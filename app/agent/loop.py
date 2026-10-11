"""
Agent loop for the AI Data Agent using OpenAI.
Tracks generated chart and Excel artifacts.
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


@dataclass
class Step:
    """Record one action performed by the agent."""

    step_number: int
    action: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRun:
    """Store the result of one agent run."""

    answer: str
    steps: list[Step]
    success: bool
    error: str | None = None
    artifacts: list[dict[str, str]] = field(default_factory=list)


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
    """Run the OpenAI tool-calling loop."""

    question = question.strip()

    if not question:
        return AgentRun(
            answer="Please enter a question.",
            steps=[],
            success=False,
            error="Empty question.",
        )

    settings = get_settings()

    if not settings.openai_api_key.strip():
        return AgentRun(
            answer="The OpenAI API key is not configured.",
            steps=[],
            success=False,
            error="Missing OPENAI_API_KEY.",
        )

    client = OpenAI(api_key=settings.openai_api_key)
    instructions = build_system_prompt()
    tools = _openai_tools()

    steps: list[Step] = []
    artifacts: list[dict[str, str]] = []
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
                    details={
                        "error": error_message,
                    },
                )
            )

            return AgentRun(
                answer=(
                    "I couldn't contact the OpenAI service. "
                    "Check your API key, model access, and billing."
                ),
                steps=steps,
                success=False,
                error=error_message,
                artifacts=artifacts,
            )

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

            return AgentRun(
                answer=answer,
                steps=steps,
                success=True,
                artifacts=artifacts,
            )

        for call in function_calls:
            try:
                arguments = json.loads(call.arguments)

                if not isinstance(arguments, dict):
                    raise ValueError(
                        "Tool arguments must be a JSON object."
                    )

            except (
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ):
                result = {
                    "ok": False,
                    "error": (
                        "Invalid tool arguments. "
                        "Expected a JSON object."
                    ),
                }

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

            if (
                not isinstance(result, dict)
                or not result.get("ok", False)
            ):
                tool_failures += 1

                steps.append(
                    Step(
                        step_number=iteration,
                        action="tool_error",
                        details={
                            "tool": call.name,
                            "error": (
                                result.get(
                                    "error",
                                    "Unknown tool error.",
                                )
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
            return AgentRun(
                answer=(
                    "I couldn't complete the request after multiple "
                    "tool failures. Please try rephrasing your question "
                    "or simplifying the requested report."
                ),
                steps=steps,
                success=False,
                error="Tool failure limit reached.",
                artifacts=artifacts,
            )

    return AgentRun(
        answer=(
            "I reached the maximum number of agent steps "
            "before completing the request."
        ),
        steps=steps,
        success=False,
        error="Maximum agent iterations reached.",
        artifacts=artifacts,
    )