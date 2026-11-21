#!/usr/bin/env python3
"""Isolated-session programmatic evaluation harness for agent/agent.py.

Runs every question in a fresh ADK InMemoryRunner + McpToolset session (zero
cross-turn leakage) and grades both process invariants (cold discovery before SQL,
graph-only queries, AGG() on MEASURE fields, exact MCP SQL error counts) and
independent ground-truth results (numeric values, NULL-vs-0 rules, abstention).

Usage:
  python3 agent/eval.py --suite all --runs 3 --concurrency 2
"""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from google.adk.runners import InMemoryRunner
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.agent import build_agent

ORIGINAL_QUESTIONS = [
    ("Q1", "For Enterprise customers, how much did we sell in Accessories and what was the total shipping on those orders?"),
    ("Q2", "What is our return rate by customer segment?"),
    ("Q3", "How many paying customers do we have in each segment, and how many in each product category within Enterprise?"),
    ("Q4", "By customer segment, show me GMV alongside total support tickets and total resolution hours."),
    ("Q5", "For Enterprise, what is the average support resolution hours per order?"),
    ("Q6", "Which Enterprise customer had a refunded order, and what support tickets did they open?"),
    ("Q7", "What is our net profit margin after warehouse rent and shipping costs by segment?"),
    ("Q8", "For Enterprise orders over $500, what was the total gross revenue and total shipping?"),
    ("Q9", "For every customer segment, compare total GMV, return rate, paying customers, Hardware sales, shipping on orders that included Accessories, and support resolution hours per dollar of GMV, without dropping customers who have not ordered yet."),
]

HELDOUT_QUESTIONS = [
    ("H1", "Total delivery charges on orders containing at least one Hardware item, by segment?"),
    ("H2", "What share of the value of orders that included Hardware was later refunded?"),
    ("H3", "How many customers have never bought anything, and did any of them contact support?"),
    ("H4", "How did sales trend month over month?"),
    ("H5", "Gross and net revenue after refunds and payment-processing fees by segment?"),
    ("H6", "Which customer needed the most support time per dollar spent?"),
    ("H7", "How much software did our enterprise accounts buy?"),
    ("H8", "For customers who contacted support, what is the total value of their orders?"),
]

MEASURE_NAMES = (
    "gross_revenue",
    "order_count",
    "total_shipping",
    "refunded_revenue",
    "refund_rate_pct",
    "completed_buyer_count",
    "item_sales",
    "ticket_count",
    "total_resolution_hours",
)

RAW_TABLE_RE = re.compile(
    r"\bdemo\.(customers|orders|order_items|support_tickets)\b", re.IGNORECASE
)
BAD_MEASURE_AGG_RE = re.compile(
    r"\b(?:SUM|AVG|COUNT)\s*\(\s*[A-Za-z0-9_]*(" + "|".join(MEASURE_NAMES) + r")\b",
    re.IGNORECASE,
)


def parse_bq_mcp_response(resp_obj: Any) -> tuple[bool, list[dict[str, Any]], str]:
    """Parse BigQuery MCP execute_sql_readonly response, checking outer isError."""
    outer_is_error = bool(isinstance(resp_obj, dict) and resp_obj.get("isError"))
    text_blob = ""
    if isinstance(resp_obj, dict):
        for item in resp_obj.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text_blob += item.get("text", "")
        if not text_blob and "structuredContent" in resp_obj:
            text_blob = json.dumps(resp_obj["structuredContent"])
    else:
        text_blob = str(resp_obj)

    if outer_is_error:
        return False, [], text_blob[:500]

    try:
        parsed = json.loads(text_blob)
    except Exception:
        return False, [], text_blob[:500]

    if isinstance(parsed, dict) and ("error" in parsed or parsed.get("isError")):
        return False, [], json.dumps(parsed)[:500]

    fields = [f["name"] for f in parsed.get("schema", {}).get("fields", [])]
    rows_out = [
        dict(zip(fields, [cell.get("v") for cell in r.get("f", [])]))
        for r in parsed.get("rows", [])
    ]
    return True, rows_out, text_blob[:500]


def _has_num(target: float, text: str) -> bool:
    for n in re.findall(r"-?\d+(?:,\d{3})*(?:\.\d+)?", text):
        try:
            v = float(n.replace(",", ""))
            if abs(v - target) <= max(1e-4, abs(target) * 1e-3):
                return True
        except ValueError:
            pass
    return False


