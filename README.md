# BigQuery Semantic Graph + Knowledge Catalog + ADK 2

Companion code for the blog series on building a warehouse-native semantic layer with **BigQuery Graph**, **BigQuery Measures**, **Knowledge Catalog**, and a **Google ADK 2** analytics agent grounded by a portable `SkillToolset` skill.

## Repository layout

| Path | Blog part | Description |
| :--- | :---: | :--- |
| [`sql/01_seed_tables.sql`](sql/01_seed_tables.sql) | Part 1 | Creates the 14-row `demo` tables (`customers`, `orders`, `order_items`, `support_tickets`) with `NOT ENFORCED` primary and foreign keys |
| [`sql/02_commerce_graph.sql`](sql/02_commerce_graph.sql) | Part 1 | Defines `demo.CommerceGraph` (`CREATE OR REPLACE PROPERTY GRAPH`) with `DEFAULT LABEL OPTIONS`, `NO PROPERTIES` on edges, grain-locked measures, and business synonyms |
| [`sql/03_queries.sql`](sql/03_queries.sql) | Part 1 | Part 1 verification queries: `GRAPH_EXPAND` with child filters, multi-fact `FULL OUTER JOIN`, ISO GQL `MATCH` traversal, and `AGG()` with outer windows + `HAVING` |
| [`part2_skill/sql/01_seed_commerce_bench.sql`](part2_skill/sql/01_seed_commerce_bench.sql) | Part 2 | Creates the 3,018-row `commerce_bench` dataset (120 customers including 18 zero-order accounts, 640 orders, 1,918 order items, 340 support tickets) |
| [`part2_skill/sql/02_commerce_bench_graph.sql`](part2_skill/sql/02_commerce_bench_graph.sql) | Part 2 | Defines `commerce_bench.CommerceGraph` over the scaled benchmark tables |
| [`part2_skill/skills/bigquery-semantic-graph/SKILL.md`](part2_skill/skills/bigquery-semantic-graph/SKILL.md) | Part 2 | 79-line portable skill using symbolic SQL templates (`Entity`, `Parent`, `Child`, `BranchA`, `BranchB`) and `adk_additional_tools: [execute_sql]` |
| [`part2_skill/agent_under_test/agent.py`](part2_skill/agent_under_test/agent.py) | Part 2 | ADK 2 `App` with async Knowledge Catalog hydration (`searchEntries` + `lookupContext`), TTL cache, `SkillToolset`, and read-only `BigQueryToolset` |
| [`part2_skill/deploy_agent_engine.sh`](part2_skill/deploy_agent_engine.sh) | Part 2 | Idempotent deployment script for Agent Runtime on Gemini Enterprise Agent Platform with least-privilege IAM and OpenTelemetry |
| [`part2_skill/BENCHMARK_QUERIES.md`](part2_skill/BENCHMARK_QUERIES.md) | Part 2 | All 20 business and adversarial benchmark questions (`B01`–`B10`, `T01`–`T10`) and their canonical `CommerceGraph` queries |

## Quickstart

### Part 1: 14-row `demo` dataset and graph

```bash
bq query --use_legacy_sql=false < sql/01_seed_tables.sql
bq query --use_legacy_sql=false < sql/02_commerce_graph.sql
bq query --use_legacy_sql=false < sql/03_queries.sql
```

### Part 2: Scaled `commerce_bench` + ADK 2 agent

1. Seed `commerce_bench` and create `commerce_bench.CommerceGraph`:

```bash
bq query --use_legacy_sql=false < part2_skill/sql/01_seed_commerce_bench.sql
bq query --use_legacy_sql=false < part2_skill/sql/02_commerce_bench_graph.sql
```

2. Configure Python and environment variables:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r part2_skill/agent_under_test/requirements.txt

cp part2_skill/.env.example part2_skill/agent_under_test/.env
# Edit part2_skill/agent_under_test/.env with your GOOGLE_CLOUD_PROJECT
gcloud auth application-default login --project="your-project-id"
```

3. Run locally with ADK or deploy to Agent Runtime:

```bash
# Local ADK web UI
adk web part2_skill

# Or deploy to Agent Runtime on Gemini Enterprise Agent Platform
export GOOGLE_CLOUD_PROJECT="your-project-id"
export AGENT_ENGINE_REGION="us-central1"
export BQ_LOCATION="us"
export BQ_DATASET="commerce_bench"
./part2_skill/deploy_agent_engine.sh
```
