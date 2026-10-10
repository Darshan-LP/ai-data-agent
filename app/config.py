from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ai_data_agent"
    postgres_admin_user: str = "app_admin"
    postgres_admin_password: str = ""
    postgres_readonly_user: str = "app_readonly"
    postgres_readonly_password: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-5-nano"

    # App
    outputs_dir: str = "/app/outputs"
    max_agent_iterations: int = 6
    max_tokens_per_run: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()