def _row_by_key(rows: list[dict[str, Any]], value_sub: str) -> dict[str, Any] | None:
    target = value_sub.lower()
    for row in rows:
        for v in row.values():
            if v is not None and str(v).lower() == target:
                return row
    return None


def _as_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def grade_trace(qid: str, trace: dict[str, Any]) -> dict[str, Any]:
    """Programmatically verify process invariants and ground-truth results."""
    calls = trace["tool_calls"]
    tool_names = [c["tool"] for c in calls]
    sql_calls = [c for c in calls if c["tool"] == "execute_sql_readonly"]
    answer = trace["final_answer"]
    ans_low = answer.lower()

    issues: list[str] = []

    # 1. Cold discovery before SQL (and even before abstaining)
    if "search_entries" not in tool_names or "lookup_context" not in tool_names:
        issues.append(f"MISSING_DISCOVERY(tools={tool_names})")
    elif sql_calls and tool_names.index("lookup_context") > tool_names.index("execute_sql_readonly"):
        issues.append("DISCOVERY_AFTER_SQL")

    # 2. SQL governance and exact error count
    sql_errors = 0
    ok_rows: list[dict[str, Any]] = []
    for c in sql_calls:
        q = c.get("raw_query", "")
        if RAW_TABLE_RE.search(q):
            issues.append("RAW_BASE_TABLE_QUERY")
        if not ("GRAPH_EXPAND" in q.upper() or "GRAPH " in q.upper()):
            issues.append("NOT_GRAPH_QUERY")
        if BAD_MEASURE_AGG_RE.search(q):
            issues.append("MEASURE_WRAPPED_IN_NON_AGG")
        if c.get("ok"):
            ok_rows.extend(c.get("rows", []))
        else:
            sql_errors += 1

    # 3. Ground-truth result assertions (including NULL vs 0 checks)
    gt_ok = True
    gt_note = ""

    if qid == "Q1":
        if not (_has_num(100, answer) and _has_num(30, answer)):
            gt_ok, gt_note = False, "Expected 100 and 30"
    elif qid == "Q2":
        if not (_has_num(10, answer) and _has_num(0, answer)):
            gt_ok, gt_note = False, "Expected 10% and 0%"
    elif qid == "Q3":
        if not all(w in ans_low for w in ("enterprise", "smb", "accessory", "hardware")) or not _has_num(1, answer):
            gt_ok, gt_note = False, "Expected Enterprise=1, SMB=1, Accessory=1, Hardware=1"
    elif qid == "Q4":
        if not (_has_num(1000, answer) and _has_num(3, answer) and _has_num(14, answer) and _has_num(200, answer)):
            gt_ok, gt_note = False, "Expected Ent(1000, 3, 14) and SMB(200, 0, 0)"
        else:
            smb_row = _row_by_key(ok_rows, "SMB")
            if smb_row:
                null_cols = [k for k, v in smb_row.items() if v is None]
                if null_cols:
                    gt_ok, gt_note = False, f"NULL_VS_ZERO: SMB had NULL in {null_cols} instead of 0"
    elif qid == "Q5":
        if _has_num(7, answer):
            gt_note = "7.0 (14/2)"
        elif _has_num(6, answer):
            gt_note = "6.0 (12/2)"
        else:
            gt_ok, gt_note = False, "Expected 7.0 (14/2) or 6.0 (12/2)"
    elif qid == "Q6":
        if not all(w in ans_low for w in ("acme", "tkt-001", "tkt-002", "billing", "shipping")):
            gt_ok, gt_note = False, "Expected Acme, Tkt-001 (billing), Tkt-002 (shipping)"
    elif qid == "Q7":
        # Partial-grounding policy: must refuse net profit margin / warehouse rent; optional grounded SQL for revenue/shipping is OK
        if not ("warehouse rent" in ans_low and any(w in ans_low for w in ("not", "missing", "absent", "cannot", "no "))):
            gt_ok, gt_note = False, "Expected refusal naming missing warehouse rent"
    elif qid == "Q8":
        if not (_has_num(900, answer) and _has_num(30, answer)):
            gt_ok, gt_note = False, "Expected 900 and 30"
    elif qid == "Q9":
        missing_n = [x for x in (1000, 10, 1, 900, 30, 0.014, 200) if not _has_num(x, answer)]
        if missing_n:
            gt_ok, gt_note = False, f"Missing numbers: {missing_n}"
        else:
            smb_row = _row_by_key(ok_rows, "SMB")
            if smb_row:
                null_cols = [k for k, v in smb_row.items() if v is None]
                if null_cols:
                    gt_ok, gt_note = False, f"NULL_VS_ZERO: SMB had NULL in {null_cols} instead of 0/0.0"
    elif qid == "H1":
        if _has_num(70, answer) and not _has_num(40, answer):
            gt_ok, gt_note = False, "FANOUT_TRAP: got 70 instead of 40"
        elif not _has_num(40, answer):
            gt_ok, gt_note = False, "Expected Enterprise=40"
    elif qid == "H2":
        if _has_num(5.26, answer) or _has_num(5.3, answer):
            gt_ok, gt_note = False, "FANOUT_TRAP: got 5.26% instead of 10.0%"
        elif not _has_num(10, answer):
            gt_ok, gt_note = False, "Expected 10.0%"
    elif qid == "H3":
        if not ("beta" in ans_low and "yes" in ans_low and _has_num(1, answer)):
            gt_ok, gt_note = False, "Expected 1 customer (Beta) and yes (contacted support)"
    elif qid == "H4":
        for c in sql_calls:
            if "FARM_FINGERPRINT" in c.get("raw_query", "").upper():
                issues.append("FELL_FOR_SYNTHETIC_DATE_TRAP")
        if sql_calls:
            issues.append(f"UNEXPECTED_SQL_ON_ABSTAIN({len(sql_calls)})")
        if not any(w in ans_low for w in ("date", "time", "month", "timestamp")):
            gt_ok, gt_note = False, "Expected abstention explaining missing date/time dimension"
    elif qid == "H5":
        if not (
            _has_num(1000, answer)
            and _has_num(900, answer)
            and _has_num(200, answer)
            and "processing" in ans_low
            and any(w in ans_low for w in ("missing", "not", "absent", "unavailable", "cannot"))
        ):
            gt_ok, gt_note = False, "Expected gross 1000/200, net-after-refunds 900/200, and payment-processing fees missing"
    elif qid == "H6":
        if not ("acme" in ans_low and _has_num(0.012, answer)):
            gt_ok, gt_note = False, "Expected Acme = 0.012"
        elif any(bad in ans_low for bad in ("infinity", "beta needed the most")):
            gt_ok, gt_note = False, "ZERO_DENOM_TRAP: treated Beta as highest/infinity"
        else:
            # Verify Beta ratio is NULL (denominator 0) and Cozy ratio is 0.0 (0 hours / $200)
            beta_row = _row_by_key(ok_rows, "Beta") or _row_by_key(ok_rows, "Cust-002")
            cozy_row = _row_by_key(ok_rows, "Cozy") or _row_by_key(ok_rows, "Cust-003")
            if beta_row:
                ratio_vals = [v for k, v in beta_row.items() if "per" in k.lower() or "ratio" in k.lower()]
                if ratio_vals and any(_as_float(v) is not None for v in ratio_vals):
                    gt_ok, gt_note = False, f"ZERO_DENOM_COALESCED: Beta ratio={ratio_vals} (expected NULL)"
            if gt_ok and cozy_row:
                ratio_vals = [v for k, v in cozy_row.items() if "per" in k.lower() or "ratio" in k.lower()]
                if ratio_vals and all(_as_float(v) is None for v in ratio_vals):
                    gt_ok, gt_note = False, f"NULL_VS_ZERO: Cozy ratio={ratio_vals} (expected 0.0)"
    elif qid == "H7":
        if not (_has_num(0, answer) or "no " in ans_low or "none" in ans_low):
            gt_ok, gt_note = False, "Expected $0 / no Enterprise Software purchases"
        elif _has_num(200, answer) and "smb" not in ans_low and "cozy" not in ans_low:
            gt_ok, gt_note = False, "WRONG_SEGMENT: returned SMB's $200 as Enterprise"
    elif qid == "H8":
        if _has_num(2000, answer) and not _has_num(1000, answer):
            gt_ok, gt_note = False, "CHASM_FANOUT_TRAP: got $2,000 instead of $1,000"
        elif not _has_num(1000, answer):
            gt_ok, gt_note = False, "Expected $1,000 total order value"

    passed = gt_ok and (len(issues) == 0)
    passed_attempt_1 = passed and (sql_errors == 0)
    return {
        "passed": passed,
        "passed_attempt_1": passed_attempt_1,
        "gt_ok": gt_ok,
        "gt_note": gt_note,
        "sql_errors": sql_errors,
        "issues": issues,
        "num_tool_calls": len(calls),
        "num_sql_calls": len(sql_calls),
    }


