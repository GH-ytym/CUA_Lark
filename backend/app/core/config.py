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

    lark_cli_path: str = "lark-cli"
    lark_cli_timeout_seconds: int = 20
    lark_cli_workdir: str = ""
    cua_max_steps: int = 20

    dashscope_api_key: str = ""
    qwen_chat_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    qwen_model: str = "qwen3.6-max-preview"
    qwen_timeout_seconds: int = 20
    qwen_intent_timeout_seconds: int = 20
    intent_require_llm: bool = False
    recipient_sqlite_path: str = "data/lark_recipients.db"
    recipient_resolver_top_k: int = 12
    recipient_resolver_high_confidence: float = 0.90
    recipient_resolver_min_confidence: float = 0.70
    recipient_resolver_ambiguity_gap: float = 0.15


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached settings object."""
    return Settings()
