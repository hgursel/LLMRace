from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LLMRace Proxy"
    database_url: str = "sqlite:////data/llmrace.db"
    ollama_default_url: str = "http://host.docker.internal:11434"
    openai_default_url: str = "https://api.openai.com"
    anthropic_default_url: str = "https://api.anthropic.com"
    openrouter_default_url: str = "https://openrouter.ai"
    openai_compat_default_url: str = "http://host.docker.internal:1234"
    llamacpp_default_url: str = "http://host.docker.internal:8080"
    custom_default_url: str = "http://host.docker.internal:1234"
    openrouter_http_referer: str | None = None
    openrouter_x_title: str | None = "LLMRace"
    telemetry_poll_interval_seconds: float = 0.4
    telemetry_heartbeat_seconds: float = 10.0
    tool_loop_limit: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
