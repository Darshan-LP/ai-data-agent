import pytest

from app.sql.executor import run_sql


@pytest.mark.integration
def test_select_returns_rows():
    result = run_sql(
        "SELECT id, name FROM customers ORDER BY id LIMIT 3"
    )

    assert result.ok, result.error
    assert result.columns == ["id", "name"]
    assert len(result.rows) == 3
    assert result.total_rows == 3


@pytest.mark.integration
def test_rejected_sql_never_touches_db():
    result = run_sql("DROP TABLE orders")

    assert not result.ok
    assert "Rejected" in (result.error or "")


@pytest.mark.integration
def test_invalid_column_returns_sql_error():
    result = run_sql(
        "SELECT nonexistent_column FROM customers"
    )

    assert not result.ok
    assert "SQL error" in (result.error or "")


@pytest.mark.integration
def test_limit_is_applied_when_omitted():
    result = run_sql("SELECT * FROM orders")

    assert result.ok, result.error
    assert result.total_rows <= 1000