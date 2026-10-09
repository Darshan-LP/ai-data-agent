from app.config import get_settings
from app.db import _url
from sqlalchemy import create_engine, text

s = get_settings()

# Connect to the existing PostgreSQL server as its administrator.
admin_url = _url("postgres", input("Enter PostgreSQL postgres password: "))
engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

try:
    with engine.connect() as conn:
        conn.execute(text("""
            SELECT pg_advisory_lock(842701)
        """))

        conn.execute(text("""
            CREATE ROLE app_admin LOGIN PASSWORD :password
        """), {"password": s.postgres_admin_password}) if not conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = 'app_admin'")
        ).scalar() else None

        conn.execute(text("""
            CREATE ROLE app_readonly LOGIN PASSWORD :password
        """), {"password": s.postgres_readonly_password}) if not conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = 'app_readonly'")
        ).scalar() else None

        exists = conn.execute(text(
            "SELECT 1 FROM pg_database WHERE datname = :name"
        ), {"name": s.postgres_db}).scalar()

        if not exists:
            conn.exec_driver_sql('CREATE DATABASE "ai_data_agent"')

        print("Database and application roles initialized.")
finally:
    engine.dispose()
