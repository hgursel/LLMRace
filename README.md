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

Add these connections in Garage and test them before creating cars.

## UI proxy target

- UI reads proxy base URL from `VITE_PROXY_BASE_URL`.
- Default is same-origin (`/api`) through Nginx reverse proxy.
- In Docker, browser access works at `http://127.0.0.1:3000` with backend CORS policy allowing localhost/127.0.0.1 origins.

## Secrets and API keys

API keys are **not stored in plaintext** in SQLite.
- Store only env var names in the app (for example `LMSTUDIO_API_KEY`).
- Set env vars on `llmrace-proxy` in `docker-compose.yml`.

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

## Troubleshooting

- No models discovered:
  - Ensure the host model server is running.
  - Verify base URL and port are correct.
  - In **Connections**, run **Test** first and check the inline status card (`ONLINE`/`OFFLINE`).
  - If you see connection failures from Docker, use `http://host.docker.internal:<port>` instead of `localhost`.
  - Use manual model name entry if discovery fails.
- Stream disconnects:
  - Re-open Race page; SSE replay resumes from persisted event sequence.
- CORS issues:
  - Use UI at `127.0.0.1:3000` so browser calls remain same-origin via Nginx reverse proxy.
