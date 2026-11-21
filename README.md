# BigQuery Semantic Graph + Knowledge Catalog ADK Agent

Companion code for the two-part blog series on building a warehouse-native semantic layer with **BigQuery Graph**, **BigQuery Measures**, **Knowledge Catalog** (Dataplex Data Profiles + Data Insights), and a **Google ADK** analytics agent backed by Google Cloud's managed MCP servers.

## Repository layout

| Path | Description |
| :--- | :--- |
| [`sql/01_seed_tables.sql`](sql/01_seed_tables.sql) | Creates `demo.customers`, `demo.orders`, `demo.order_items`, and `demo.support_tickets` (14 rows total) |
| [`sql/02_commerce_graph.sql`](sql/02_commerce_graph.sql) | Defines `demo.CommerceGraph` (`CREATE OR REPLACE PROPERTY GRAPH`) with grain-locked measures, derived ratios, synonyms, and `NO PROPERTIES` edges |
| [`sql/03_queries.sql`](sql/03_queries.sql) | Part 1 verification queries: `GRAPH_EXPAND` with child filters, multi-fact `FULL OUTER JOIN`, and ISO GQL `MATCH` root-cause traversal |
| [`scripts/04_publish_catalog_metadata.sh`](scripts/04_publish_catalog_metadata.sh) | Enables required APIs and runs Dataplex `data-profile` and `data-documentation` scans with `--enable-catalog-publishing` |
| [`agent/agent.py`](agent/agent.py) | Google ADK `root_agent` using `gemini-4-hydrogen` and `McpToolset` connected to Knowledge Catalog MCP (`https://dataplex.googleapis.com/mcp`) and BigQuery MCP (`https://bigquery.googleapis.com/mcp`) |
| [`agent/run_demo.py`](agent/run_demo.py) | Runs the 9-question multi-turn walkthrough via ADK `InMemoryRunner` |

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

### 3. Run the Google ADK agent

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

gcloud auth application-default login --project="$GOOGLE_CLOUD_PROJECT"

export GOOGLE_GENAI_USE_VERTEXAI=TRUE
export GOOGLE_CLOUD_LOCATION=global
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_PROJECT_NUMBER="$(gcloud projects describe "$GOOGLE_CLOUD_PROJECT" --format='value(projectNumber)')"

# Run the 9-question walkthrough
python3 agent/run_demo.py

# Or launch the interactive ADK web UI
adk web .
```
