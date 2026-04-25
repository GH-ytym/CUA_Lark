"""Application settings for API, security, and execution behavior."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CUA-Lark"
    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"

    frontend_origin: str = "http://127.0.0.1:5173"

    event_backend: str = "memory"
    redis_url: str = "redis://127.0.0.1:6379/0"

    lark_cli_timeout_seconds: int = 20
    cua_max_steps: int = 20

    minimax_api_key: str = ""
    minimax_chat_url: str = "https://api.minimax.chat/v1/chat/completions"
    minimax_model: str = "MiniMax-M2.5"
    minimax_timeout_seconds: int = 20


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached settings object."""
    return Settings()
