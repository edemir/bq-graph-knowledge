# Benchmark Questions and Expected Queries

Below are all 20 benchmark questions (`B01` through `B10` for multi-grain business metrics, `T01` through `T10` for adversarial traps) and their canonical `CommerceGraph` queries.

## B01: Accessory sales and shipping (Enterprise)

**Question:** For Enterprise customers, how much did we sell in Accessories and what was the total shipping on those orders?

```sql
SELECT
  AGG(OrderItem_item_sales) AS accessory_sales,
  AGG(Orders_total_shipping) AS total_shipping
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'OrderItem')
WHERE Customer_segment = 'Enterprise'
  AND OrderItem_category = 'Accessory';
```

## B02: Return rate by segment

**Question:** What is our return rate by customer segment?

```sql
SELECT
  Customer_segment,
  AGG(Orders_refunded_revenue) AS refunded_revenue,
  AGG(Orders_gross_revenue) AS gross_revenue,
  AGG(Orders_refund_rate_pct) AS return_rate_pct
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
GROUP BY Customer_segment;
```

## B03: Paying customers by segment and Enterprise category

**Question:** How many paying customers do we have in each segment, and how many in each product category within Enterprise?

```sql
SELECT Customer_segment, AGG(Orders_completed_buyer_count) AS paying_customers
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
GROUP BY Customer_segment;

SELECT OrderItem_category, AGG(Orders_completed_buyer_count) AS paying_customers
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'OrderItem')
WHERE Customer_segment = 'Enterprise'
GROUP BY OrderItem_category;
```

## B04: Segment GMV and support workload

**Question:** By customer segment, show me GMV alongside total support tickets and total resolution hours.

```sql
WITH segments AS (
  SELECT DISTINCT Customer_segment AS segment
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Customer')
),
ord AS (
  SELECT Customer_segment AS segment, AGG(Orders_gross_revenue) AS gmv
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
  GROUP BY 1
),
tkt AS (
  SELECT
    Customer_segment AS segment,
    AGG(SupportTicket_ticket_count) AS tickets,
    AGG(SupportTicket_total_resolution_hours) AS resolution_hours
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'SupportTicket')
  GROUP BY 1
)
SELECT
  s.segment,
  COALESCE(o.gmv, 0) AS gmv,
  COALESCE(t.tickets, 0) AS tickets,
  COALESCE(t.resolution_hours, 0) AS resolution_hours
FROM segments s
LEFT JOIN ord o USING (segment)
LEFT JOIN tkt t USING (segment);
```

## B05: Enterprise support hours per order

**Question:** For Enterprise, what is the average support resolution hours per order?

```sql
WITH ord AS (
  SELECT AGG(Orders_order_count) AS order_count
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
  WHERE Customer_segment = 'Enterprise'
),
tkt AS (
  SELECT AGG(SupportTicket_total_resolution_hours) AS total_hours
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'SupportTicket')
  WHERE Customer_segment = 'Enterprise'
)
SELECT
  t.total_hours,
  o.order_count,
  SAFE_DIVIDE(t.total_hours, NULLIF(o.order_count, 0)) AS hours_per_order
FROM ord o
CROSS JOIN tkt t;
```

## B06: Refunded Enterprise customer and support tickets (ISO GQL)

**Question:** Which Enterprise customer had a refunded order over $4,000, and what support tickets did they open?

```sql
GRAPH commerce_bench.CommerceGraph
MATCH (o:Orders)-[:PlacedBy]->(c:Customer)<-[:OpenedBy]-(t:SupportTicket)
WHERE c.segment = 'Enterprise'
  AND o.status = 'refunded'
  AND o.order_total > 4000
RETURN
  c.customer_id,
  c.customer_name,
  o.order_id,
  o.order_total,
  t.ticket_id,
  t.topic,
  t.resolution_hours;
```

## B07: Enterprise orders over $3,000

**Question:** For Enterprise orders over $3,000, what was the total gross revenue and total shipping?

```sql
SELECT
  AGG(Orders_order_count) AS order_count,
  AGG(Orders_gross_revenue) AS gross_revenue,
  AGG(Orders_total_shipping) AS total_shipping
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
WHERE Customer_segment = 'Enterprise'
  AND Orders_order_total > 3000;
```

## B08: Segment share of total GMV

**Question:** What percentage share of total company GMV comes from each customer segment?

```sql
SELECT
  Customer_segment,
  AGG(Orders_gross_revenue) AS gmv,
  SAFE_DIVIDE(
    AGG(Orders_gross_revenue),
    SUM(AGG(Orders_gross_revenue)) OVER ()
  ) * 100.0 AS gmv_share_pct
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
GROUP BY Customer_segment;
```

