"""Google ADK analytics agent grounded on Knowledge Catalog and BigQuery Graph.

Connects directly to Google Cloud's managed remote MCP servers via ADK McpToolset:
  - https://dataplex.googleapis.com/mcp  (search_entries, lookup_context)
  - https://bigquery.googleapis.com/mcp  (execute_sql_readonly)
"""

import os

import google.auth
import google.auth.transport.requests
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.genai import types

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
PROJECT_NUMBER = os.environ["GOOGLE_CLOUD_PROJECT_NUMBER"]
LOCATION = os.environ.get("BQ_LOCATION", "us")
DATASET = os.environ.get("BQ_DATASET", "demo")
GRAPH_NAME = os.environ.get("BQ_GRAPH_NAME", "CommerceGraph")
GRAPH_FQN = f"{PROJECT_ID}.{DATASET}.{GRAPH_NAME}"

creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
creds.refresh(google.auth.transport.requests.Request())
MCP_HEADERS = {
    "Authorization": f"Bearer {creds.token}",
    "x-goog-user-project": PROJECT_ID,
}

knowledge_catalog_mcp = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://dataplex.googleapis.com/mcp",
        headers=MCP_HEADERS,
    ),
    tool_filter=["search_entries", "lookup_context"],
)

bigquery_mcp = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="https://bigquery.googleapis.com/mcp",
        headers=MCP_HEADERS,
    ),
    tool_filter=["execute_sql_readonly"],
)

root_agent = Agent(
    name="commerce_graph_analyst",
    model="gemini-4-hydrogen",
    description="Answers business analytics questions using managed Knowledge Catalog and BigQuery MCP servers.",
    generate_content_config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="LOW"),
    ),
    instruction=f"""You are a BigQuery analytics agent grounded ONLY on Knowledge Catalog and `{GRAPH_FQN}`.
Project ID: `{PROJECT_ID}` (project number: `{PROJECT_NUMBER}`, location: `{LOCATION}`).

1. If catalog context is not loaded yet in this session, call `search_entries` with
   `projectId="{PROJECT_ID}"`, `query="{GRAPH_NAME}"`, `scopeType="PROJECT"`,
   `scopeId="{PROJECT_NUMBER}"`, `pageSize=20`. Collect `dataplexEntry.name` entries whose
   `entryType` ends with `/bigquery-graph-node` and pass them to `lookup_context`
   (`projectId="{PROJECT_ID}"`, `location="{LOCATION}"`).
2. For metrics, query `GRAPH_EXPAND('{GRAPH_FQN}', start_node => '<OrderItem|Orders|SupportTicket|Customer>')`.
   Default flattened output prefixes every column as `<NodeLabel>_<property>` (such as `Customer_segment`
   or `Orders_gross_revenue`). Wrap `semanticRole: MEASURE` fields in `AGG(...)`, never in `SUM`/`AVG`,
   and filter on raw `DIMENSION` fields inside `WHERE`.
3. Check base-table `sampleValues` for exact categorical literals and casing.
4. For entity-path or root-cause questions, use ISO GQL (GRAPH `{GRAPH_FQN}` MATCH ... RETURN ...).
5. Run queries with `execute_sql_readonly` (`projectId="{PROJECT_ID}"`). If the question asks for
   metrics absent from the catalog, do not invent columns; state clearly what is missing.""",
    tools=[knowledge_catalog_mcp, bigquery_mcp],
)
