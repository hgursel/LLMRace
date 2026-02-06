from __future__ import annotations

from app.db.models import Car, Connection, ConnectionType, TestCase
from app.providers.types import NormalizedChatRequest, NormalizedMessage


def build_messages(test_case: TestCase) -> list[NormalizedMessage]:
    messages: list[NormalizedMessage] = []
    if test_case.system_prompt:
        messages.append(NormalizedMessage(role="system", content=test_case.system_prompt))
    messages.append(NormalizedMessage(role="user", content=test_case.user_prompt))
    return messages


def build_request(connection: Connection, car: Car, test_case: TestCase) -> NormalizedChatRequest:
    return NormalizedChatRequest(
        model=car.model_name,
        messages=build_messages(test_case),
        temperature=car.temperature,
        top_p=car.top_p,
        max_tokens=car.max_tokens,
        stop=car.stop_json,
        seed=car.seed,
        tools=test_case.tools_schema_json,
        stream=True,
        metadata={
            "connection_type": connection.type.value,
            "connection_id": connection.id,
            "car_id": car.id,
            "test_id": test_case.id,
        },
    )


def provider_mode(connection_type: ConnectionType) -> str:
    if connection_type == ConnectionType.OLLAMA:
        return "ollama"
    return "openai_compat"
