
"""
Safe executor for validated SQL.

Validates SQL before execution, uses the read-only database engine,
and returns a compact result suitable for an AI agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import readonly_engine
from app.sql.validator import validate


PREVIEW_ROWS = 50


@dataclass
class QueryResult:
    ok: bool
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int
    error: str | None = None
    sql_executed: str | None = None

    def to_tool_payload(self) -> dict:
        """Return a compact payload for the AI agent."""

        if not self.ok:
            return {"ok": False, "error": self.error}

        return {
            "ok": True,
            "columns": self.columns,
            "rows": self.rows,
            "total_rows": self.total_rows,
            "preview_note": (
                f"Showing first {len(self.rows)} of {self.total_rows} rows."
                if self.total_rows > len(self.rows)
                else f"Showing all {len(self.rows)} rows."
            ),
        }


def run_sql(sql: str) -> QueryResult:
    """Validate and execute SQL. Return errors as data instead of raising."""

    # Step 1: Validate before opening a database connection.
    validation = validate(sql)

    if not validation.ok:
        return QueryResult(
            ok=False,
            columns=[],
            rows=[],
            total_rows=0,
            error=f"Rejected by validator: {validation.reason}",
        )

    # Step 2: Execute only the rewritten, validated SQL.
    engine = readonly_engine()

    try:
        with engine.connect() as conn:
            # Use a transaction so SET LOCAL applies to this query.
            with conn.begin():
                conn.execute(text("SET LOCAL statement_timeout = '5s'"))
                df = pd.read_sql_query(
                    text(validation.rewritten_sql),
                    conn,
                )

    except SQLAlchemyError as exc:
        message = str(exc).splitlines()[0]

        return QueryResult(
            ok=False,
            columns=[],
            rows=[],
            total_rows=0,
            error=f"SQL error: {message}",
            sql_executed=validation.rewritten_sql,
        )

    # Step 3: Return column names and at most 50 preview rows.
    columns = list(df.columns)
    total = len(df)
    rows = df.head(PREVIEW_ROWS).values.tolist()

    return QueryResult(
        ok=True,
        columns=columns,
        rows=rows,
        total_rows=total,
        sql_executed=validation.rewritten_sql,
    )