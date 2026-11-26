-- Deterministic ~2,800-row scaled commerce benchmark (commerce_bench)
-- Preserves the exact 4-table relational schema from Part 1 while making
-- SELECT * context-window eyeballing impossible and exposing real join fan-out.

CREATE SCHEMA IF NOT EXISTS commerce_bench OPTIONS (location = 'US');

-- 1. Customers: 120 accounts across Enterprise (40) and SMB (80)
--    Includes ~18 zero-order accounts (Cust-0035..Cust-0040 in Enterprise, Cust-0109..Cust-0120 in SMB)
CREATE OR REPLACE TABLE commerce_bench.customers (
  customer_id STRING NOT NULL,
  customer_name STRING,
  segment STRING,
  PRIMARY KEY (customer_id) NOT ENFORCED
);

INSERT INTO commerce_bench.customers (customer_id, customer_name, segment)
SELECT
  FORMAT('Cust-%04d', idx) AS customer_id,
  CONCAT(
    ['Apex', 'Beacon', 'Cobalt', 'Delta', 'Echo', 'Forge', 'Glacier', 'Harbor', 'Ionic', 'Jade', 'Kestrel', 'Lumen'][OFFSET(MOD(idx - 1, 12))],
    '-',
    CAST(idx AS STRING)
  ) AS customer_name,
  IF(idx <= 40, 'Enterprise', 'SMB') AS segment
FROM UNNEST(GENERATE_ARRAY(1, 120)) AS idx;

-- 2. Orders: 640 orders across active customers (Cust-0001..0034 in Enterprise, Cust-0041..0108 in SMB)
--    Cust-0033 and Cust-0034 have ONLY refunded orders (testing completed_buyer_count vs raw customer count).
--    Only ONE Enterprise order (Ord-0017 for Cust-0005 / Echo-5, $4,800.00) is a refunded order over $4,000.
CREATE OR REPLACE TABLE commerce_bench.orders (
  order_id STRING NOT NULL,
  customer_id STRING,
  order_total FLOAT64,
  shipping_fee FLOAT64,
  status STRING,
  PRIMARY KEY (order_id) NOT ENFORCED,
  FOREIGN KEY (customer_id) REFERENCES commerce_bench.customers(customer_id) NOT ENFORCED
);

INSERT INTO commerce_bench.orders (order_id, customer_id, order_total, shipping_fee, status)
WITH raw_orders AS (
  SELECT
    ord_num,
    FORMAT('Ord-%04d', ord_num) AS order_id,
    CASE
      WHEN ord_num = 17 THEN 'Cust-0005'
      WHEN ord_num IN (245, 246) THEN 'Cust-0033'
      WHEN ord_num = 247 THEN 'Cust-0034'
      WHEN ord_num <= 250 THEN FORMAT('Cust-%04d', 1 + MOD(ABS(FARM_FINGERPRINT(CONCAT('ent_c_', CAST(ord_num AS STRING)))), 32))
      ELSE FORMAT('Cust-%04d', 41 + MOD(ABS(FARM_FINGERPRINT(CONCAT('smb_c_', CAST(ord_num AS STRING)))), 68))
    END AS customer_id,
    ord_num <= 250 AS is_ent,
    MOD(ABS(FARM_FINGERPRINT(CONCAT('amt_', CAST(ord_num AS STRING)))), 100) AS amt_roll,
    MOD(ABS(FARM_FINGERPRINT(CONCAT('ref_', CAST(ord_num AS STRING)))), 100) AS ref_roll
  FROM UNNEST(GENERATE_ARRAY(1, 640)) AS ord_num
)
SELECT
  order_id,
  customer_id,
  CASE
    WHEN ord_num = 17 THEN 4800.0
    WHEN is_ent THEN ROUND(300.0 + amt_roll * 32.0, 2)       -- $300 to $3,468
    ELSE ROUND(60.0 + amt_roll * 8.0, 2)                     -- $60 to $852
  END AS order_total,
  CASE
    WHEN ord_num = 17 THEN 95.0
    WHEN is_ent THEN ROUND(20.0 + MOD(amt_roll, 6) * 10.0, 2)
    ELSE ROUND(10.0 + MOD(amt_roll, 4) * 5.0, 2)
  END AS shipping_fee,
  CASE
    WHEN ord_num IN (17, 245, 246, 247) THEN 'refunded'
    -- Higher refund frequency on small orders so unweighted order-count refund % != dollar-weighted refund %
    WHEN is_ent AND amt_roll < 25 AND ref_roll < 28 THEN 'refunded'
    WHEN is_ent AND amt_roll >= 25 AND ref_roll < 7 THEN 'refunded'
    WHEN (NOT is_ent) AND amt_roll < 30 AND ref_roll < 22 THEN 'refunded'
    WHEN (NOT is_ent) AND amt_roll >= 30 AND ref_roll < 6 THEN 'refunded'
    ELSE 'completed'
  END AS status
FROM raw_orders;

-- 3. Order items: ~1,850 line items (2 to 4 items on most orders -> real N:1 fan-out!)
--    Categories: 'Hardware', 'Software', 'Accessory', 'Warranty'
--    Note: Enterprise accounts buy ZERO 'Warranty' items ($0.00 sales, NULL refund_rate_pct on that slice).
CREATE OR REPLACE TABLE commerce_bench.order_items (
  item_id STRING NOT NULL,
  order_id STRING,
  category STRING,
  unit_price FLOAT64,
  qty INT64,
  PRIMARY KEY (item_id) NOT ENFORCED,
  FOREIGN KEY (order_id) REFERENCES commerce_bench.orders(order_id) NOT ENFORCED
);

