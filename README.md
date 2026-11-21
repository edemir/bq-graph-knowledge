# BigQuery Semantic Graph + Knowledge Catalog ADK Agent

Companion code for the two-part blog series on building a warehouse-native semantic layer with **BigQuery Graph**, **BigQuery Measures**, **Knowledge Catalog** (Dataplex Data Profiles + Data Insights), and a **Google ADK** analytics agent backed by Google Cloud's managed MCP servers.

## Repository layout

| Path | Description |
| :--- | :--- |
| [`sql/01_seed_tables.sql`](sql/01_seed_tables.sql) | Creates `demo.customers`, `demo.orders`, `demo.order_items`, and `demo.support_tickets` (14 rows total) |
| [`sql/02_commerce_graph.sql`](sql/02_commerce_graph.sql) | Defines `demo.CommerceGraph` (`CREATE OR REPLACE PROPERTY GRAPH`) with grain-locked measures, derived ratios, synonyms, and `NO PROPERTIES` edges |
| [`sql/03_queries.sql`](sql/03_queries.sql) | Part 1 verification queries: `GRAPH_EXPAND` with child filters, multi-fact `FULL OUTER JOIN`, and ISO GQL `MATCH` root-cause traversal |
| [`scripts/04_publish_catalog_metadata.sh`](scripts/04_publish_catalog_metadata.sh) | Enables required APIs and runs Dataplex `data-profile` and `data-documentation` scans with `--enable-catalog-publishing` |
| [`agent/agent.py`](agent/agent.py) | Google ADK `root_agent` using `gemini-4-hydrogen` and `McpToolset` with dynamic OAuth `header_provider` connected to Knowledge Catalog MCP (`https://dataplex.googleapis.com/mcp`) and BigQuery MCP (`https://bigquery.googleapis.com/mcp`) |
| [`agent/run_demo.py`](agent/run_demo.py) | Runs the 9-question multi-turn walkthrough via ADK `InMemoryRunner` |
| [`agent/eval.py`](agent/eval.py) | Isolated-session programmatic eval harness (`Q1`–`Q9` + 8 held-out adversarial traps `H1`–`H8`) with cold-start discovery, SQL governance, and ground-truth assertions |

## Quickstart

### 1. Part 1: Create tables and the semantic graph in BigQuery

Run these SQL scripts in BigQuery Studio (or via `bq query --use_legacy_sql=false`) in your project:

```bash
bq query --use_legacy_sql=false < sql/01_seed_tables.sql
bq query --use_legacy_sql=false < sql/02_commerce_graph.sql
bq query --use_legacy_sql=false < sql/03_queries.sql
```

### 2. Part 2: Publish Data Profiles and Data Insights to Knowledge Catalog

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"
export DATASCAN_LOCATION="us-central1"
./scripts/04_publish_catalog_metadata.sh
```

### 3. Run the Google ADK agent and evals

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with your GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_PROJECT_NUMBER
gcloud auth application-default login --project="your-project-id"

# Run the 9-question multi-turn walkthrough
python3 agent/run_demo.py

# Run isolated cold-start programmatic evals (Q1–Q9 + H1–H8, k=3 passes)
python3 agent/eval.py --suite all --runs 3

# Or launch the interactive ADK web UI
adk web .
```
