CREATE OR REPLACE PROPERTY GRAPH demo.CommerceGraph
  NODE TABLES (
    demo.customers AS Customer
      KEY (customer_id)
      PROPERTIES (customer_id, customer_name, segment),

    demo.orders AS Orders
      KEY (order_id)
      PROPERTIES (
        order_id, customer_id, status, order_total, shipping_fee,
        MEASURE(SUM(order_total)) AS gross_revenue OPTIONS (
          description = 'Gross order value in USD before refunds',
          synonyms = ['GMV', 'gross_sales'],
          extensions = [('unit', 'USD'), ('owner', 'finance-analytics'), ('reporting_tier', 'executive')]
        ),
        MEASURE(COUNT(order_id)) AS order_count OPTIONS (
          description = 'Total unique order count',
          synonyms = ['number of orders', 'orders'],
          extensions = [('owner', 'revops')]
        ),
        MEASURE(SUM(shipping_fee)) AS total_shipping OPTIONS (
          description = 'Order-level shipping fee in USD',
          synonyms = ['shipping cost', 'shipping'],
          extensions = [('unit', 'USD'), ('owner', 'logistics-ops')]
        ),
        MEASURE(SUM(CASE WHEN status = 'refunded' THEN order_total ELSE 0.0 END)) AS refunded_revenue OPTIONS (
          description = 'Total USD value of refunded orders',
          extensions = [('unit', 'USD'), ('owner', 'finance-analytics')]
        ),
        MEASURE(
          SAFE_DIVIDE(AGG(refunded_revenue), NULLIF(AGG(gross_revenue), 0)) * 100.0
        ) AS refund_rate_pct OPTIONS (
          description = 'Dollar-weighted refund rate percentage',
          synonyms = ['return rate', 'refund %'],
          extensions = [('unit', 'percent'), ('owner', 'finance-analytics'), ('reporting_tier', 'executive')]
        ),
        MEASURE(
          COUNT(DISTINCT CASE WHEN status = 'completed' THEN customer_id END)
        ) AS completed_buyer_count OPTIONS (
          description = 'Distinct paying customer count (completed orders only; excludes refunded orders)',
          synonyms = ['active buyers', 'paying customers'],
          extensions = [('owner', 'growth-analytics')]
        )
      ),

    demo.order_items AS OrderItem
      KEY (item_id)
      PROPERTIES (
        item_id, order_id, category, unit_price, qty,
        MEASURE(SUM(unit_price * qty)) AS item_sales OPTIONS (
          description = 'Line-item sales revenue (unit_price * qty)',
          synonyms = ['category sales', 'product sales'],
          extensions = [('unit', 'USD'), ('owner', 'merchandising')]
        )
      ),

    demo.support_tickets AS SupportTicket
      KEY (ticket_id)
      PROPERTIES (
        ticket_id, customer_id, topic, resolution_hours,
        MEASURE(COUNT(ticket_id)) AS ticket_count OPTIONS (
          description = 'Total unique support tickets',
          synonyms = ['support tickets', 'tickets'],
          extensions = [('owner', 'support-ops')]
        ),
        MEASURE(SUM(resolution_hours)) AS total_resolution_hours OPTIONS (
          description = 'Total support resolution hours',
          synonyms = ['resolution hours', 'support hours'],
          extensions = [('unit', 'hours'), ('owner', 'support-ops')]
        )
      )
  )
  EDGE TABLES (
    demo.order_items AS LineOf
      KEY (item_id)
      SOURCE KEY (item_id) REFERENCES OrderItem (item_id)
      DESTINATION KEY (order_id) REFERENCES Orders (order_id)
      NO PROPERTIES,
    demo.orders AS PlacedBy
      KEY (order_id)
      SOURCE KEY (order_id) REFERENCES Orders (order_id)
      DESTINATION KEY (customer_id) REFERENCES Customer (customer_id)
      NO PROPERTIES,
    demo.support_tickets AS OpenedBy
      KEY (ticket_id)
      SOURCE KEY (ticket_id) REFERENCES SupportTicket (ticket_id)
      DESTINATION KEY (customer_id) REFERENCES Customer (customer_id)
      NO PROPERTIES
  );
