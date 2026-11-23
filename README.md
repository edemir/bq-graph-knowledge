# BigQuery Semantic Graph + Knowledge Catalog + AI Agents

Companion code for the three-part blog series on building a warehouse-native semantic layer with **BigQuery Graph**, **BigQuery Measures**, **Knowledge Catalog**, managed **Conversational Analytics** data agents, and a custom **Google ADK** analytics agent backed by Google Cloud's managed MCP servers.

## Repository layout

| Path | Blog part | Description |
| :--- | :---: | :--- |
| [`sql/01_seed_tables.sql`](sql/01_seed_tables.sql) | Part 1 | Creates `demo.customers`, `demo.orders`, `demo.order_items`, and `demo.support_tickets` (14 rows total) with `NOT ENFORCED` primary and foreign keys |
| [`sql/02_commerce_graph.sql`](sql/02_commerce_graph.sql) | Part 1 | Defines `demo.CommerceGraph` (`CREATE OR REPLACE PROPERTY GRAPH`) with `DEFAULT LABEL OPTIONS`, `NO PROPERTIES` on edges, grain-locked measures, derived ratios, and business synonyms |
| [`sql/03_queries.sql`](sql/03_queries.sql) | Part 1 | Part 1 verification queries: `GRAPH_EXPAND` with child filters, multi-fact `FULL OUTER JOIN`, ISO GQL `MATCH` root-cause traversal, and `AGG()` with outer windows + `HAVING` |
| [`scripts/04_publish_catalog_metadata.sh`](scripts/04_publish_catalog_metadata.sh) | Part 2 / 3 | Enables required APIs and runs idempotent Dataplex `data-profile` and `data-documentation` scans with `--enable-catalog-publishing` |
| [`scripts/05_create_ca_agent.py`](scripts/05_create_ca_agent.py) | Part 2 | Creates or updates the persistent managed Conversational Analytics data agent (`commerce-graph-agent`) grounded on `demo.CommerceGraph` via `BigQueryPropertyGraphReference` |
| [`scripts/06_query_ca_agent.py`](scripts/06_query_ca_agent.py) | Part 2 | Queries `commerce-graph-agent` via `DataChatServiceClient.chat` and prints generated SQL/GQL and final grounded answers |
| [`scripts/07_adk_data_agent_toolset.py`](scripts/07_adk_data_agent_toolset.py) | Part 2 | Delegates analytics questions from a Google ADK orchestrator (`executive_briefing_agent`) to `commerce-graph-agent` using ADK's built-in `DataAgentToolset` (`ask_data_agent`) |
| [`agent/agent.py`](agent/agent.py) | Part 3 | Custom Google ADK `root_agent` using `gemini-4-hydrogen` and `McpToolset` with dynamic OAuth `header_provider` connected to Knowledge Catalog MCP (`https://dataplex.googleapis.com/mcp`) and BigQuery MCP (`https://bigquery.googleapis.com/mcp`) |
| [`agent/run_demo.py`](agent/run_demo.py) | Part 3 | Runs the 9-question multi-turn walkthrough via ADK `InMemoryRunner` |
| [`evals/commerce_graph.evalset.json`](evals/commerce_graph.evalset.json) | Part 3 | Native ADK EvalSet covering the 9 core business questions (`Q1`–`Q9`) in isolated sessions |
| [`evals/heldout_traps.evalset.json`](evals/heldout_traps.evalset.json) | Part 3 | Native ADK EvalSet covering 8 held-out adversarial traps (`H1`–`H8`) phrased without matching DDL synonyms |
| [`evals/eval_config.json`](evals/eval_config.json) | Part 3 | Native ADK `EvalConfig` combining `tool_trajectory_avg_score` (`IN_ORDER`, `ignore_args: true`), `final_response_match_v2`, `hallucinations_v1`, and `semantic_graph_sql_governance` (`parallelism: 1`) |
| [`evals/sql_governance_metrics.py`](evals/sql_governance_metrics.py) | Part 3 | Custom ADK metric enforcing expected SQL/GQL dialect (`GRAPH_EXPAND`+`AGG` vs ISO GQL `MATCH` vs `no_sql`), blocking raw base tables, and verifying zero BigQuery MCP errors |

## Quickstart

