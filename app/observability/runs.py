
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.db import admin_engine


def log_run(
    question: str,
    run: Any,
    latency_ms: int,
) -> None:
    """Save a completed or failed agent run and its observability data."""

    trace = [
        {
            "step_number": step.step_number,
            "action": step.action,
            "details": step.details,
        }
        for step in run.steps
    ]

    sql_statements = [
        step.details["arguments"]["sql"]
        for step in run.steps
        if (
            step.action == "tool_call"
            and step.details.get("tool") == "run_sql_query"
            and isinstance(step.details.get("arguments"), dict)
            and isinstance(step.details["arguments"].get("sql"), str)
        )
    ]

    input_tokens = getattr(run, "input_tokens", None)
    output_tokens = getattr(run, "output_tokens", None)
    cost_usd = getattr(run, "cost_usd", None)

    values = {
        "question": question,
        "trace": json.dumps(trace, default=str),
        "final_answer": run.answer,
        "sql_generated": sql_statements or None,
        "status": "success" if run.success else "failed",
        "latency_ms": max(0, int(latency_ms)),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    }

    with admin_engine().begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO agent_runs (
                    question,
                    trace,
                    final_answer,
                    sql_generated,
                    status,
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    cost_usd
                )
                VALUES (
                    :question,
                    CAST(:trace AS JSONB),
                    :final_answer,
                    :sql_generated,
                    :status,
                    :latency_ms,
                    :input_tokens,
                    :output_tokens,
                    :cost_usd
                )
                """
            ),
            values,
        )


def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent runs, including trace and generated SQL."""

    limit = max(1, min(int(limit), 100))

    with admin_engine().connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT
                    id,
                    question,
                    final_answer,
                    status,
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    cost_usd,
                    trace,
                    sql_generated,
                    created_at
                FROM agent_runs
                ORDER BY created_at DESC, id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )

        runs = []

        for row in result.mappings():
            item = dict(row)

            if item["created_at"] is not None:
                item["created_at"] = item["created_at"].isoformat()

            if item["cost_usd"] is not None:
                item["cost_usd"] = float(item["cost_usd"])

            runs.append(item)

        return runs
