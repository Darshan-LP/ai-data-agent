
"""
Agent loop for the AI Data Agent using OpenAI.
Tracks artifacts, token usage, and estimated API cost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import PurePath, PurePosixPath
from typing import Any

from openai import OpenAI

from app.agent.prompts import build_system_prompt
from app.agent.tools import TOOLS, dispatch
from app.config import get_settings


# Standard API pricing in USD per one million tokens.
# Update this table if OpenAI changes its published pricing.
MODEL_PRICING = {
    "gpt-5-nano": {
        "input": 0.05,
        "cached_input": 0.005,
        "output": 0.40,
    },
    "gpt-5-nano-2025-08-07": {
        "input": 0.05,
        "cached_input": 0.005,
        "output": 0.40,
    },
}


@dataclass
class Step:
    """Record one action performed by the agent."""

    step_number: int
    action: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRun:
    """Store the result and usage information for one agent run."""

    answer: str
    steps: list[Step]
    success: bool
    error: str | None = None
    artifacts: list[dict[str, str]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0


def _jsonable(value: Any) -> Any:
    """Convert common Python values to JSON-compatible values."""

    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]

    if hasattr(value, "isoformat"):
        return value.isoformat()

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


def _openai_tools() -> list[dict[str, Any]]:
    """Convert our tool schemas to OpenAI function tools."""

    return [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
            "strict": False,
        }
        for tool in TOOLS
    ]


def _artifact_filename(raw_path: Any) -> str | None:
    """Extract an allowed filename from a Windows or Linux path."""

    if not isinstance(raw_path, str) or not raw_path.strip():
        return None

    normalized = raw_path.strip().replace("\\", "/")
    filename = PurePosixPath(normalized).name

    if not filename or filename in {".", ".."}:
        return None

    if PurePath(filename).suffix.lower() not in {
        ".png",
        ".html",
        ".xlsx",
    }:
        return None

    if "/" in filename or "\\" in filename:
        return None

    return filename


def _collect_artifacts(
    result: dict[str, Any],
    artifacts: list[dict[str, str]],
) -> None:
    """Collect generated files from successful tools."""

    if not result.get("ok", False):
        return

    path_fields = (
        ("png_path", "Chart image", "image/png"),
        ("html_path", "Interactive chart", "text/html"),
        (
            "excel_path",
            "Excel report",
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet",
        ),
    )

    existing_names = {
        item["filename"]
        for item in artifacts
    }

    for field_name, label, content_type in path_fields:
        filename = _artifact_filename(result.get(field_name))

        if filename is None or filename in existing_names:
            continue

        artifacts.append(
            {
                "filename": filename,
                "label": label,
                "content_type": content_type,
            }
        )

        existing_names.add(filename)


def run_agent(question: str) -> AgentRun:
    """Run the tool-calling loop and aggregate API usage."""

    settings = get_settings()

    steps: list[Step] = []
    artifacts: list[dict[str, str]] = []
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
    }

    model_pricing = MODEL_PRICING.get(settings.openai_model)
    estimated_cost = 0.0

    def make_run(
        answer: str,
        success: bool,
        error: str | None = None,
    ) -> AgentRun:
        """Build every result with the accumulated usage totals."""

        return AgentRun(
            answer=answer,
            steps=steps.copy(),
            success=success,
            error=error,
            artifacts=artifacts.copy(),
            input_tokens=usage_totals["input_tokens"],
            output_tokens=usage_totals["output_tokens"],
            cost_usd=(
                round(estimated_cost, 10)
                if model_pricing is not None
                else None
            ),
        )

    question = question.strip()

    if not question:
        return make_run("Please enter a question.", False, "Empty question.")

    if not settings.openai_api_key.strip():
        return make_run(
            "The OpenAI API key is not configured.",
            False,
            "Missing OPENAI_API_KEY.",
        )

    client = OpenAI(api_key=settings.openai_api_key)
    instructions = build_system_prompt()
    tools = _openai_tools()

    tool_failures = 0
    max_iterations = max(1, settings.max_agent_iterations)

    input_items: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": question,
        }
    ]

    for iteration in range(1, max_iterations + 1):
        try:
            response = client.responses.create(
                model=settings.openai_model,
                instructions=instructions,
                input=input_items,
                tools=tools,
                tool_choice="auto",
                max_output_tokens=settings.max_tokens_per_run,
            )

        except Exception as exc:
            error_message = str(exc).splitlines()[0]

            steps.append(
                Step(
                    step_number=iteration,
                    action="api_error",
                    details={"error": error_message},
                )
            )

            return make_run(
                "I couldn't contact the OpenAI service. "
                "Check your API key, model access, and billing.",
                False,
                error_message,
            )

        # Accumulate usage for every model response, including tool calls.
        usage = getattr(response, "usage", None)

        if usage is not None:
            input_count = int(getattr(usage, "input_tokens", 0) or 0)
            output_count = int(getattr(usage, "output_tokens", 0) or 0)

            input_details = getattr(usage, "input_tokens_details", None)
            cached_count = int(
                getattr(input_details, "cached_tokens", 0) or 0
            )
            cached_count = min(cached_count, input_count)

            usage_totals["input_tokens"] += input_count
            usage_totals["output_tokens"] += output_count
            usage_totals["cached_input_tokens"] += cached_count

            if model_pricing is not None:
                uncached_count = input_count - cached_count

                estimated_cost += (
                    uncached_count * model_pricing["input"]
                    + cached_count * model_pricing["cached_input"]
                    + output_count * model_pricing["output"]
                ) / 1_000_000

        input_items.extend(
            item.model_dump(exclude_none=True)
            for item in response.output
        )

        function_calls = [
            item
            for item in response.output
            if item.type == "function_call"
        ]

        if not function_calls:
            answer = (response.output_text or "").strip()

            if not answer:
                answer = "The AI service returned no text answer."

            steps.append(
                Step(
                    step_number=iteration,
                    action="final_answer",
                    details={
                        "response_id": response.id,
                        "status": response.status,
                    },
                )
            )

            return make_run(answer, True)

        for call in function_calls:
            try:
                arguments = json.loads(call.arguments)

                if not isinstance(arguments, dict):
                    raise ValueError(
                        "Tool arguments must be a JSON object."
                    )

            except (json.JSONDecodeError, TypeError, ValueError):
                result = {
                    "ok": False,
                    "error": (
                        "Invalid tool arguments. "
                        "Expected a JSON object."
                    ),
                }

                steps.append(
                    Step(
                        step_number=iteration,
                        action="tool_error",
                        details={
                            "tool": call.name,
                            "error": result["error"],
                        },
                    )
                )

            else:
                steps.append(
                    Step(
                        step_number=iteration,
                        action="tool_call",
                        details={
                            "tool": call.name,
                            "arguments": _jsonable(arguments),
                        },
                    )
                )

                try:
                    result = dispatch(call.name, arguments)

                except Exception as exc:
                    result = {
                        "ok": False,
                        "error": (
                            "Tool execution failed: "
                            f"{str(exc).splitlines()[0]}"
                        ),
                    }

            if isinstance(result, dict):
                _collect_artifacts(result, artifacts)

            if not isinstance(result, dict) or not result.get("ok", False):
                tool_failures += 1

                steps.append(
                    Step(
                        step_number=iteration,
                        action="tool_error",
                        details={
                            "tool": call.name,
                            "error": (
                                result.get("error", "Unknown tool error.")
                                if isinstance(result, dict)
                                else "Tool returned an invalid result."
                            ),
                            "failure_count": tool_failures,
                        },
                    )
                )

            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(
                        _jsonable(result),
                        ensure_ascii=False,
                    ),
                }
            )

        if tool_failures >= 3:
            return make_run(
                "I couldn't complete the request after multiple "
                "tool failures. Please try rephrasing your question "
                "or simplifying the requested report.",
                False,
                "Tool failure limit reached.",
            )

    return make_run(
        "I reached the maximum number of agent steps "
        "before completing the request.",
        False,
        "Maximum agent iterations reached.",
    )
