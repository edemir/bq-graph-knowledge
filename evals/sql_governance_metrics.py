"""Deterministic native ADK custom metric for BigQuery Semantic Graph SQL/GQL governance.

Tool call sequencing (`search_entries` -> `lookup_context` -> `execute_sql_readonly`)
is enforced natively by ADK's built-in `tool_trajectory_avg_score` (`IN_ORDER`,
`ignore_args: true`). This module covers only SQL/GQL payload checks that
argument-ignoring trajectory matching and LLM judges cannot check deterministically:
  - Expected query dialect per invocation (`-graph_expand`, `-gql_match`, `-no_sql`, `-graph_any`)
  - No raw base-table queries (must target the semantic graph)
  - No SUM/AVG/COUNT wrapping semantic MEASURE fields
  - Zero BigQuery MCP execution errors (outer `isError` or JSON error body)
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from google.adk.evaluation.eval_case import (
    ConversationScenario,
    Invocation,
    get_all_tool_calls_with_responses,
)
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.evaluator import EvaluationResult, PerInvocationResult

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


def _resolve_threshold(eval_metric: EvalMetric) -> float:
    if eval_metric.threshold is not None:
        return float(eval_metric.threshold)
    criterion = getattr(eval_metric, "criterion", None)
    if criterion is not None and criterion.threshold is not None:
        return float(criterion.threshold)
    return 1.0


def _expected_mode(expected_invocation: Optional[Invocation]) -> str:
    """Derive expected SQL/GQL dialect from expected invocation_id suffix."""
    if expected_invocation is None or not expected_invocation.invocation_id:
        return "graph_any"
    inv_id = expected_invocation.invocation_id.lower()
    for mode in ("graph_expand", "gql_match", "no_sql", "graph_any"):
        if inv_id.endswith(f"-{mode}"):
            return mode
    return "graph_any"


def _response_has_sql_error(resp_obj: Any) -> bool:
    """Detect BigQuery MCP errors in either the outer MCP envelope or JSON body."""
    if resp_obj is None:
        return True
    if isinstance(resp_obj, dict):
        if resp_obj.get("isError"):
            return True
        text_blob = "".join(
            item.get("text", "")
            for item in resp_obj.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        )
        if text_blob:
            try:
                parsed = json.loads(text_blob)
                if isinstance(parsed, dict) and ("error" in parsed or parsed.get("isError")):
                    return True
            except Exception:
                return True
    return False


def semantic_graph_sql_governance(
    eval_metric: EvalMetric,
    actual_invocations: list[Invocation],
    expected_invocations: Optional[list[Invocation]] = None,
    conversation_scenario: Optional[ConversationScenario] = None,
) -> EvaluationResult:
    """Verify SQL/GQL dialect compliance, measure governance, and zero BigQuery MCP errors."""
    per_inv: list[PerInvocationResult] = []
    scores: list[float] = []
    threshold = _resolve_threshold(eval_metric)

    for idx, inv in enumerate(actual_invocations):
        exp = expected_invocations[idx] if expected_invocations and idx < len(expected_invocations) else None
        mode = _expected_mode(exp)

        pairs = get_all_tool_calls_with_responses(inv.intermediate_data)
        sql_pairs = [(tc, tr) for tc, tr in pairs if tc.name == "execute_sql_readonly"]

        ok = True
        if mode == "no_sql":
            ok = len(sql_pairs) == 0
        else:
            if mode in ("graph_expand", "gql_match") and not sql_pairs:
                ok = False
            for tc, tr in sql_pairs:
                query = str((tc.args or {}).get("query", ""))
                q_upper = query.upper()
                has_expand = "GRAPH_EXPAND(" in q_upper
                has_gql = "GRAPH " in q_upper and "MATCH" in q_upper

                if RAW_TABLE_RE.search(query) or BAD_MEASURE_AGG_RE.search(query):
                    ok = False
                if "FARM_FINGERPRINT" in q_upper:
                    ok = False
                if mode == "graph_expand" and not (has_expand and "AGG(" in q_upper):
                    ok = False
                elif mode == "gql_match" and not has_gql:
                    ok = False
                elif mode == "graph_any" and not (has_expand or has_gql):
                    ok = False
                if _response_has_sql_error(tr.response if tr is not None else None):
                    ok = False

        score = 1.0 if ok else 0.0
        scores.append(score)
        per_inv.append(
            PerInvocationResult(
                actual_invocation=inv,
                expected_invocation=exp,
                score=score,
                eval_status=EvalStatus.PASSED if score >= threshold else EvalStatus.FAILED,
            )
        )

    overall = sum(scores) / len(scores) if scores else 0.0
    return EvaluationResult(
        overall_score=overall,
        overall_eval_status=EvalStatus.PASSED if overall >= threshold else EvalStatus.FAILED,
        per_invocation_results=per_inv,
    )
