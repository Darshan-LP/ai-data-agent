from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.agent.loop import run_agent
from app.config import get_settings
from app.db import admin_engine, readonly_engine, ping


app = FastAPI(
    title="AI Data Agent",
    version="0.2.0",
    description=(
        "Ask business questions in natural language and receive "
        "answers powered by OpenAI and a SQL safety layer."
    ),
)


class AgentRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Business question to answer using the database.",
        examples=[
            "How many orders are in the database?",
            "What are the top 5 products by revenue?",
        ],
    )


class AgentResponse(BaseModel):
    success: bool
    answer: str
    error: str | None = None


@app.get("/")
def root() -> dict:
    return {
        "message": "AI Data Agent API is running.",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict:
    s = get_settings()

    admin_ok = ping(admin_engine())
    readonly_ok = ping(readonly_engine())

    return {
        "status": "ok" if (admin_ok and readonly_ok) else "degraded",
        "postgres_host": s.postgres_host,
        "postgres_db": s.postgres_db,
        "admin_connection": admin_ok,
        "readonly_connection": readonly_ok,
    }


@app.post("/agent/run", response_model=AgentResponse)
def run_agent_endpoint(request: AgentRequest) -> AgentResponse:
    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=422,
            detail="Question cannot be empty.",
        )

    result = run_agent(question)

    if not result.success:
        raise HTTPException(
            status_code=502,
            detail={
                "message": result.answer,
                "error": result.error,
            },
        )

    return AgentResponse(
        success=result.success,
        answer=result.answer,
        error=result.error,
    )