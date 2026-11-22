CREATE SCHEMA IF NOT EXISTS demo;

CREATE OR REPLACE TABLE demo.customers (
  customer_id STRING NOT NULL,
  customer_name STRING,
  segment STRING,
  PRIMARY KEY (customer_id) NOT ENFORCED
);
INSERT INTO demo.customers VALUES
  ('Cust-001', 'Acme', 'Enterprise'),
  ('Cust-002', 'Beta', 'Enterprise'),
  ('Cust-003', 'Cozy', 'SMB');

CREATE OR REPLACE TABLE demo.orders (
  order_id STRING NOT NULL,
  customer_id STRING,
  order_total FLOAT64,
  shipping_fee FLOAT64,
  status STRING,
  PRIMARY KEY (order_id) NOT ENFORCED,
  FOREIGN KEY (customer_id) REFERENCES demo.customers(customer_id) NOT ENFORCED
);
INSERT INTO demo.orders VALUES
  ('Ord-001', 'Cust-001', 900.0, 30.0, 'completed'),
  ('Ord-002', 'Cust-001', 100.0, 10.0, 'refunded'),
  ('Ord-003', 'Cust-003', 200.0, 15.0, 'completed');

CREATE OR REPLACE TABLE demo.order_items (
  item_id STRING NOT NULL,
  order_id STRING,
  category STRING,
  unit_price FLOAT64,
  qty INT64,
  PRIMARY KEY (item_id) NOT ENFORCED,
  FOREIGN KEY (order_id) REFERENCES demo.orders(order_id) NOT ENFORCED
);
INSERT INTO demo.order_items VALUES
  ('Item-001', 'Ord-001', 'Hardware', 200.0, 2),
  ('Item-002', 'Ord-001', 'Hardware', 400.0, 1),
  ('Item-003', 'Ord-001', 'Accessory', 100.0, 1),
  ('Item-004', 'Ord-002', 'Hardware', 100.0, 1),
  ('Item-005', 'Ord-003', 'Software', 200.0, 1);

CREATE OR REPLACE TABLE demo.support_tickets (
  ticket_id STRING NOT NULL,
  customer_id STRING,
  topic STRING,
  resolution_hours INT64,
  PRIMARY KEY (ticket_id) NOT ENFORCED,
  FOREIGN KEY (customer_id) REFERENCES demo.customers(customer_id) NOT ENFORCED
);
INSERT INTO demo.support_tickets VALUES
  ('Tkt-001', 'Cust-001', 'billing', 4),
  ('Tkt-002', 'Cust-001', 'shipping', 8),
  ('Tkt-003', 'Cust-002', 'onboarding', 2);
