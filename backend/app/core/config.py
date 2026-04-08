from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="Simple Task Management", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")

    secret_key: str = Field(alias="SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=60, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    database_url: str = Field(alias="DATABASE_URL")

    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_default_model: str = Field(default="qwen2.5:1.5b", alias="OLLAMA_DEFAULT_MODEL")
    ai_default_timeout_seconds: int = Field(default=8, alias="AI_DEFAULT_TIMEOUT_SECONDS")
    session_idle_timeout_minutes: int = Field(default=15, alias="SESSION_IDLE_TIMEOUT_MINUTES", ge=1)

    initial_admin_email: str = Field(default="admin@example.com", alias="INITIAL_ADMIN_EMAIL")
    initial_admin_password: str = Field(default="admin1234", alias="INITIAL_ADMIN_PASSWORD")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
