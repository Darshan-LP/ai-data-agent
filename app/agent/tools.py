"""
Tool schemas and dispatcher for the AI Data Agent.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import text as sql_text
from sqlalchemy.exc import SQLAlchemyError

from app.agent.state import STORE
from app.db import readonly_engine
from app.sql.executor import run_sql


RUN_SQL_QUERY_SCHEMA: dict[str, Any] = {
    "name": "run_sql_query",
    "description": (
        "Execute a read-only PostgreSQL SELECT query against business "
        "tables. Returns columns, up to 50 preview rows, total row count, "
        "and a data reference. Only validated SQL is executed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "A single PostgreSQL SELECT statement.",
            }
        },
        "required": ["sql"],
    },
}

TOOLS: list[dict[str, Any]] = [RUN_SQL_QUERY_SCHEMA]


def dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a requested tool."""
    if name == "run_sql_query":
        return _run_sql_query(args)

    return {"ok": False, "error": f"Unknown tool: {name}"}


def _run_sql_query(args: dict[str, Any]) -> dict[str, Any]:
    """Validate, execute, and store a SQL query result."""
    sql = args.get("sql", "")

    if not isinstance(sql, str) or not sql.strip():
        return {"ok": False, "error": "A non-empty SQL string is required."}

    result = run_sql(sql)

    if not result.ok:
        return {
            "ok": False,
            "error": result.error or "SQL execution failed.",
        }

    if not result.sql_executed:
        return {
            "ok": False,
            "error": "The executor did not return validated SQL.",
        }

    try:
        engine = readonly_engine()
        try:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(
                        sql_text("SET LOCAL statement_timeout = '5s'")
                    )
                    query_result = conn.execute(
                        sql_text(result.sql_executed)
                    )
                    columns = list(query_result.keys())
                    rows = query_result.fetchall()

            df = pd.DataFrame(rows, columns=columns)
        finally:
            engine.dispose()

    except (SQLAlchemyError, ValueError, TypeError) as exc:
        return {
            "ok": False,
            "error": (
                "The query succeeded, but storing its full result failed: "
                f"{str(exc).splitlines()[0]}"
            ),
        }

    stored = STORE.put(
        ref="last",
        sql=result.sql_executed,
        df=df,
    )

    preview = df.head(50).to_dict(orient="records")

    return {
        "ok": True,
        "columns": stored.columns,
        "rows": preview,
        "total_rows": stored.total_rows,
        "preview_note": (
            f"Showing first 50 of {stored.total_rows} rows."
            if stored.total_rows > 50
            else f"Showing all {stored.total_rows} rows."
        ),
        "data_ref": stored.ref,
    }