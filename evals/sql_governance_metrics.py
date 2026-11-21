"""Deterministic native ADK custom metrics for Knowledge Catalog + BigQuery Graph MCP.

Registered in evals/eval_config.json under `custom_metrics` and executed directly
by `adk eval` alongside ADK's built-in LLM judges (`final_response_match_v2`,
`hallucinations_v1`).
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


def _response_has_sql_error(resp_obj: Any) -> bool:
    """Detect BigQuery MCP errors in either the outer MCP envelope or JSON body."""
    if resp_obj is None:
        return True
    if isinstance(resp_obj, dict):
        if resp_obj.get("isError"):
            return True
        text_blob = ""
        for item in resp_obj.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text_blob += item.get("text", "")
        if text_blob:
            try:
                parsed = json.loads(text_blob)
                if isinstance(parsed, dict) and ("error" in parsed or parsed.get("isError")):
                    return True
            except Exception:
                return True
    return False


def _resolve_threshold(eval_metric: EvalMetric) -> float:
    if eval_metric.threshold is not None:
        return float(eval_metric.threshold)
    if getattr(eval_metric, "criterion", None) is not None and eval_metric.criterion.threshold is not None:
        return float(eval_metric.criterion.threshold)
    return 1.0


def catalog_discovery_first(
    eval_metric: EvalMetric,
    actual_invocations: list[Invocation],
    expected_invocations: Optional[list[Invocation]] = None,
    conversation_scenario: Optional[ConversationScenario] = None,
) -> EvaluationResult:
    """Verify Knowledge Catalog discovery (`search_entries` -> `lookup_context`) precedes SQL."""
    per_inv: list[PerInvocationResult] = []
    scores: list[float] = []
    threshold = _resolve_threshold(eval_metric)

    for idx, inv in enumerate(actual_invocations):
        pairs = get_all_tool_calls_with_responses(inv.intermediate_data)
        names = [tc.name for tc, _ in pairs]

        has_search = "search_entries" in names
        has_lookup = "lookup_context" in names
        sql_indices = [i for i, n in enumerate(names) if n == "execute_sql_readonly"]

        ok = has_search and has_lookup
        if ok and sql_indices:
            ok = names.index("lookup_context") < sql_indices[0]

        score = 1.0 if ok else 0.0
        scores.append(score)
        exp = expected_invocations[idx] if expected_invocations and idx < len(expected_invocations) else None
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


def semantic_graph_sql_governance(
    eval_metric: EvalMetric,
    actual_invocations: list[Invocation],
    expected_invocations: Optional[list[Invocation]] = None,
    conversation_scenario: Optional[ConversationScenario] = None,
) -> EvaluationResult:
    """Verify every SQL call targets the semantic graph, uses AGG() on measures, and has 0 MCP errors."""
    per_inv: list[PerInvocationResult] = []
    scores: list[float] = []
    threshold = _resolve_threshold(eval_metric)

    for idx, inv in enumerate(actual_invocations):
        pairs = get_all_tool_calls_with_responses(inv.intermediate_data)
        sql_pairs = [(tc, tr) for tc, tr in pairs if tc.name == "execute_sql_readonly"]

        ok = True
        for tc, tr in sql_pairs:
            query = str((tc.args or {}).get("query", ""))
            if RAW_TABLE_RE.search(query):
                ok = False
            if not ("GRAPH_EXPAND" in query.upper() or "GRAPH " in query.upper()):
                ok = False
            if BAD_MEASURE_AGG_RE.search(query):
                ok = False
            if "FARM_FINGERPRINT" in query.upper():
                ok = False
            resp_payload = tr.response if tr is not None else None
            if _response_has_sql_error(resp_payload):
                ok = False

        score = 1.0 if ok else 0.0
        scores.append(score)
        exp = expected_invocations[idx] if expected_invocations and idx < len(expected_invocations) else None
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