## B09: Hardware order and paying buyer counts

**Question:** How many distinct orders included at least one Hardware item, and how many paying customers bought Hardware?

```sql
SELECT
  AGG(Orders_order_count) AS hardware_orders,
  AGG(Orders_completed_buyer_count) AS hardware_paying_customers
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'OrderItem')
WHERE OrderItem_category = 'Hardware';
```

## B10: Full segment scorecard

**Question:** For each customer segment, compare total GMV, return rate, paying customers, Hardware sales, shipping on orders that included Accessories, and support resolution hours per dollar of GMV, without dropping customers who have not ordered yet.

```sql
WITH segments AS (
  SELECT DISTINCT Customer_segment AS segment
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Customer')
),
ord AS (
  SELECT
    Customer_segment AS segment,
    AGG(Orders_gross_revenue) AS gmv,
    AGG(Orders_refund_rate_pct) AS return_rate_pct,
    AGG(Orders_completed_buyer_count) AS paying_customers
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
  GROUP BY 1
),
hw AS (
  SELECT Customer_segment AS segment, AGG(OrderItem_item_sales) AS hardware_sales
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'OrderItem')
  WHERE OrderItem_category = 'Hardware'
  GROUP BY 1
),
acc AS (
  SELECT Customer_segment AS segment, AGG(Orders_total_shipping) AS accessory_shipping
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'OrderItem')
  WHERE OrderItem_category = 'Accessory'
  GROUP BY 1
),
tkt AS (
  SELECT Customer_segment AS segment, AGG(SupportTicket_total_resolution_hours) AS res_hours
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'SupportTicket')
  GROUP BY 1
)
SELECT
  s.segment,
  COALESCE(o.gmv, 0) AS gmv,
  o.return_rate_pct,
  COALESCE(o.paying_customers, 0) AS paying_customers,
  COALESCE(h.hardware_sales, 0) AS hardware_sales,
  COALESCE(a.accessory_shipping, 0) AS accessory_shipping,
  SAFE_DIVIDE(COALESCE(t.res_hours, 0), NULLIF(COALESCE(o.gmv, 0), 0)) AS support_hours_per_gmv
FROM segments s
LEFT JOIN ord o USING (segment)
LEFT JOIN hw h USING (segment)
LEFT JOIN acc a USING (segment)
LEFT JOIN tkt t USING (segment);
```

## T01: Hardware delivery charges fanout trap

**Question:** Total delivery charges on orders containing at least one Hardware item, by segment?

```sql
SELECT
  Customer_segment,
  AGG(Orders_total_shipping) AS delivery_charges
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'OrderItem')
WHERE OrderItem_category = 'Hardware'
GROUP BY Customer_segment;
```

## T02: Hardware refund share fanout trap

**Question:** For orders that included Hardware, what was the total gross order value, the refunded order value, and the dollar refund rate percentage?

```sql
SELECT
  AGG(Orders_gross_revenue) AS gross_order_value,
  AGG(Orders_refunded_revenue) AS refunded_order_value,
  AGG(Orders_refund_rate_pct) AS refund_rate_pct
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'OrderItem')
WHERE OrderItem_category = 'Hardware';
```

## T03: Zero-order customers and their support tickets

**Question:** How many customers have never placed an order, and how many of those zero-order customers opened a support ticket (and who are they)?

```sql
WITH customers AS (
  SELECT DISTINCT Customer_customer_id AS customer_id, Customer_customer_name AS customer_name
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Customer')
),
ord AS (
  SELECT Customer_customer_id AS customer_id, AGG(Orders_order_count) AS order_count
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
  GROUP BY 1
),
tkt AS (
  SELECT
    Customer_customer_id AS customer_id,
    AGG(SupportTicket_ticket_count) AS ticket_count,
    AGG(SupportTicket_total_resolution_hours) AS resolution_hours
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'SupportTicket')
  GROUP BY 1
)
SELECT
  COUNT(*) OVER () AS zero_order_customers,
  COUNTIF(COALESCE(t.ticket_count, 0) > 0) OVER () AS zero_order_with_tickets,
  c.customer_id,
  c.customer_name,
  COALESCE(t.ticket_count, 0) AS ticket_count,
  COALESCE(t.resolution_hours, 0) AS resolution_hours
FROM customers c
LEFT JOIN ord o USING (customer_id)
LEFT JOIN tkt t USING (customer_id)
WHERE COALESCE(o.order_count, 0) = 0
ORDER BY ticket_count DESC, c.customer_id;
```

