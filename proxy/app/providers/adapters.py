from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

import httpx

from app.db.models import Connection, ConnectionType
from app.providers.normalize import provider_mode
from app.providers.types import NormalizedChatRequest, ProviderResponse, TelemetryCallback, TokenCallback


class ProviderClient:
    async def discover_models(self, connection: Connection, timeout_ms: int = 8000) -> list[str]:
        timeout = timeout_ms / 1000.0
        headers = self._headers_for(connection)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if connection.type == ConnectionType.OLLAMA:
                    resp = await client.get(f"{connection.base_url.rstrip('/')}/api/tags", headers=headers)
                    resp.raise_for_status()
                    payload = resp.json()
                    return [m.get("name", "") for m in payload.get("models", []) if m.get("name")]

                resp = await client.get(f"{connection.base_url.rstrip('/')}/v1/models", headers=headers)
                resp.raise_for_status()
                payload = resp.json()
                return [m.get("id", "") for m in payload.get("data", []) if m.get("id")]
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(self._format_connection_error("Model discovery", connection, exc)) from exc

    async def test_connection(self, connection: Connection, timeout_ms: int = 8000) -> tuple[bool, int | None, list[str], str | None]:
        started = time.perf_counter()
        try:
            models = await self.discover_models(connection, timeout_ms=timeout_ms)
            latency_ms = int((time.perf_counter() - started) * 1000)
            return True, latency_ms, models, None
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.perf_counter() - started) * 1000)
            return False, latency_ms, [], str(exc)

    async def generate(
        self,
        connection: Connection,
        request: NormalizedChatRequest,
        timeout_ms: int,
        on_token: TokenCallback,
        on_telemetry: TelemetryCallback | None = None,
    ) -> ProviderResponse:
        try:
            if provider_mode(connection.type) == "ollama":
                return await self._generate_ollama(connection, request, timeout_ms, on_token)
            return await self._generate_openai_compat(connection, request, timeout_ms, on_token, on_telemetry)
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(self._format_connection_error("Generation", connection, exc)) from exc

    async def _generate_openai_compat(
        self,
        connection: Connection,
        request: NormalizedChatRequest,
        timeout_ms: int,
        on_token: TokenCallback,
        on_telemetry: TelemetryCallback | None,
    ) -> ProviderResponse:
        headers = self._headers_for(connection)
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [self._to_openai_message(msg) for msg in request.messages],
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
            "seed": request.seed,
            "stop": request.stop,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        if request.tools:
            payload["tools"] = request.tools
        if request.tool_choice is not None:
            payload["tool_choice"] = request.tool_choice

        timeout = timeout_ms / 1000.0
        text_chunks: list[str] = []
        raw_chunks: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        tool_fragments: dict[int, dict[str, str]] = defaultdict(lambda: {"id": "", "name": "", "arguments": ""})

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{connection.base_url.rstrip('/')}/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()

                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    raw_chunks.append(chunk)

                    if chunk.get("usage"):
                        usage = chunk["usage"]

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        text_chunks.append(content)
                        await on_token(content)

                    for tc in delta.get("tool_calls", []) or []:
                        idx = tc.get("index", 0)
                        fragment = tool_fragments[idx]
                        fragment["id"] = tc.get("id") or fragment["id"]
                        func = tc.get("function", {})
                        fragment["name"] = func.get("name") or fragment["name"]
                        fragment["arguments"] += func.get("arguments") or ""

        tool_calls = []
        for fragment in tool_fragments.values():
            if not fragment["name"]:
                continue
            try:
                parsed_args = json.loads(fragment["arguments"] or "{}")
            except json.JSONDecodeError:
                parsed_args = {"raw": fragment["arguments"]}
            tool_calls.append(
                {
                    "id": fragment["id"] or f"call_{len(tool_calls) + 1}",
                    "name": fragment["name"],
                    "arguments": parsed_args,
                }
            )

        if tool_calls and on_telemetry:
            await on_telemetry("tool.call.detected", {"count": len(tool_calls), "tool_calls": tool_calls})

        text = "".join(text_chunks)
        if not usage:
            usage = {"completion_tokens": max(1, len(text.split()) // 1), "estimated": True}

        return ProviderResponse(
            text=text,
            tool_calls=tool_calls,
            usage=usage,
            raw={"chunks": raw_chunks, "provider": "openai_compat"},
        )

    async def _generate_ollama(
        self,
        connection: Connection,
        request: NormalizedChatRequest,
        timeout_ms: int,
        on_token: TokenCallback,
    ) -> ProviderResponse:
        headers = self._headers_for(connection)
        payload: dict[str, Any] = {
            "model": request.model,
            "stream": True,
            "messages": [self._to_ollama_message(msg) for msg in request.messages],
            "options": {
                "temperature": request.temperature,
                "top_p": request.top_p,
                "num_predict": request.max_tokens,
                "seed": request.seed,
            },
        }
        payload["options"] = {k: v for k, v in payload["options"].items() if v is not None}
        if request.tools:
            payload["tools"] = request.tools

        timeout = timeout_ms / 1000.0
        text_chunks: list[str] = []
        raw_chunks: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        tool_calls: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{connection.base_url.rstrip('/')}/api/chat",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    raw_chunks.append(chunk)

                    message = chunk.get("message", {})
                    content = message.get("content")
                    if content:
                        text_chunks.append(content)
                        await on_token(content)

                    for tool in message.get("tool_calls", []) or []:
                        fn = tool.get("function", {})
                        tool_calls.append(
                            {
                                "id": tool.get("id", f"call_{len(tool_calls) + 1}"),
                                "name": fn.get("name", "unknown_tool"),
                                "arguments": fn.get("arguments", {}),
                            }
                        )

                    if chunk.get("done"):
                        usage = {
                            "completion_tokens": chunk.get("eval_count") or max(1, len("".join(text_chunks).split())),
                            "prompt_tokens": chunk.get("prompt_eval_count"),
                            "estimated": chunk.get("eval_count") is None,
                        }

        return ProviderResponse(
            text="".join(text_chunks),
            tool_calls=tool_calls,
            usage=usage,
            raw={"chunks": raw_chunks, "provider": "ollama"},
        )

    def _headers_for(self, connection: Connection) -> dict[str, str]:
        headers: dict[str, str] = {}
        if connection.api_key_env_var:
            api_key = os.getenv(connection.api_key_env_var)
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _format_connection_error(self, action: str, connection: Connection, exc: Exception) -> str:
        base_url = str(getattr(connection, "base_url", "") or "")
        raw_provider = getattr(connection, "type", "UNKNOWN")
        provider = str(getattr(raw_provider, "value", raw_provider))
        message = f"{action} failed for {provider} endpoint {base_url}: {exc}"
        hint = self._docker_localhost_hint(base_url)
        if hint:
            message = f"{message} {hint}"
        return message

    def _docker_localhost_hint(self, base_url: str) -> str:
        if not base_url:
            return ""
        try:
            host = urlparse(base_url).hostname
        except Exception:  # noqa: BLE001
            return ""
        if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
            return "Tip: proxy runs in Docker. For host services, use http://host.docker.internal:<port>."
        return ""

    def _to_openai_message(self, msg: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": msg.role}
        if msg.role == "tool":
            payload["tool_call_id"] = msg.tool_call_id
            payload["name"] = msg.name
        payload["content"] = msg.content
        return payload

    def _to_ollama_message(self, msg: Any) -> dict[str, Any]:
        return {"role": msg.role, "content": msg.content}
