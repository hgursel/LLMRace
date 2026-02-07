from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.security import decrypt_secret
from app.core.settings import Settings, get_settings
from app.db.models import Connection, ConnectionType
from app.providers.normalize import provider_mode
from app.providers.types import NormalizedChatRequest, ProviderResponse, TelemetryCallback, TokenCallback


class ProviderClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

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

                path = self._models_path(connection)
                resp = await client.get(f"{connection.base_url.rstrip('/')}{path}", headers=headers)
                resp.raise_for_status()
                payload = resp.json()
                return self._extract_model_ids(payload)
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

    async def verify_runtime(self, connection: Connection, timeout_ms: int = 8000) -> dict[str, Any]:
        api_key, auth_source = self._resolve_api_key(connection)
        ok, latency_ms, models, error = await self.test_connection(connection, timeout_ms=timeout_ms)
        hints = self._runtime_hints(connection, auth_source, error)
        return {
            "connection_id": connection.id,
            "provider_type": connection.type,
            "base_url": connection.base_url,
            "auth_source": auth_source,
            "auth_present": bool(api_key),
            "discovery_ok": ok,
            "latency_ms": latency_ms,
            "models": models,
            "error": error,
            "hints": hints,
        }

    async def generate(
        self,
        connection: Connection,
        request: NormalizedChatRequest,
        timeout_ms: int,
        on_token: TokenCallback,
        on_telemetry: TelemetryCallback | None = None,
    ) -> ProviderResponse:
        try:
            mode = provider_mode(connection.type)
            if mode == "ollama":
                return await self._generate_ollama(connection, request, timeout_ms, on_token)
            if mode == "anthropic":
                return await self._generate_anthropic(connection, request, timeout_ms, on_token)
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
                f"{connection.base_url.rstrip('/')}{self._chat_completions_path(connection)}",
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

    async def _generate_anthropic(
        self,
        connection: Connection,
        request: NormalizedChatRequest,
        timeout_ms: int,
        on_token: TokenCallback,
    ) -> ProviderResponse:
        headers = self._headers_for(connection)
        system_messages: list[str] = []
        messages: list[dict[str, Any]] = []
        for msg in request.messages:
            if msg.role == "system":
                system_messages.append(msg.content)
                continue
            if msg.role not in {"user", "assistant"}:
                messages.append({"role": "user", "content": msg.content})
                continue
            messages.append({"role": msg.role, "content": msg.content})

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "stream": True,
            "max_tokens": request.max_tokens or 1024,
            "temperature": request.temperature,
            "top_p": request.top_p,
        }
        if system_messages:
            payload["system"] = "\n\n".join(system_messages)
        payload = {k: v for k, v in payload.items() if v is not None}

        timeout = timeout_ms / 1000.0
        text_chunks: list[str] = []
        raw_chunks: list[dict[str, Any]] = []
        usage: dict[str, Any] = {}
        current_event = ""

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{connection.base_url.rstrip('/')}/v1/messages",
                headers=headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    raw_chunks.append({"event": current_event, "data": chunk})

                    if current_event == "message_delta":
                        delta_usage = chunk.get("usage") or {}
                        if delta_usage.get("output_tokens") is not None:
                            usage["completion_tokens"] = delta_usage.get("output_tokens")
                            usage["estimated"] = False

                    if current_event == "content_block_delta":
                        text = (chunk.get("delta") or {}).get("text")
                        if text:
                            text_chunks.append(text)
                            await on_token(text)

        text = "".join(text_chunks)
        if not usage:
            usage = {"completion_tokens": max(1, len(text.split()) // 1), "estimated": True}

        return ProviderResponse(
            text=text,
            tool_calls=[],
            usage=usage,
            raw={"chunks": raw_chunks, "provider": "anthropic"},
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

    def _resolve_api_key(self, connection: Connection) -> tuple[str | None, str]:
        encrypted_value = getattr(connection, "api_key_encrypted", None)
        if encrypted_value:
            decrypted = decrypt_secret(encrypted_value)
            if decrypted:
                return decrypted, "encrypted_db"
        env_var = getattr(connection, "api_key_env_var", None)
        if env_var:
            env_value = os.getenv(env_var)
            if env_value:
                return env_value, "env_var"
        return None, "none"

    def _headers_for(self, connection: Connection) -> dict[str, str]:
        headers: dict[str, str] = {}
        api_key, _source = self._resolve_api_key(connection)

        if connection.type == ConnectionType.ANTHROPIC:
            if api_key:
                headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
            return headers

        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        if connection.type in {ConnectionType.OPENAI_COMPAT, ConnectionType.LLAMACPP_OPENAI, ConnectionType.CUSTOM} and api_key:
            headers["X-API-Key"] = api_key
            headers["api-key"] = api_key

        if connection.type == ConnectionType.OPENROUTER:
            if self.settings.openrouter_http_referer:
                headers["HTTP-Referer"] = self.settings.openrouter_http_referer
            if self.settings.openrouter_x_title:
                headers["X-Title"] = self.settings.openrouter_x_title

        return headers

    def _models_path(self, connection: Connection) -> str:
        if connection.type == ConnectionType.OPENROUTER:
            return "/api/v1/models"
        return "/v1/models"

    def _chat_completions_path(self, connection: Connection) -> str:
        if connection.type == ConnectionType.OPENROUTER:
            return "/api/v1/chat/completions"
        return "/v1/chat/completions"

    def _extract_model_ids(self, payload: dict[str, Any]) -> list[str]:
        data = payload.get("data")
        if isinstance(data, list):
            ids: list[str] = []
            for item in data:
                if isinstance(item, dict):
                    model_id = item.get("id")
                    if isinstance(model_id, str) and model_id:
                        ids.append(model_id)
            return ids
        return []

    def _format_connection_error(self, action: str, connection: Connection, exc: Exception) -> str:
        base_url = str(getattr(connection, "base_url", "") or "")
        raw_provider = getattr(connection, "type", "UNKNOWN")
        provider = str(getattr(raw_provider, "value", raw_provider))
        status_code: int | None = None
        response_body = ""
        details = str(exc)

        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            try:
                response_body = (exc.response.text or "").strip()
            except Exception:  # noqa: BLE001
                response_body = ""
            details = f"HTTP {status_code}"
            if response_body:
                details = f"{details} response={response_body[:220]}"

        message = f"{action} failed for {provider} endpoint {base_url}: {details}"
        hints = [
            self._docker_localhost_hint(base_url),
            self._windows_host_hint(base_url, details),
            self._jan_trusted_host_hint(status_code, response_body),
            self._api_key_hint(connection, status_code),
        ]
        hints = [hint for hint in hints if hint]
        if hints:
            message = f"{message} {' '.join(hints)}"
        return message

    def _runtime_hints(self, connection: Connection, auth_source: str, error: str | None) -> list[str]:
        hints: list[str] = []
        if auth_source == "none" and connection.type in {
            ConnectionType.OPENAI,
            ConnectionType.ANTHROPIC,
            ConnectionType.OPENROUTER,
            ConnectionType.LLAMACPP_OPENAI,
            ConnectionType.OPENAI_COMPAT,
        }:
            hints.append("No API key resolved. Save API key in connection wizard.")
        if auth_source == "env_var":
            hints.append("Legacy env-var auth detected. Save API key in connection wizard to avoid host env drift.")
        if error:
            lowered = error.lower()
            if "invalid host header" in lowered:
                hints.append("Jan trusted-hosts check failed. Allow host.docker.internal in Jan Local API Server.")
            if "host.docker.internal" in connection.base_url and ("connecterror" in lowered or "all connection attempts failed" in lowered):
                hints.append("Windows tip: restart Docker Desktop and verify host.docker.internal resolves from containers.")
            if "401" in lowered or "unauthorized" in lowered:
                hints.append("Auth rejected by provider. Re-save API key in connection wizard.")
        return hints

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

    def _windows_host_hint(self, base_url: str, details: str) -> str:
        if "host.docker.internal" not in base_url:
            return ""
        lowered = details.lower()
        if "connecterror" in lowered or "all connection attempts failed" in lowered:
            return (
                "Windows tip: for Docker Desktop use host.docker.internal and restart containers with "
                "`docker compose up -d --force-recreate` after network or .env changes."
            )
        return ""

    def _jan_trusted_host_hint(self, status_code: int | None, response_body: str) -> str:
        if status_code != 403:
            return ""
        text = (response_body or "").lower()
        if "invalid host header" in text:
            return (
                "Tip: Jan Local API Server rejected the host header. "
                "In Jan > Settings > Local API Server, set Trusted Hosts to "
                "host.docker.internal,localhost,127.0.0.1."
            )
        return ""

    def _api_key_hint(self, connection: Connection, status_code: int | None) -> str:
        if status_code != 401:
            return ""
        _api_key, source = self._resolve_api_key(connection)
        if source == "none":
            return "Tip: endpoint requires API auth. Save API key in the connection wizard."
        if source == "env_var":
            return "Tip: using legacy env-var auth. Prefer stored encrypted key in connection wizard."
        return "Tip: stored API key exists. Verify the key value and provider account scope."

    def _to_openai_message(self, msg: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": msg.role}
        if msg.role == "tool":
            payload["tool_call_id"] = msg.tool_call_id
            payload["name"] = msg.name
        payload["content"] = msg.content
        return payload

    def _to_ollama_message(self, msg: Any) -> dict[str, Any]:
        return {"role": msg.role, "content": msg.content}
