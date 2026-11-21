"""Google ADK analytics agent grounded on Knowledge Catalog and BigQuery Graph.

Connects directly to Google Cloud's managed remote MCP servers via ADK McpToolset:
  - https://dataplex.googleapis.com/mcp  (search_entries, lookup_context)
  - https://bigquery.googleapis.com/mcp  (execute_sql_readonly)
"""

import os
from typing import Any, Callable

import google.auth
import google.auth.transport.requests
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.genai import types

load_dotenv()

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
PROJECT_NUMBER = os.environ["GOOGLE_CLOUD_PROJECT_NUMBER"]
LOCATION = os.environ.get("BQ_LOCATION", "us")
DATASET = os.environ.get("BQ_DATASET", "demo")
GRAPH_NAME = os.environ.get("BQ_GRAPH_NAME", "CommerceGraph")
GRAPH_FQN = f"{PROJECT_ID}.{DATASET}.{GRAPH_NAME}"
BQ_RESERVATION = os.environ.get("BQ_RESERVATION", "")

_CREDS, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
_AUTH_REQUEST = google.auth.transport.requests.Request()


def mcp_headers(_readonly_context: Any = None) -> dict[str, str]:
    """Return fresh OAuth headers on every MCP call (avoids 1-hour static token expiry)."""
    if not _CREDS.valid or _CREDS.expired:
        _CREDS.refresh(_AUTH_REQUEST)
    return {
        "Authorization": f"Bearer {_CREDS.token}",
        "x-goog-user-project": PROJECT_ID,
    }


def _inject_reservation(tool: Any, args: dict[str, Any], _tool_context: Any) -> None:
    """Optional per-job BigQuery reservation hook when BQ_RESERVATION is configured."""
    if BQ_RESERVATION and tool.name == "execute_sql_readonly" and "query" in args:
        query = args["query"].strip()
        if "SET @@reservation" not in query:
            args["query"] = f"SET @@reservation = '{BQ_RESERVATION}';\n{query}"
    return None


AGENT_INSTRUCTION = f"""You are a BigQuery analytics agent grounded ONLY on Knowledge Catalog and `{GRAPH_FQN}`.
Project ID: `{PROJECT_ID}` (project number: `{PROJECT_NUMBER}`, location: `{LOCATION}`).

1. Discover: If catalog context for `{GRAPH_FQN}` is not already in this conversation, call `search_entries`
   with `projectId="{PROJECT_ID}"`, `query="{GRAPH_NAME}"`, `scopeType="PROJECT"`, `scopeId="{PROJECT_NUMBER}"`,
   `pageSize=20`. Filter to entries whose `entryType` ends with `/bigquery-graph-node` and whose `name` belongs
   to `/datasets/{DATASET}/propertyGraphs/{GRAPH_NAME}/`, then call `lookup_context`
   (`projectId="{PROJECT_ID}"`, `location="{LOCATION}"`) on those node entries.
2. Ground: Use ONLY node labels, properties, measures, synonyms, and categorical `sampleValues` returned by
   `lookup_context`. Never guess column names, node labels, or filter literals.
3. Aggregate queries: Query `GRAPH_EXPAND('{GRAPH_FQN}', start_node => '<NodeLabel>')`, picking the node label
   whose grain matches the finest filter or grouping needed. Flattened columns are named `<NodeLabel>_<property>`.
   Wrap `semanticRole: MEASURE` fields in `AGG(...)` only (never `SUM`/`COUNT`/`AVG`, and never re-derive from
   raw columns). Filter and group on `DIMENSION` fields. One `GRAPH_EXPAND` from the finest-grain node already
   exposes grain-safe measures of every node reachable along its outgoing `N:1` chain; split into separate CTEs
   and join at the shared grouping level only for sibling branches unreachable from one start node, without
   dropping groups present on only one side. Counts and sums over no matching rows are `0`; a ratio is `NULL`
   only when its denominator is `0` or absent (never `COALESCE` a ratio to `0`).
4. Entity and path queries: Use ISO GQL (`GRAPH `{GRAPH_FQN}` MATCH ... RETURN ...`), avoiding aggregations over
   paths that multiply rows.
5. Execute via `execute_sql_readonly` (`projectId="{PROJECT_ID}"`). Never query raw base tables directly. If a
   query errors, inspect the message, re-check the catalog context, and retry.
6. Abstain honestly: If any requested concept has no supporting property or measure in the catalog, state clearly
   what is missing and do not approximate or fabricate it; answer only the grounded parts."""


def build_agent(
    *,
    name: str = "commerce_graph_analyst",
    before_tool_callback: Callable[..., Any] | None = None,
    after_tool_callback: Callable[..., Any] | None = None,
) -> tuple[Agent, McpToolset, McpToolset]:
    """Construct an Agent with fresh Knowledge Catalog and BigQuery MCP toolsets."""
    kc_mcp = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url="https://dataplex.googleapis.com/mcp",
        ),
        header_provider=mcp_headers,
        tool_filter=["search_entries", "lookup_context"],
    )
    bq_mcp = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url="https://bigquery.googleapis.com/mcp",
        ),
        header_provider=mcp_headers,
        tool_filter=["execute_sql_readonly"],
    )

    def combined_before_cb(tool: Any, args: dict[str, Any], tool_context: Any) -> Any:
        res = None
        if before_tool_callback is not None:
            res = before_tool_callback(tool, args, tool_context)
        _inject_reservation(tool, args, tool_context)
        return res

    agent = Agent(
        name=name,
        model="gemini-4-hydrogen",
        description="Answers business analytics questions using managed Knowledge Catalog and BigQuery MCP servers.",
        generate_content_config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        ),
        before_tool_callback=combined_before_cb if (before_tool_callback or BQ_RESERVATION) else None,
        after_tool_callback=after_tool_callback,
        instruction=AGENT_INSTRUCTION,
        tools=[kc_mcp, bq_mcp],
    )
    return agent, kc_mcp, bq_mcp


root_agent, knowledge_catalog_mcp, bigquery_mcp = build_agent()
