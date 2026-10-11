from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent.loop import run_agent
from app.config import get_settings
from app.db import admin_engine, readonly_engine, ping


app = FastAPI(
    title="AI Data Agent",
    version="0.3.0",
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
            "Create a chart of customers by segment.",
            "Export customer counts by segment to Excel.",
        ],
    )


class ArtifactLink(BaseModel):
    name: str
    url: str
    kind: str


class AgentResponse(BaseModel):
    success: bool
    answer: str
    error: str | None = None
    artifacts: list[ArtifactLink] = Field(default_factory=list)


def _outputs_directory() -> Path:
    """Resolve the configured output directory to an absolute path."""

    configured = Path(get_settings().outputs_dir)

    if not configured.is_absolute():
        configured = Path.cwd() / configured

    return configured.resolve()


@app.get("/")
def root() -> dict:
    return {
        "message": "AI Data Agent API is running.",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health() -> dict:
    settings = get_settings()

    admin_ok = ping(admin_engine())
    readonly_ok = ping(readonly_engine())

    return {
        "status": "ok" if (admin_ok and readonly_ok) else "degraded",
        "postgres_host": settings.postgres_host,
        "postgres_db": settings.postgres_db,
        "admin_connection": admin_ok,
        "readonly_connection": readonly_ok,
    }


@app.get("/artifacts/{filename}")
def download_artifact(filename: str) -> FileResponse:
    """Serve an allowed report file from the configured output directory."""

    if (
        not filename
        or filename in {".", ".."}
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid artifact filename.",
        )

    media_types = {
        ".png": "image/png",
        ".html": "text/html",
        ".xlsx": (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    }

    suffix = Path(filename).suffix.lower()

    if suffix not in media_types:
        raise HTTPException(
            status_code=404,
            detail="Artifact type not supported.",
        )

    output_dir = _outputs_directory()
    file_path = (output_dir / filename).resolve()

    if file_path.parent != output_dir:
        raise HTTPException(
            status_code=400,
            detail="Invalid artifact path.",
        )

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Artifact not found.",
        )

    return FileResponse(
        path=file_path,
        media_type=media_types[suffix],
        filename=file_path.name,
    )


@app.post("/agent/run", response_model=AgentResponse)
def run_agent_endpoint(request: AgentRequest) -> AgentResponse:
    """Run the agent and return links for any generated artifacts."""

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

    output_dir = _outputs_directory()
    artifact_links: list[ArtifactLink] = []

    for artifact in result.artifacts:
        filename = artifact.get("filename", "")

        # Validate the filename before creating a public download URL.
        if (
            not filename
            or Path(filename).name != filename
            or "/" in filename
            or "\\" in filename
            or Path(filename).suffix.lower()
            not in {".png", ".html", ".xlsx"}
        ):
            continue

        file_path = (output_dir / filename).resolve()

        # Never return a link for a file outside the configured directory.
        if file_path.parent != output_dir or not file_path.is_file():
            continue

        artifact_links.append(
            ArtifactLink(
                name=artifact.get("label", filename),
                url=f"/artifacts/{filename}",
                kind=artifact.get(
                    "content_type",
                    "application/octet-stream",
                ),
            )
        )

    return AgentResponse(
        success=result.success,
        answer=result.answer,
        error=result.error,
        artifacts=artifact_links,
    )