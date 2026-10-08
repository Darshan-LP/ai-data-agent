from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine

from app.config import get_settings


def _url(user: str, password: str) -> URL:
    s = get_settings()
    return URL.create(
        drivername="postgresql+psycopg",
        username=user,
        password=password,
        host=s.postgres_host,
        port=s.postgres_port,
        database=s.postgres_db,
    )


def admin_engine() -> Engine:
    """Writer: migrations, seed, agent_runs logging."""
    s = get_settings()
    return create_engine(
        _url(s.postgres_admin_user, s.postgres_admin_password),
        pool_pre_ping=True,
        future=True,
    )


def readonly_engine() -> Engine:
    """SELECT-only engine used by the agent's run_sql_query tool."""
    s = get_settings()
    return create_engine(
        _url(s.postgres_readonly_user, s.postgres_readonly_password),
        pool_pre_ping=True,
        future=True,
    )


def ping(engine: Engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False