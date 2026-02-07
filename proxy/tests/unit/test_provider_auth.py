from types import SimpleNamespace

from app.core.security import encrypt_secret
from app.core.settings import Settings
from app.db.models import ConnectionType
from app.providers.adapters import ProviderClient


def _conn(
    connection_type: ConnectionType,
    *,
    api_key_encrypted: str | None = None,
    api_key_env_var: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        type=connection_type,
        base_url="https://example.com",
        api_key_encrypted=api_key_encrypted,
        api_key_env_var=api_key_env_var,
    )


def test_encrypted_key_takes_priority_over_env(monkeypatch: object) -> None:
    monkeypatch.setenv("LEGACY_KEY", "from-env")
    connection = _conn(
        ConnectionType.OPENAI,
        api_key_encrypted=encrypt_secret("from-db"),
        api_key_env_var="LEGACY_KEY",
    )
    headers = ProviderClient()._headers_for(connection)  # noqa: SLF001
    assert headers["Authorization"] == "Bearer from-db"


def test_anthropic_headers_are_native() -> None:
    connection = _conn(
        ConnectionType.ANTHROPIC,
        api_key_encrypted=encrypt_secret("anthropic-key"),
    )
    headers = ProviderClient()._headers_for(connection)  # noqa: SLF001
    assert headers["x-api-key"] == "anthropic-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in headers


def test_openrouter_optional_headers() -> None:
    settings = Settings(openrouter_http_referer="https://example.app", openrouter_x_title="LLMRace Tests")
    connection = _conn(
        ConnectionType.OPENROUTER,
        api_key_encrypted=encrypt_secret("openrouter-key"),
    )
    headers = ProviderClient(settings=settings)._headers_for(connection)  # noqa: SLF001
    assert headers["Authorization"] == "Bearer openrouter-key"
    assert headers["HTTP-Referer"] == "https://example.app"
    assert headers["X-Title"] == "LLMRace Tests"
