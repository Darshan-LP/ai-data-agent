-- Business tables + agent_runs
-- Runs as app_admin on first DB boot.

CREATE TABLE customers (
id          SERIAL PRIMARY KEY,
name        TEXT NOT NULL,
city        TEXT NOT NULL,
segment     TEXT NOT NULL CHECK (segment IN ('retail','wholesale','vip')),
created_at  DATE NOT NULL
);

CREATE TABLE products (
id        SERIAL PRIMARY KEY,
name      TEXT NOT NULL,
category  TEXT NOT NULL,
price     NUMERIC(10,2) NOT NULL CHECK (price >= 0)
);

CREATE TABLE orders (
id           SERIAL PRIMARY KEY,
customer_id  INT NOT NULL REFERENCES customers(id),
order_date   DATE NOT NULL,
status       TEXT NOT NULL CHECK (status IN ('completed','pending','cancelled','refunded'))
);

CREATE TABLE order_items (
id          SERIAL PRIMARY KEY,
order_id    INT NOT NULL REFERENCES orders(id),
product_id  INT NOT NULL REFERENCES products(id),
quantity    INT NOT NULL CHECK (quantity > 0),
unit_price  NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0)
);

CREATE INDEX idx_orders_customer   ON orders(customer_id);
CREATE INDEX idx_orders_date       ON orders(order_date);
CREATE INDEX idx_items_order       ON order_items(order_id);
CREATE INDEX idx_items_product     ON order_items(product_id);

-- Agent observability table (written by app_admin only)
CREATE TABLE agent_runs (
id             SERIAL PRIMARY KEY,
question       TEXT NOT NULL,
trace          JSONB NOT NULL DEFAULT '[]'::jsonb,
final_answer   TEXT,
sql_generated  TEXT[],
status         TEXT NOT NULL,
latency_ms     INT,
input_tokens   INT,
output_tokens  INT,
cost_usd       NUMERIC(10,6),
created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
