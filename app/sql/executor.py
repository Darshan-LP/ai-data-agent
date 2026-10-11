
"""
Safe executor for validated SQL.

Validates SQL before execution, uses the read-only database engine,
and returns both a preview and the full DataFrame.
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
    """Result returned by the SQL executor."""

    ok: bool
    columns: list[str]
    rows: list[list[Any]]
    total_rows: int
    error: str | None = None
    sql_executed: str | None = None
    dataframe: pd.DataFrame | None = None

    def to_tool_payload(self) -> dict:
        """Return a compact payload for the AI agent."""

        if not self.ok:
            return {
                "ok": False,
                "error": self.error,
            }

        return {
            "ok": True,
            "columns": self.columns,
            "rows": self.rows,
            "total_rows": self.total_rows,
            "preview_note": (
                f"Showing first {len(self.rows)} of "
                f"{self.total_rows} rows."
                if self.total_rows > len(self.rows)
                else f"Showing all {len(self.rows)} rows."
            ),
        }


def run_sql(sql: str) -> QueryResult:
    """
    Validate and execute SQL once.

    Returns a full DataFrame for reporting tools and a small
    preview for the AI agent.
    """

    # Step 1: Validate SQL before opening a database connection.
    validation = validate(sql)

    if not validation.ok:
        return QueryResult(
            ok=False,
            columns=[],
            rows=[],
            total_rows=0,
            error=f"Rejected by validator: {validation.reason}",
        )

    # Step 2: Execute only the validated and rewritten SQL.
    engine = readonly_engine()

    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(
                    text("SET LOCAL statement_timeout = '5s'")
                )

                query_result = conn.execute(
                    text(validation.rewritten_sql)
                )

                columns = list(query_result.keys())
                fetched_rows = query_result.fetchall()

        # Step 3: Build the full DataFrame from the fetched results.
        dataframe = pd.DataFrame(
            fetched_rows,
            columns=columns,
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

    except (ValueError, TypeError) as exc:
        return QueryResult(
            ok=False,
            columns=[],
            rows=[],
            total_rows=0,
            error=f"Could not process query results: {exc}",
            sql_executed=validation.rewritten_sql,
        )

    finally:
        engine.dispose()

    # Step 4: Preserve the existing preview format.
    total = len(dataframe)

    preview_rows = [
        list(row)
        for row in dataframe.head(PREVIEW_ROWS).itertuples(
            index=False,
            name=None,
        )
    ]

    return QueryResult(
        ok=True,
        columns=columns,
        rows=preview_rows,
        total_rows=total,
        sql_executed=validation.rewritten_sql,
        dataframe=dataframe,
    )
