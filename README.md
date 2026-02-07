# LLMRace

LLMRace is a retro neon arcade webapp for benchmarking local LLMs. It includes:
- `llmrace-proxy` (FastAPI + SQLite + SSE)
- `llmrace-ui` (Vite Vanilla TS + Nginx reverse proxy)

Designed for iterative eval workflows:
- create/import/export custom suites in JSON
- stream full run telemetry and inspect per-item outputs
- compare model profiles on latency/error/check-pass/judge metrics
- inspect per-run scorecards and baseline regression deltas
- tune provider timeout/retry/concurrency settings

## Quickstart

```bash
docker compose up --build
```

Open:
- UI: http://127.0.0.1:3000
- Proxy health: http://127.0.0.1:8000/api/health

## Local model endpoints

By default the proxy can connect to model servers on your host machine using `host.docker.internal`:
- Ollama: `http://host.docker.internal:11434`
- LM Studio (OpenAI-compatible): `http://host.docker.internal:1234`
- llama.cpp server (OpenAI-compatible preferred): `http://host.docker.internal:8080`
- Jan Local API Server (OpenAI-compatible): `http://host.docker.internal:1337`
- OpenAI: `https://api.openai.com`
- Anthropic: `https://api.anthropic.com`
- OpenRouter: `https://openrouter.ai`

Add these connections in Garage and test them before creating cars.

## UI proxy target

- UI reads proxy base URL from `VITE_PROXY_BASE_URL`.
- Default is same-origin (`/api`) through Nginx reverse proxy.
- In Docker, browser access works at `http://127.0.0.1:3000` with backend CORS policy allowing localhost/127.0.0.1 origins.

## Secrets and API keys

API keys are **not stored in plaintext** in SQLite.
- Enter API key directly in Connections form; proxy encrypts before storing.
- `LLMRACE_SECRET_KEY` controls encryption key derivation (set this in production).
- Legacy env-var auth still works for old connections, but direct encrypted storage is recommended.
- Optional passthrough env vars remain in compose: `JAN_API_KEY`, `LMSTUDIO_API_KEY`, `LLAMACPP_API_KEY`, `OPENAI_API_KEY`.

## Streaming and telemetry

Race execution is sequential by test and selected car.
Telemetry stream (`/api/runs/{id}/stream`) includes:
- request start
- TTFT
- token deltas
- tool calls and execution
- errors/retries
- final metrics and completion events

## Core workflow

1. Add one or more connections.
2. Add model profiles.
3. Build or import suites in **Suites > Suite JSON Editor**.
4. Run selected suite against selected model profiles.
5. Inspect run details in **Run History > Inspect** and export run JSON.
6. Use **Run Scorecard** + **Baseline Comparison** in Run History to track regressions.
7. Optionally run manual judge and compare on **Comparison**.

## Suite JSON format

Use this shape in Suite JSON Editor:

```json
{
  "name": "My Regression Suite",
  "category": "custom",
  "description": "Daily regression checks",
  "tests": [
    {
      "order_index": 1,
      "name": "Output format",
      "system_prompt": "You are precise.",
      "user_prompt": "Return a JSON object with fields id and status.",
      "expected_constraints": "Must be valid JSON.",
      "tools_schema_json": null
    }
  ]
}
```

`expected_constraints` supports optional deterministic checks with this syntax (newline or `;` separated):
- `contains:<text>`
- `icontains:<text>`
- `not_contains:<text>`
- `regex:<pattern>`
- `max_words:<number>`

Example:

```text
contains:JSON
regex:^\\{
max_words:120
```

## Data persistence

SQLite DB is stored in Docker volume `llmrace_data` at `/data/llmrace.db`.
Run history, outputs, tool calls, judge results, and metrics persist across restarts.

## Example presets

- **Ollama**
  - Type: `OLLAMA`
  - Base URL: `http://host.docker.internal:11434`
- **LM Studio**
  - Type: `OPENAI_COMPAT`
  - Base URL: `http://host.docker.internal:1234`
- **llama.cpp**
  - Type: `LLAMACPP_OPENAI`
  - Base URL: `http://host.docker.internal:8080`
- **Jan (llama.cpp backend)**
  - Type: `LLAMACPP_OPENAI` (or `OPENAI_COMPAT`)
  - Base URL: `http://host.docker.internal:1337`
  - API Key Env Var: `JAN_API_KEY`
  - Jan app settings:
    - Server Host: `127.0.0.1` or `0.0.0.0`
    - Server Port: `1337`
    - API Prefix: `/v1`
    - Trusted Hosts: `host.docker.internal,localhost,127.0.0.1`
- **OpenAI**
  - Type: `OPENAI`
  - Base URL: `https://api.openai.com`
  - API key: enter in connection form (stored encrypted)
- **Anthropic**
  - Type: `ANTHROPIC`
  - Base URL: `https://api.anthropic.com`
  - API key: enter in connection form (stored encrypted)
- **OpenRouter**
  - Type: `OPENROUTER`
  - Base URL: `https://openrouter.ai`
  - API key: enter in connection form (stored encrypted)
  - Optional headers via env: `OPENROUTER_HTTP_REFERER`, `OPENROUTER_X_TITLE`

## Jan quick verify

From inside proxy container:

```bash
docker compose exec -T llmrace-proxy python - <<'PY'
import os, httpx
key = os.getenv("JAN_API_KEY", "")
r = httpx.get(
    "http://host.docker.internal:1337/v1/models",
    headers={"Authorization": f"Bearer {key}", "X-API-Key": key},
    timeout=10,
)
print(r.status_code)
print(r.text[:300])
PY
```

Or use **Verify Runtime** button in Connections page for one-click diagnostics:
- resolved auth source (`encrypted_db` or legacy `env_var`)
- auth present/missing
- discovery status and model list
- provider-specific hints (Jan trusted hosts, Windows Docker Desktop hints)

## Troubleshooting

- No models discovered:
  - Ensure the host model server is running.
  - Verify base URL and port are correct.
  - In **Connections**, run **Test** first and check the inline status card (`ONLINE`/`OFFLINE`).
  - If you see connection failures from Docker, use `http://host.docker.internal:<port>` instead of `localhost`.
  - Use manual model name entry if discovery fails.
- `401 Unauthorized`:
  - Connection likely requires API key.
  - Re-save API key in the connection form (encrypted storage).
  - For legacy env-var connections, ensure variable exists in container.
- `403 Invalid host header` (common with Jan):
  - Jan rejected the container host header.
  - In Jan > Settings > Local API Server, set Trusted Hosts to:
    - `host.docker.internal,localhost,127.0.0.1`
- Windows + Docker Desktop:
  - After `.env` or network changes, recreate proxy:
    - `docker compose up -d --force-recreate llmrace-proxy`
  - Prefer `host.docker.internal` over `localhost` for host-run model servers.
- Stream disconnects:
  - Re-open Race page; SSE replay resumes from persisted event sequence.
- CORS issues:
  - Use UI at `127.0.0.1:3000` so browser calls remain same-origin via Nginx reverse proxy.
