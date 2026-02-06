from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class NormalizedMessage:
    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class NormalizedChatRequest:
    model: str
    messages: list[NormalizedMessage]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    seed: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    stream: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallFragment:
    id: str
    name: str
    arguments: str


@dataclass
class ProviderResponse:
    text: str
    tool_calls: list[dict[str, Any]]
    usage: dict[str, Any]
    raw: dict[str, Any]


TokenCallback = Callable[[str], Awaitable[None]]
TelemetryCallback = Callable[[str, dict[str, Any]], Awaitable[None]]