async def run_one(run_idx: int, qid: str, question: str) -> dict[str, Any]:
    """Run one question in a completely fresh session and MCP toolset."""
    recorded_calls: list[dict[str, Any]] = []

    def before_cb(tool: Any, args: dict[str, Any], _ctx: Any) -> None:
        entry: dict[str, Any] = {"tool": tool.name, "args": dict(args)}
        if tool.name == "execute_sql_readonly" and "query" in args:
            entry["raw_query"] = args["query"]
        recorded_calls.append(entry)
        return None

    def after_cb(tool: Any, _args: dict[str, Any], _ctx: Any, tool_response: Any) -> None:
        for entry in reversed(recorded_calls):
            if entry["tool"] == tool.name and "response_len" not in entry:
                entry["response_len"] = len(str(tool_response))
                if tool.name == "execute_sql_readonly":
                    ok, rows, preview = parse_bq_mcp_response(tool_response)
                    entry["ok"] = ok
                    entry["rows"] = rows
                    entry["preview"] = preview
                break
        return None

    agent, kc_mcp, bq_mcp = build_agent(
        name=f"eval_{qid}_r{run_idx}",
        before_tool_callback=before_cb,
        after_tool_callback=after_cb,
    )
    runner = InMemoryRunner(agent=agent, app_name=f"eval_{qid}_r{run_idx}")
    session = await runner.session_service.create_session(
        app_name=f"eval_{qid}_r{run_idx}", user_id="evaluator"
    )

    t0 = time.time()
    final_text = ""
    err_msg = None
    try:
        async for event in runner.run_async(
            user_id="evaluator",
            session_id=session.id,
            new_message=types.Content(
                role="user", parts=[types.Part.from_text(text=question)]
            ),
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text and event.is_final_response():
                        final_text += part.text
    except Exception as exc:
        err_msg = repr(exc)
    finally:
        await runner.close()
        await kc_mcp.close()
        await bq_mcp.close()

    ms = int((time.time() - t0) * 1000)
    trace = {
        "run": run_idx,
        "qid": qid,
        "question": question,
        "ms": ms,
        "error": err_msg,
        "tool_calls": recorded_calls,
        "final_answer": final_text.strip(),
    }
    trace["grade"] = grade_trace(qid, trace)
    g = trace["grade"]
    tag = "PASS@1" if g["passed_attempt_1"] and not err_msg else ("PASS* " if g["passed"] and not err_msg else "FAIL  ")
    print(
        f"[run {run_idx}] {qid:3s} {tag} ({ms:5d}ms) "
        f"sql_calls={g['num_sql_calls']} sql_err={g['sql_errors']} "
        f"issues={g['issues']} note={g['gt_note']}"
    )
    return trace


async def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated-session eval harness for agent/agent.py")
    parser.add_argument("--suite", choices=["original", "heldout", "all"], default="all")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--out", type=str, default="")
    args = parser.parse_args()

    questions: list[tuple[str, str]] = []
    if args.suite in ("original", "all"):
        questions.extend(ORIGINAL_QUESTIONS)
    if args.suite in ("heldout", "all"):
        questions.extend(HELDOUT_QUESTIONS)

    sem = asyncio.Semaphore(args.concurrency)

    async def bounded(run_idx: int, qid: str, q: str) -> dict[str, Any]:
        async with sem:
            return await run_one(run_idx, qid, q)

    tasks = [
        bounded(r, qid, q)
        for r in range(1, args.runs + 1)
        for qid, q in questions
    ]
    traces = await asyncio.gather(*tasks)

    def summarize(subset: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(subset)
        passed = sum(1 for t in subset if t["grade"]["passed"] and not t["error"])
        pass1 = sum(1 for t in subset if t["grade"]["passed_attempt_1"] and not t["error"])
        sql_err = sum(t["grade"]["sql_errors"] for t in subset)
        return {
            "total": total,
            "passed": passed,
            "pass_attempt_1": pass1,
            "sql_errors": sql_err,
        }

    orig_traces = [t for t in traces if t["qid"].startswith("Q")]
    held_traces = [t for t in traces if t["qid"].startswith("H")]
    summary = {
        "runs": args.runs,
        "original_Q1_Q9": summarize(orig_traces),
        "heldout_H1_H8": summarize(held_traces),
        "overall": summarize(traces),
    }

    print("\n=== EVAL SUMMARY ===")
    print(json.dumps(summary, indent=2))

    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "traces": traces}, indent=2, default=str))
        print(f"Saved full traces to {args.out}")

    if summary["overall"]["passed"] != summary["overall"]["total"]:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
