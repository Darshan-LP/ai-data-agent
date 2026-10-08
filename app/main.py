from fastapi import FastAPI

from app.config import get_settings
from app.db import admin_engine, readonly_engine, ping


app = FastAPI(
    title="AI Data Agent",
    version="0.1.0",
)


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