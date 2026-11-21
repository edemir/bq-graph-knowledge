-- 1. Child-filtered order-level measures (fan-out-safe shipping & weighted ratio)
SELECT
  Customer_segment,
  AGG(OrderItem_item_sales) AS item_sales,
  AGG(Orders_gross_revenue) AS basket_value,
  AGG(Orders_total_shipping) AS order_shipping,
  AGG(Orders_refund_rate_pct) AS refund_rate_pct
FROM GRAPH_EXPAND('demo.CommerceGraph', start_node => 'OrderItem')
WHERE OrderItem_category = 'Accessory'
GROUP BY Customer_segment;

-- 2. Multi-fact rollup across Orders and SupportTicket (preserving zero-order customers)
SELECT
  COALESCE(EO.Customer_segment, ET.Customer_segment) AS segment,
  AGG(EO.Orders_gross_revenue) AS gross_revenue,
  AGG(EO.Orders_refund_rate_pct) AS refund_rate_pct,
  AGG(EO.Orders_completed_buyer_count) AS completed_buyers,
  AGG(ET.SupportTicket_ticket_count) AS ticket_count,
  AGG(ET.SupportTicket_total_resolution_hours) AS resolution_hours
FROM GRAPH_EXPAND('demo.CommerceGraph', start_node => 'Orders') AS EO
FULL OUTER JOIN GRAPH_EXPAND('demo.CommerceGraph', start_node => 'SupportTicket') AS ET
  ON EO.Customer_customer_id = ET.Customer_customer_id
GROUP BY segment
ORDER BY segment;

-- 3. ISO GQL root-cause traversal from refunded Enterprise orders to support tickets
GRAPH demo.CommerceGraph
MATCH (o:Orders {status: 'refunded'})-[:PlacedBy]->(c:Customer {segment: 'Enterprise'})<-[:OpenedBy]-(t:SupportTicket)
RETURN c.customer_name, o.order_id, o.order_total, t.topic, t.resolution_hours
ORDER BY t.topic;