## T04: Month-over-month GMV abstention

**Question:** How did GMV trend month over month?

Expected behavior: Zero SQL calls. Abstain because no date, timestamp, or month columns exist in `CommerceGraph`.

## T05: Partial-scope revenue vs missing costs

**Question:** Show gross revenue, net revenue after refunds, and net profit after warehouse rent and payment-processing fees by segment.

```sql
SELECT
  Customer_segment,
  AGG(Orders_gross_revenue) AS gross_revenue,
  AGG(Orders_refunded_revenue) AS refunded_revenue,
  AGG(Orders_gross_revenue) - AGG(Orders_refunded_revenue) AS net_revenue_after_refunds
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
GROUP BY Customer_segment;
```

Abstain on net profit after warehouse rent and payment-processing fees because those cost fields do not exist in `CommerceGraph`.

## T06: Support hours per dollar with zero denominator

**Question:** Compare customers Cust-0001, Cust-0005, and Cust-0035 by support resolution hours per dollar of gross order value.

```sql
WITH target AS (
  SELECT DISTINCT Customer_customer_id AS customer_id, Customer_customer_name AS customer_name
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Customer')
  WHERE Customer_customer_id IN ('Cust-0001', 'Cust-0005', 'Cust-0035')
),
ord AS (
  SELECT Customer_customer_id AS customer_id, AGG(Orders_gross_revenue) AS gmv
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
  WHERE Customer_customer_id IN ('Cust-0001', 'Cust-0005', 'Cust-0035')
  GROUP BY 1
),
tkt AS (
  SELECT Customer_customer_id AS customer_id, AGG(SupportTicket_total_resolution_hours) AS hours
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'SupportTicket')
  WHERE Customer_customer_id IN ('Cust-0001', 'Cust-0005', 'Cust-0035')
  GROUP BY 1
)
SELECT
  t.customer_id,
  t.customer_name,
  COALESCE(k.hours, 0) AS resolution_hours,
  COALESCE(o.gmv, 0) AS gmv,
  SAFE_DIVIDE(COALESCE(k.hours, 0), NULLIF(COALESCE(o.gmv, 0), 0)) AS hours_per_dollar
FROM target t
LEFT JOIN ord o USING (customer_id)
LEFT JOIN tkt k USING (customer_id);
```

## T07: Enterprise Warranty zero sum and NULL ratio

**Question:** How much Warranty did enterprise accounts purchase, and what was the refund rate on those Enterprise Warranty orders?

```sql
SELECT
  COALESCE(AGG(OrderItem_item_sales), 0) AS warranty_sales,
  AGG(Orders_refund_rate_pct) AS refund_rate_pct
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'OrderItem')
WHERE Customer_segment = 'Enterprise'
  AND OrderItem_category = 'Warranty';
```

## T08: Order value of customers who contacted support

**Question:** For customers who contacted support, what is the total gross value of their orders?

```sql
WITH support_customers AS (
  SELECT DISTINCT Customer_customer_id AS customer_id
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'SupportTicket')
)
SELECT AGG(Orders_gross_revenue) AS total_gross_order_value
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
WHERE Customer_customer_id IN (SELECT customer_id FROM support_customers);
```

## T09: Order value of customers with shipping tickets

**Question:** What is the total gross order value of customers who opened a shipping support ticket?

```sql
WITH shipping_ticket_customers AS (
  SELECT DISTINCT Customer_customer_id AS customer_id
  FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'SupportTicket')
  WHERE SupportTicket_topic = 'shipping'
)
SELECT
  COUNT(DISTINCT Customer_customer_id) AS customer_count,
  AGG(Orders_gross_revenue) AS total_gross_order_value
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'Orders')
WHERE Customer_customer_id IN (SELECT customer_id FROM shipping_ticket_customers);
```

## T10: Refunded order entity details over $4,000

**Question:** List each refunded order over $4,000, including the order ID, customer name, distinct item categories inside that order, and the order's total dollar value.

```sql
SELECT
  Orders_order_id,
  Customer_customer_name,
  STRING_AGG(DISTINCT OrderItem_category, ', ' ORDER BY OrderItem_category) AS categories,
  AGG(Orders_gross_revenue) AS order_total
FROM GRAPH_EXPAND('commerce_bench.CommerceGraph', start_node => 'OrderItem')
WHERE Orders_status = 'refunded'
  AND Orders_order_total > 4000
GROUP BY Orders_order_id, Customer_customer_name;
```
