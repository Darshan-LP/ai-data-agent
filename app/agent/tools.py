
"""
Tool schemas and dispatcher for the AI Data Agent.

Available tools:
- run_sql_query
- create_chart
- export_excel
"""

from __future__ import annotations

from typing import Any

from app.agent.state import STORE
from app.reporting.chart import build_chart
from app.reporting.excel import export_excel
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


CREATE_CHART_SCHEMA: dict[str, Any] = {
    "name": "create_chart",
    "description": (
        "Create a chart from a previous SQL query result. "
        "Supports bar, line, and pie charts. Use the data_ref returned "
        "by run_sql_query, normally 'last'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "data_ref": {
                "type": "string",
                "description": "Reference returned by run_sql_query.",
            },
            "chart_type": {
                "type": "string",
                "enum": ["bar", "line", "pie"],
                "description": "Type of chart to generate.",
            },
            "x": {
                "type": "string",
                "description": "Column to use for labels or the x-axis.",
            },
            "y": {
                "type": "string",
                "description": "Numeric column to plot.",
            },
            "title": {
                "type": "string",
                "description": "Human-readable chart title.",
            },
        },
        "required": [
            "data_ref",
            "chart_type",
            "x",
            "y",
            "title",
        ],
    },
}


EXPORT_EXCEL_SCHEMA: dict[str, Any] = {
    "name": "export_excel",
    "description": (
        "Export a previous SQL query result to a formatted Excel workbook. "
        "Use the data_ref returned by run_sql_query, normally 'last'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "data_ref": {
                "type": "string",
                "description": "Reference returned by run_sql_query.",
            },
            "title": {
                "type": "string",
                "description": "Human-readable Excel report title.",
            },
        },
        "required": ["data_ref", "title"],
    },
}


TOOLS: list[dict[str, Any]] = [
    RUN_SQL_QUERY_SCHEMA,
    CREATE_CHART_SCHEMA,
    EXPORT_EXCEL_SCHEMA,
]


def dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a requested tool."""

    if name == "run_sql_query":
        return _run_sql_query(args)

    if name == "create_chart":
        return _create_chart(args)

    if name == "export_excel":
        return _export_excel(args)

    return {
        "ok": False,
        "error": f"Unknown tool: {name}",
    }


def _run_sql_query(args: dict[str, Any]) -> dict[str, Any]:
    """Execute SQL once and store the complete result."""

    sql = args.get("sql", "")

    if not isinstance(sql, str) or not sql.strip():
        return {
            "ok": False,
            "error": "A non-empty SQL string is required.",
        }

    result = run_sql(sql)

    if not result.ok:
        return {
            "ok": False,
            "error": result.error or "SQL execution failed.",
        }

    if result.dataframe is None:
        return {
            "ok": False,
            "error": "The SQL executor did not return a DataFrame.",
        }

    stored = STORE.put(
        ref="last",
        sql=result.sql_executed or sql,
        df=result.dataframe,
    )

    return {
        "ok": True,
        "columns": stored.columns,
        "rows": result.rows,
        "total_rows": stored.total_rows,
        "preview_note": (
            f"Showing first 50 of {stored.total_rows} rows."
            if stored.total_rows > 50
            else f"Showing all {stored.total_rows} rows."
        ),
        "data_ref": stored.ref,
    }


def _get_stored_result(data_ref: Any):
    """Validate a reference and retrieve its stored result."""

    if not isinstance(data_ref, str) or not data_ref.strip():
        return None, {
            "ok": False,
            "error": "A non-empty data_ref is required.",
        }

    stored = STORE.get(data_ref)

    if stored is None:
        return None, {
            "ok": False,
            "error": (
                f"No result found for data_ref '{data_ref}'. "
                "Run run_sql_query first."
            ),
        }

    return stored, None


def _create_chart(args: dict[str, Any]) -> dict[str, Any]:
    """Create HTML and PNG charts from a stored SQL result."""

    stored, error = _get_stored_result(args.get("data_ref"))

    if error:
        return error

    chart_type = args.get("chart_type")
    x = args.get("x")
    y = args.get("y")
    title = args.get("title")

    if not all(isinstance(value, str) and value.strip()
               for value in (chart_type, x, y, title)):
        return {
            "ok": False,
            "error": "chart_type, x, y, and title must be non-empty strings.",
        }

    artifact = build_chart(
        df=stored.df,
        chart_type=chart_type,
        x=x,
        y=y,
        title=title,
    )

    if not artifact.ok:
        return {
            "ok": False,
            "error": artifact.error or "Chart generation failed.",
        }

    return {
        "ok": True,
        "data_ref": stored.ref,
        "chart_type": chart_type,
        "png_path": artifact.png_path,
        "html_path": artifact.html_path,
    }


def _export_excel(args: dict[str, Any]) -> dict[str, Any]:
    """Export a stored SQL result to Excel."""

    stored, error = _get_stored_result(args.get("data_ref"))

    if error:
        return error

    title = args.get("title", "Data Report")

    if not isinstance(title, str) or not title.strip():
        return {
            "ok": False,
            "error": "title must be a non-empty string.",
        }

    try:
        output_path = export_excel(
            df=stored.df,
            title=title,
        )
    except (ValueError, OSError, TypeError) as exc:
        return {
            "ok": False,
            "error": f"Excel export failed: {exc}",
        }

    return {
        "ok": True,
        "data_ref": stored.ref,
        "excel_path": output_path,
        "total_rows": stored.total_rows,
    }
