"""Minimal ADK 2 BigQuery Semantic Graph agent."""

from __future__ import annotations

import asyncio
from functools import cache
import logging
import os
from pathlib import Path
import threading
import time

from dotenv import load_dotenv
import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.adk import Agent, Context
from google.adk.apps import App
from google.adk.integrations.bigquery import BigQueryToolset
from google.adk.integrations.bigquery.config import BigQueryToolConfig, WriteMode
from google.adk.models.google_llm import Gemini
from google.adk.skills import load_skills_from_dir
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.skill_toolset import SkillDiscoveryMode, SkillToolset
from google.genai import types
import requests
import yaml

load_dotenv()

logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable `{name}` is not set.")
    return value


def _resolve_skills_dir() -> Path:
    candidates = (
        Path(__file__).resolve().parents[1] / "skills",
        Path(__file__).resolve().parents[2] / "skills",
    )
    for path in candidates:
        if path.is_dir():
            return path
    searched = ", ".join(str(p) for p in candidates)
    raise FileNotFoundError(f"Skills directory not found in: {searched}")


PROJECT_ID = _require_env("GOOGLE_CLOUD_PROJECT")
BQ_PROJECT_ID = os.environ.get("BQ_PROJECT_ID", "").strip() or PROJECT_ID
LOCATION = os.environ.get("BQ_LOCATION", "us")
DATASET = os.environ.get("BQ_DATASET", "commerce_bench")
MODEL_ID = (
    os.environ.get("MODEL_ID")
    or os.environ.get("EVAL_MODEL_ID")
    or "gemini-4-hydrogen"
)
THINKING_LEVEL = os.environ.get("THINKING_LEVEL", "LOW")
SKILLS_DIR = _resolve_skills_dir()

_GRAPH_CONTEXT_TTL_S = 600.0
_CACHE_LOCK = threading.Lock()
_CACHED_GRAPH_CONTEXT: tuple[float, str] | None = None


@cache
def _session() -> AuthorizedSession:
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        quota_project_id=BQ_PROJECT_ID,
    )
    return AuthorizedSession(creds)


def _fetch_graph_context() -> str:
    http = _session()
    search_url = (
        f"https://dataplex.googleapis.com/v1/projects/{BQ_PROJECT_ID}"
        "/locations/global:searchEntries"
        "?fields=results.dataplexEntry(name,entryType),nextPageToken"
    )
    nodes: set[str] = set()
    page_token: str | None = None
    while True:
        payload: dict[str, object] = {
            "scope": f"projects/{BQ_PROJECT_ID}",
            "query": f"name:{DATASET}/propertyGraphs/",
            "pageSize": 100,
        }
        if page_token:
            payload["pageToken"] = page_token
        search_resp = http.post(search_url, json=payload, timeout=30)
        search_resp.raise_for_status()
        body = search_resp.json()
        for item in body.get("results", []):
            entry = item.get("dataplexEntry", {})
            name = entry.get("name", "")
            if (
                f"/datasets/{DATASET}/propertyGraphs/" in name
                and entry.get("entryType", "").endswith("/bigquery-graph-node")
            ):
                nodes.add(name)
        page_token = body.get("nextPageToken")
        if not page_token:
            break

    if not nodes:
        return ""

    lookup_resp = http.post(
        f"https://dataplex.googleapis.com/v1/projects/{BQ_PROJECT_ID}"
        f"/locations/{LOCATION}:lookupContext",
        json={"resources": sorted(nodes)},
        timeout=30,
    )
    lookup_resp.raise_for_status()

    context_yaml = lookup_resp.json().get("context", "")
    doc = yaml.safe_load(context_yaml)
    if isinstance(doc, dict) and doc.pop("sampleQueries", None) is not None:
        context_yaml = yaml.safe_dump(doc, sort_keys=False)
    return context_yaml.strip()