### 1. Part 1: Create tables and the semantic graph in BigQuery

Run these SQL scripts in BigQuery Studio (or via `bq query --use_legacy_sql=false`) in your project:

```bash
bq query --use_legacy_sql=false < sql/01_seed_tables.sql
bq query --use_legacy_sql=false < sql/02_commerce_graph.sql
bq query --use_legacy_sql=false < sql/03_queries.sql
```

### 2. Publish Data Profiles and Data Insights to Knowledge Catalog

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"
export DATASCAN_LOCATION="us-central1"
./scripts/04_publish_catalog_metadata.sh
```

### 3. Set up the Python environment

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_PROJECT_NUMBER
gcloud auth application-default login --project="your-project-id"
```

### 4. Part 2: Managed Conversational Analytics data agent + ADK `DataAgentToolset`

```bash
python3 scripts/05_create_ca_agent.py
python3 scripts/06_query_ca_agent.py
python3 scripts/07_adk_data_agent_toolset.py
```

### 5. Part 3: Custom Google ADK + Managed MCP agent and native ADK evals

```bash
# Run the 9-question multi-turn walkthrough
python3 agent/run_demo.py

# Run native ADK evaluations (isolated sessions per case, k=3 runs)
PYTHONPATH=. adk eval agent \
  evals/commerce_graph.evalset.json \
  evals/heldout_traps.evalset.json \
  --config_file_path evals/eval_config.json \
  --num_runs 3 \
  --print_detailed_results

# Or launch the interactive ADK web UI (also opens the Eval tab for evals/*.evalset.json)
adk web .
```

## Resolved pitfalls and design notes

- **Edge `NO PROPERTIES` prevents duplicate `GRAPH_EXPAND` columns:** Edges backed by an existing node table (`demo.order_items AS LineOf`, `demo.orders AS PlacedBy`, `demo.support_tickets AS OpenedBy`) must specify `NO PROPERTIES` right after `DEFAULT LABEL OPTIONS (...)`; otherwise BigQuery defaults to `PROPERTIES ARE ALL COLUMNS` and duplicates every column under `LineOf_*` / `PlacedBy_*`.
- **`NOT ENFORCED` PKs/FKs let BigQuery Graph infer keys:** Declaring `PRIMARY KEY (...) NOT ENFORCED` and `FOREIGN KEY (...) REFERENCES ... NOT ENFORCED` on the base tables lets `CREATE PROPERTY GRAPH` infer node and edge keys automatically without repeating `KEY (...)` clauses.
- **Raw columns referenced by `MEASURE(...)` stay in `PROPERTIES(...)`:** GA property graph DDL requires any column referenced inside `MEASURE(...)` (such as `order_total` and `shipping_fee`) to remain listed in the node's `PROPERTIES(...)`.
- **String-literal verification in Conversational Analytics:** Adding a single generic rule to `SYSTEM_INSTRUCTION` (*"Before filtering on any string dimension, run a `SELECT DISTINCT` query on that column first"*) resolves singular/plural literal mismatches (such as `'Accessories'` vs `'Accessory'`) without hardcoding domain values.
- **Keep undefined ratios `NULL`:** Never `COALESCE` a ratio (`SAFE_DIVIDE`) to `0` when the denominator is `0` or absent; empty counts/sums are `0`, while `0 / 0` ratios stay `NULL`.
- **Use ADK `DataAgentToolset` (`ask_data_agent`) for persistent Conversational Analytics agents:** `google.adk.tools.data_agent.DataAgentToolset` calls persistent data agents directly by resource name without raw HTTP or BigQuery SDK boilerplate (and avoids A2A wire-format mismatches between ADK `RemoteA2aAgent` and `geminidataanalytics` `/v1/a2a`).
- **Knowledge Catalog `lookup_context` 1-hop chain:** Knowledge Catalog links `Graph <-> Graph Node <-> Base Table`. Passing the `bigquery-graph-node` entries to `lookup_context` traverses 1 hop in both directions in one zero-scan call, hydrating graph topology upward and base-table Data Profiles + Data Insights downward.
- **Sequential `parallelism: 1` for `adk eval`:** `evals/eval_config.json` sets `parallelism: 1` so `McpToolset` HTTP sessions open and close cleanly without async lifecycle races.