INSERT INTO commerce_bench.order_items (item_id, order_id, category, unit_price, qty)
WITH order_item_counts AS (
  SELECT
    o.order_id,
    o.customer_id,
    o.order_total,
    c.segment,
    CASE
      WHEN o.order_id = 'Ord-0017' THEN 3
      ELSE 2 + MOD(ABS(FARM_FINGERPRINT(CONCAT('icnt_', o.order_id))), 3)  -- 2, 3, or 4 items per order
    END AS item_cnt
  FROM commerce_bench.orders o
  JOIN commerce_bench.customers c USING (customer_id)
),
expanded AS (
  SELECT
    o.order_id,
    o.segment,
    o.order_total,
    o.item_cnt,
    slot,
    ROW_NUMBER() OVER (ORDER BY o.order_id, slot) AS global_seq,
    MOD(ABS(FARM_FINGERPRINT(CONCAT('cat_', o.order_id, '_', CAST(slot AS STRING)))), 100) AS cat_roll,
    1 + MOD(ABS(FARM_FINGERPRINT(CONCAT('qty_', o.order_id, '_', CAST(slot AS STRING)))), 3) AS qty_val
  FROM order_item_counts o,
  UNNEST(GENERATE_ARRAY(1, o.item_cnt)) AS slot
)
SELECT
  FORMAT('Item-%05d', global_seq) AS item_id,
  order_id,
  CASE
    WHEN order_id = 'Ord-0017' AND slot IN (1, 2) THEN 'Hardware'
    WHEN order_id = 'Ord-0017' AND slot = 3 THEN 'Accessory'
    WHEN segment = 'Enterprise' THEN
      CASE
        WHEN cat_roll < 50 THEN 'Hardware'
        WHEN cat_roll < 80 THEN 'Software'
        ELSE 'Accessory'
      END
    ELSE
      CASE
        WHEN cat_roll < 35 THEN 'Hardware'
        WHEN cat_roll < 65 THEN 'Software'
        WHEN cat_roll < 85 THEN 'Accessory'
        ELSE 'Warranty'
      END
  END AS category,
  -- Partition order_total cleanly across the slots so SUM(unit_price * qty) aligns with order_total
  ROUND(
    (order_total * (CASE
      WHEN item_cnt = 2 THEN [0.6, 0.4][OFFSET(slot - 1)]
      WHEN item_cnt = 3 THEN [0.5, 0.3, 0.2][OFFSET(slot - 1)]
      ELSE [0.4, 0.3, 0.2, 0.1][OFFSET(slot - 1)]
    END)) / qty_val,
    2
  ) AS unit_price,
  qty_val AS qty
FROM expanded;

-- 4. Support tickets: ~340 rows across active AND zero-order customers
--    Includes tickets for zero-order Enterprise customers (Cust-0035..Cust-0038)
--    and explicit tickets for Cust-0005 (Echo-5) to test multi-hop GQL traversal.
CREATE OR REPLACE TABLE commerce_bench.support_tickets (
  ticket_id STRING NOT NULL,
  customer_id STRING,
  topic STRING,
  resolution_hours INT64,
  PRIMARY KEY (ticket_id) NOT ENFORCED,
  FOREIGN KEY (customer_id) REFERENCES commerce_bench.customers(customer_id) NOT ENFORCED
);

INSERT INTO commerce_bench.support_tickets (ticket_id, customer_id, topic, resolution_hours)
WITH seeded_tickets AS (
  -- Explicit tickets for Cust-0005 (who owns Ord-0017, the >$4,000 refunded Enterprise order)
  SELECT 1 AS seq, 'Cust-0005' AS customer_id, 'billing' AS topic, 6 AS resolution_hours
  UNION ALL SELECT 2, 'Cust-0005', 'shipping', 14
  -- Explicit tickets for zero-order Enterprise customers (Cust-0035, Cust-0036, Cust-0037)
  UNION ALL SELECT 3, 'Cust-0035', 'onboarding', 5
  UNION ALL SELECT 4, 'Cust-0035', 'security', 9
  UNION ALL SELECT 5, 'Cust-0036', 'onboarding', 4
  UNION ALL SELECT 6, 'Cust-0037', 'onboarding', 3
  -- Deterministic bulk tickets across remaining Enterprise & SMB customers (excluding Cust-0005 and Cust-0035..0040 so zero-order count stays exact)
  UNION ALL
  SELECT
    6 + idx AS seq,
    CASE
      WHEN idx <= 190 THEN
        FORMAT('Cust-%04d',
          CASE
            WHEN 1 + MOD(ABS(FARM_FINGERPRINT(CONCAT('tk_ent_', CAST(idx AS STRING)))), 33) = 5 THEN 6
            ELSE 1 + MOD(ABS(FARM_FINGERPRINT(CONCAT('tk_ent_', CAST(idx AS STRING)))), 33)
          END
        )
      ELSE
        FORMAT('Cust-%04d', 41 + MOD(ABS(FARM_FINGERPRINT(CONCAT('tk_smb_', CAST(idx AS STRING)))), 60))
    END AS customer_id,
    ['billing', 'shipping', 'onboarding', 'security'][OFFSET(MOD(ABS(FARM_FINGERPRINT(CONCAT('top_', CAST(idx AS STRING)))), 4))] AS topic,
    2 + MOD(ABS(FARM_FINGERPRINT(CONCAT('hrs_', CAST(idx AS STRING)))), 11) AS resolution_hours
  FROM UNNEST(GENERATE_ARRAY(1, 334)) AS idx
)
SELECT
  FORMAT('Tkt-%04d', seq) AS ticket_id,
  customer_id,
  topic,
  resolution_hours
FROM seeded_tickets;