def _get_graph_context() -> str:
    global _CACHED_GRAPH_CONTEXT
    with _CACHE_LOCK:
        if _CACHED_GRAPH_CONTEXT is not None:
            expires_at, cached = _CACHED_GRAPH_CONTEXT
            if time.monotonic() < expires_at:
                return cached
        fetched = _fetch_graph_context()
        if fetched:
            _CACHED_GRAPH_CONTEXT = (time.monotonic() + _GRAPH_CONTEXT_TTL_S, fetched)
        return fetched


async def _ensure_graph_context(ctx: Context) -> types.Content | None:
    if ctx.state.get("graph_context"):
        return None
    try:
        graph_context = await asyncio.to_thread(_get_graph_context)
    except (requests.RequestException, yaml.YAMLError) as exc:
        logger.warning(
            "Failed to load Knowledge Catalog graph context for %s.%s: %s",
            BQ_PROJECT_ID,
            DATASET,
            exc,
        )
        return types.Content(
            role="model",
            parts=[
                types.Part.from_text(
                    text=(
                        f"Graph context for `{BQ_PROJECT_ID}.{DATASET}` is temporarily "
                        "unavailable from Knowledge Catalog. Please try again shortly."
                    )
                )
            ],
        )
    if not graph_context:
        logger.warning(
            "No Knowledge Catalog property graph nodes found for %s.%s.",
            BQ_PROJECT_ID,
            DATASET,
        )
        return types.Content(
            role="model",
            parts=[
                types.Part.from_text(
                    text=(
                        f"No BigQuery Property Graph metadata was found in Knowledge "
                        f"Catalog for `{BQ_PROJECT_ID}.{DATASET}`."
                    )
                )
            ],
        )
    ctx.state["graph_context"] = graph_context
    return None


def _cap_dry_runs(
    tool: BaseTool,
    args: dict[str, object],
    ctx: Context,
) -> dict[str, object] | None:
    if tool.name == "execute_sql" and args.get("dry_run") is True:
        count = int(ctx.state.get("temp:dry_runs", 0)) + 1
        ctx.state["temp:dry_runs"] = count
        if count > 1:
            return {
                "status": "SKIPPED",
                "message": (
                    "Dry-run limit reached for this turn. Execute the complete "
                    "query directly with dry_run=False."
                ),
            }
    return None


root_agent = Agent(
    name="bq_semantic_graph_analyst",
    model=Gemini(
        model=MODEL_ID,
        client_kwargs={"vertexai": True, "project": PROJECT_ID, "location": "global"},
    ),
    description=(
        "Answers analytics questions over BigQuery Property Graphs using "
        "Knowledge Catalog metadata and governed measures."
    ),
    generate_content_config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level=THINKING_LEVEL),
        http_options=types.HttpOptions(
            timeout=180_000,
            retry_options=types.HttpRetryOptions(attempts=4),
        ),
    ),
    before_agent_callback=_ensure_graph_context,
    before_tool_callback=_cap_dry_runs,
    instruction=(
        f"You are a data analytics assistant for BigQuery dataset `{BQ_PROJECT_ID}.{DATASET}` "
        f"(location `{LOCATION}`). Answer accurately using governed data and never guess numbers. "
        "`execute_sql` already enforces read-only mode and a 1 GB scan cap automatically; "
        "run your composed query directly (`dry_run=False`) instead of dry-running individual CTEs.\n\n"
        "```yaml\n{graph_context?}\n```"
    ),
    tools=[
        SkillToolset(
            skills=load_skills_from_dir(SKILLS_DIR),
            discovery_mode=SkillDiscoveryMode.EAGER,
            # Keep execute_sql in tool_filter so SkillToolset exposes it once load_skill runs.
            tool_filter=["load_skill", "execute_sql"],
            additional_tools=[
                BigQueryToolset(
                    tool_filter=["execute_sql"],
                    bigquery_tool_config=BigQueryToolConfig(
                        write_mode=WriteMode.BLOCKED,
                        compute_project_id=BQ_PROJECT_ID,
                        default_project_id=BQ_PROJECT_ID,
                        location=LOCATION,
                        max_query_result_rows=200,
                        maximum_bytes_billed=1_073_741_824,
                    ),
                ),
            ],
        ),
    ],
)

app = App(name="agent_under_test", root_agent=root_agent)
