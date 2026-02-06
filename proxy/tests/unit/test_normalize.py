from app.db.models import ConnectionType
from app.providers.normalize import provider_mode


def test_provider_mode_mapping() -> None:
    assert provider_mode(ConnectionType.OLLAMA) == 'ollama'
    assert provider_mode(ConnectionType.OPENAI_COMPAT) == 'openai_compat'
    assert provider_mode(ConnectionType.LLAMACPP_OPENAI) == 'openai_compat'
    assert provider_mode(ConnectionType.CUSTOM) == 'openai_compat'
