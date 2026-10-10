"""
Agent loop for the AI Data Agent using OpenAI.

Flow:
1. Send the user's question to GPT.
2. GPT requests the run_sql_query tool when needed.
3. Python dispatches the request through the existing SQL safety layer.
4. The tool result is returned to GPT.
5. GPT produces the final answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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


def _jsonable(value: Any) -> Any:
    """Convert common Python values to JSON-compatible values."""
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]

    if hasattr(value, "isoformat"):
        return value.isoformat()

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


def _openai_tools() -> list[dict[str, Any]]:
    """Convert our existing tool schemas to OpenAI function tools."""
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


def run_agent(question: str) -> AgentRun:
    """Run the OpenAI tool-calling loop for a user's question."""

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
    sql_failures = 0
    max_iterations = max(1, settings.max_agent_iterations)

    # Responses API input can contain user messages and tool outputs.
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

            return AgentRun(
                answer=(
                    "I couldn't contact the OpenAI service. "
                    "Check your API key, model access, and billing."
                ),
                steps=steps,
                success=False,
                error=error_message,
            )

        # Save the model's response items so the next request
        # can continue the same tool-calling interaction.
        input_items.extend(
            item.model_dump(exclude_none=True)
            for item in response.output
        )

        function_calls = [
            item for item in response.output
            if item.type == "function_call"
        ]

        # No tool call means GPT has returned its final answer.
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
            )

        for call in function_calls:
            try:
                arguments = json.loads(call.arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = {}

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

            if not result.get("ok", False):
                sql_failures += 1

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

        # Stop after the initial failure plus two retries.
        if sql_failures >= 3:
            return AgentRun(
                answer=(
                    "I couldn't complete the query after multiple "
                    "attempts. Please try rephrasing your question."
                ),
                steps=steps,
                success=False,
                error="Tool failure limit reached.",
            )

    return AgentRun(
        answer=(
            "I reached the maximum number of agent steps "
            "before completing the request."    
        ),
        steps=steps,
        success=False,
        error="Maximum agent iterations reached.",
    )