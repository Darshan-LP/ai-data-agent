import pytest

from app.sql.validator import validate


# ---------- ALLOWED QUERIES ----------

@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, name FROM customers",
        "SELECT COUNT(*) FROM orders",
        (
            "SELECT c.name, SUM(oi.quantity * oi.unit_price) AS revenue "
            "FROM customers c "
            "JOIN orders o ON o.customer_id = c.id "
            "JOIN order_items oi ON oi.order_id = o.id "
            "GROUP BY c.name"
        ),
        (
            "WITH monthly AS ("
            "SELECT date_trunc('month', order_date) AS m, COUNT(*) AS n "
            "FROM orders GROUP BY 1"
            ") SELECT * FROM monthly ORDER BY m DESC"
        ),
        "SELECT * FROM products WHERE category = 'Electronics' LIMIT 5",
    ],
)
def test_allowed(sql):
    result = validate(sql)

    assert result.ok, result.reason
    assert result.rewritten_sql


def test_missing_limit_is_added():
    result = validate("SELECT * FROM customers")

    assert result.ok
    assert "LIMIT 1000" in result.rewritten_sql


def test_existing_limit_is_preserved():
    result = validate("SELECT * FROM customers LIMIT 5")

    assert result.ok
    assert "LIMIT 5" in result.rewritten_sql


def test_oversized_limit_is_clamped():
    result = validate("SELECT * FROM customers LIMIT 999999")

    assert result.ok
    assert "LIMIT 1000" in result.rewritten_sql


# ---------- BLOCKED QUERIES ----------

def test_empty():
    result = validate("   ")

    assert not result.ok


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE orders",
        "DELETE FROM orders WHERE id = 1",
        "UPDATE orders SET status = 'x'",
        "INSERT INTO customers (name) VALUES ('x')",
        "ALTER TABLE orders ADD COLUMN x INT",
        "TRUNCATE orders",
        "COPY customers TO '/tmp/x'",
    ],
)
def test_write_statements_blocked(sql):
    result = validate(sql)

    assert not result.ok
    assert "Only SELECT" in (result.reason or "")


def test_multi_statement_blocked():
    result = validate("SELECT 1; DROP TABLE orders;")

    assert not result.ok
    assert "exactly 1 statement" in (result.reason or "").lower()


def test_forbidden_function_blocked():
    result = validate("SELECT pg_sleep(10)")

    assert not result.ok
    assert "pg_sleep" in (result.reason or "").lower()


def test_forbidden_schema_blocked():
    result = validate("SELECT * FROM pg_catalog.pg_class")

    assert not result.ok
    assert "pg_catalog" in (result.reason or "").lower()


def test_non_allowlisted_table_blocked():
    result = validate("SELECT * FROM agent_runs")

    assert not result.ok
    assert "agent_runs" in (result.reason or "").lower()


def test_with_cte_containing_delete_blocked():
    result = validate(
        "WITH gone AS ("
        "DELETE FROM orders RETURNING id"
        ") SELECT * FROM gone"
    )

    assert not result.ok


def test_parse_error_is_rejected_cleanly():
    result = validate("SELECT FROM WHERE")

    assert not result.ok
    assert "parse" in (result.reason or "").lower()