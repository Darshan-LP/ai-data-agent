
"""Initialize the local PostgreSQL database and application roles."""

from getpass import getpass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from app.config import get_settings


def main() -> None:
    settings = get_settings()

    postgres_password = getpass("Enter PostgreSQL postgres password: ")

    admin_url = URL.create(
        drivername="postgresql+psycopg",
        username="postgres",
        password=postgres_password,
        host=settings.postgres_host,
        port=settings.postgres_port,
        database="postgres",
    )

    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        with engine.connect() as conn:
            roles = {
                "app_admin": settings.postgres_admin_password,
                "app_readonly": settings.postgres_readonly_password,
            }

            for role_name, role_password in roles.items():
                exists = conn.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :name"),
                    {"name": role_name},
                ).scalar()

                if not exists:
                    create_role_sql = conn.execute(
                        text(
                            "SELECT format("
                            "'CREATE ROLE %I LOGIN PASSWORD %L', "
                            ":role_name, :role_password)"
                        ),
                        {
                            "role_name": role_name,
                            "role_password": role_password,
                        },
                    ).scalar_one()

                    conn.exec_driver_sql(create_role_sql)

            database_exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": settings.postgres_db},
            ).scalar()

            if not database_exists:
                database_sql = conn.execute(
                    text("SELECT format('CREATE DATABASE %I', :name)"),
                    {"name": settings.postgres_db},
                ).scalar_one()

                conn.exec_driver_sql(database_sql)

        print("Database and application roles initialized.")

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()