---
name: bigquery-semantic-graph
metadata:
  version: "0.9.5"
  category: BigDataAndAnalytics
  adk_additional_tools:
    - execute_sql
description: >-
  Queries BigQuery Property Graphs and governed MEASURE definitions using
  GRAPH_EXPAND, AGG(), and ISO GQL MATCH from Knowledge Catalog graph context.
  ALWAYS load FIRST (before execute_sql or execute_sql_readonly) on EVERY
  question when a BigQuery Property Graph or graphSchema is present.
---

# BigQuery Semantic Graph

## 1. Context Grounding

- Read node labels, directed edges (`graphSchema.edges`), `DIMENSION` properties, and `MEASURE` `synonyms`/`description` from the `BigQuery Graph Node` entries and `graphSchema` in context, using `BigQuery Table` entries in `relatedResources` solely for column descriptions and `sampleValues`.
- When a Property Graph exists in context, **never** query `<dataset_id>.<table>` (including `BigQuery Table` URIs in `relatedResources`), views, or `INFORMATION_SCHEMA`.

## 2. Routing

- **`GRAPH_EXPAND` + `AGG()`:** All counts, sums, averages, shares, rates, `MEASURE`s, and zero-activity (`0`-count) checks (even when also listing entity names). Never use `GRAPH_TABLE(...)` or `OPTIONAL MATCH`.
- **ISO GQL `MATCH`:** Listing connected `DIMENSION` records only, with no counts, aggregations, `MEASURE`s, or zero-activity filters. Never use `GRAPH_TABLE(...)`.

## 3. `GRAPH_EXPAND` Rules

1. Single-quote `'project.dataset.Graph'` (no `TABLE` or backticks) and set `start_node => '<FinestNode>'`. Expanding a child node (`'Child'`) flattens all `N:1` ancestors (`Child_*`, `Parent_*`, `Entity_*`) and automatically deduplicates ancestor `AGG()` measures (including distinct-count measures like `AGG(Parent_cnt)`) per parent key, even when grouping by `Child_dim`; do not split `Child` and `Parent` into separate `GRAPH_EXPAND` CTEs along a single `N:1` chain:

```sql
SELECT Entity_dim, AGG(Child_m1) AS m1, AGG(Parent_m2) AS m2, AGG(Parent_cnt) AS cnt,
  SAFE_DIVIDE(AGG(Parent_m2), SUM(AGG(Parent_m2)) OVER ()) AS share
FROM GRAPH_EXPAND('project.dataset.Graph', start_node => 'Child')
WHERE Child_attr = 'val'
GROUP BY Entity_dim;
```

2. Prefix every column `<NodeLabel>_<prop>`. Never run `SELECT * FROM GRAPH_EXPAND(...)`, even with `LIMIT` (`*` includes `MEASURE` columns and fails at compile time with HTTP 400); read exact filter strings from `sampleValues` in `relatedResources`, or query explicit `DIMENSION` columns (`SELECT DISTINCT Node_dim FROM GRAPH_EXPAND(...)`) if you need to inspect values.
3. Always call governed `AGG(<NodeLabel>_<measure>)` directly inside `GRAPH_EXPAND` whenever a matching `MEASURE` exists (matching `synonyms` and `description` in the graph context, including ancestor measures like `AGG(Parent_cnt)` when expanding `'Child'` and grouping by `Child_dim`—never substitute raw `COUNT(DISTINCT ...)` or `CASE WHEN` for a governed measure); only use `COUNT(<NodeLabel>_<id>)` inside `GRAPH_EXPAND` for a node that defines no count `MEASURE`. Filter `MEASURE`s via `WHERE` (using separate CTEs for distinct filter slices; never use `CASE WHEN`, `AGG(... WHERE ...)`, `SUM`/`COUNT`/`AVG` on a `MEASURE`, raw formulas from the graph context, or unaggregated `MEASURE`s outside a CTE).
4. Trust `GRAPH_EXPAND` and `AGG()` deduplication: once a governed `GRAPH_EXPAND` query returns the requested columns, answer directly without running follow-up sanity-check or manual-deduplication queries.
5. Use `COALESCE(AGG(...), 0)` for empty sums/counts and `NULLIF(denom, 0)` so `0/0` ratios stay `NULL`.
6. For sibling `1:N` branches (`BranchA -> Entity <- BranchB`), distinct filtered slices, or zero-activity anti-joins (`COALESCE(cnt, 0) = 0`), aggregate each branch at the output grain in `WITH` CTEs anchored on the shared entity node:

```sql
WITH d AS (
  SELECT DISTINCT Entity_dim FROM GRAPH_EXPAND('project.dataset.Graph', start_node => 'Entity')
),
a AS (
  SELECT Entity_dim, AGG(BranchA_m1) AS m1, AGG(Parent_m2) AS m2
  FROM GRAPH_EXPAND('project.dataset.Graph', start_node => 'BranchA')
  WHERE BranchA_attr = 'val'
  GROUP BY Entity_dim
),
b AS (
  SELECT Entity_dim, AGG(BranchB_cnt) AS cnt, AGG(BranchB_m3) AS m3
  FROM GRAPH_EXPAND('project.dataset.Graph', start_node => 'BranchB')
  GROUP BY Entity_dim
)
SELECT d.Entity_dim, COALESCE(a.m1, 0) AS m1, COALESCE(b.cnt, 0) AS cnt,
  SAFE_DIVIDE(COALESCE(b.m3, 0), NULLIF(a.m1, 0)) AS ratio
FROM d LEFT JOIN a USING (Entity_dim) LEFT JOIN b USING (Entity_dim);
```

## 4. ISO GQL `MATCH`

Pass standalone `GRAPH` directly as the top-level statement (never wrap in `SELECT ... FROM GRAPH_TABLE(...)` and use `RETURN [DISTINCT]`, never `RETURNING`). Match exact node labels and directed edges (`source -> destination`) from `graphSchema.edges` using only `DIMENSION` properties:

```sql
GRAPH `project.dataset.Graph`
MATCH (a:BranchA)-[:EdgeA]->(e:Entity)<-[:EdgeB]-(b:BranchB)
WHERE e.dim = 'val' AND a.flag = 'x' AND a.num > 100
RETURN e.id, e.name, a.id AS branch_a_id, b.id AS branch_b_id;
```

## 5. Abstention

- **Missing required dimension or time axis (dates/months):** Run **`0` SQL queries** and state `<dataset_id>` lacks that column.
- **Mixed grounded + missing metrics:** Query `<dataset_id>`'s graph once for grounded metrics and name the missing fields.
