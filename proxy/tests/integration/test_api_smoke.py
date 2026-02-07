from __future__ import annotations

import time
from typing import Any

from app.providers.adapters import ProviderClient
from app.providers.types import ProviderResponse


async def fake_discover_models(self: ProviderClient, connection: Any, timeout_ms: int = 8000) -> list[str]:
    return ['demo-model', 'judge-model']


async def fake_generate(
    self: ProviderClient,
    connection: Any,
    request: Any,
    timeout_ms: int,
    on_token: Any,
    on_telemetry: Any = None,
) -> ProviderResponse:
    if request.metadata.get('judge'):
        text = '{"writing_score":8,"coding_score":7,"tool_score":9,"overall":8,"rationale":"Consistent output."}'
        await on_token(text)
        return ProviderResponse(text=text, tool_calls=[], usage={'completion_tokens': 24}, raw={'mock': True})

    text = f"model={request.model} prompt_ok"
    await on_token(text)
    if on_telemetry:
        await on_telemetry('tool.call.detected', {'count': 0})
    return ProviderResponse(text=text, tool_calls=[], usage={'completion_tokens': 6}, raw={'mock': True})


def _wait_for_run_completion(client: Any, run_id: int, timeout_seconds: int = 8) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f'/api/runs/{run_id}')
        payload = response.json()
        if payload['run']['status'] in ('COMPLETED', 'FAILED'):
            return payload
        time.sleep(0.2)
    raise AssertionError('Run did not complete in time')


def test_connection_suite_seed_and_models(client: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(ProviderClient, 'discover_models', fake_discover_models)

    health = client.get('/api/health')
    assert health.status_code == 200
    assert health.json()['status'] == 'ok'

    create = client.post(
        '/api/connections',
        json={
            'name': 'Ollama Local',
            'type': 'OLLAMA',
            'base_url': 'http://host.docker.internal:11434',
            'api_key_env_var': None,
        },
    )
    assert create.status_code == 200
    connection_id = create.json()['id']

    models = client.get(f'/api/connections/{connection_id}/models')
    assert models.status_code == 200
    assert 'demo-model' in models.json()

    runtime = client.post(f'/api/connections/{connection_id}/verify-runtime')
    assert runtime.status_code == 200
    assert runtime.json()['connection_id'] == connection_id
    assert runtime.json()['discovery_ok'] is True

    suites = client.get('/api/suites')
    assert suites.status_code == 200
    suite_data = suites.json()
    assert len(suite_data) >= 3
    assert sum(len(s['tests']) for s in suite_data) >= 12


def test_run_stream_judge_and_leaderboard(client: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(ProviderClient, 'discover_models', fake_discover_models)
    monkeypatch.setattr(ProviderClient, 'generate', fake_generate)

    conn_resp = client.post(
        '/api/connections',
        json={
            'name': 'LM Studio',
            'type': 'OPENAI_COMPAT',
            'base_url': 'http://host.docker.internal:1234',
            'api_key_env_var': None,
        },
    )
    connection_id = conn_resp.json()['id']

    car_resp = client.post(
        '/api/cars',
        json={
            'name': 'Turbo Car',
            'connection_id': connection_id,
            'model_name': 'demo-model',
            'temperature': 0.2,
            'top_p': 1,
        },
    )
    car_id = car_resp.json()['id']

    suites = client.get('/api/suites').json()
    writing = next(s for s in suites if s['name'] == 'Writing Basic')

    start = client.post('/api/runs/start', json={'suite_id': writing['id'], 'car_ids': [car_id], 'judge_car_id': car_id})
    assert start.status_code == 200
    run_id = start.json()['run_id']

    run_payload = _wait_for_run_completion(client, run_id)
    assert run_payload['run']['status'] == 'COMPLETED'
    assert len(run_payload['items']) == len(writing['tests'])

    stream = client.get(f'/api/runs/{run_id}/stream?after_seq=0')
    assert stream.status_code == 200
    assert 'event: run.started' in stream.text
    assert 'event: run.completed' in stream.text

    judge = client.post(f'/api/runs/{run_id}/judge', json={'judge_car_id': car_id})
    assert judge.status_code == 200
    assert judge.json()['item_scores'] > 0

    leaderboard = client.get('/api/leaderboard')
    assert leaderboard.status_code == 200
    rows = leaderboard.json()['rows']
    assert len(rows) >= 1
    assert rows[0]['avg_latency_ms'] is not None
    assert 'avg_assertion_pass_rate' in rows[0]
    assert 'items_total' in rows[0]

    scorecard = client.get(f'/api/runs/{run_id}/scorecard')
    assert scorecard.status_code == 200
    scorecard_rows = scorecard.json()['rows']
    assert len(scorecard_rows) >= 1
    assert scorecard_rows[0]['items_total'] >= 1

    start_2 = client.post('/api/runs/start', json={'suite_id': writing['id'], 'car_ids': [car_id], 'judge_car_id': car_id})
    assert start_2.status_code == 200
    run_id_2 = start_2.json()['run_id']
    _wait_for_run_completion(client, run_id_2)

    compare = client.get(f'/api/runs/{run_id_2}/compare?baseline_run_id={run_id}')
    assert compare.status_code == 200
    compare_rows = compare.json()['rows']
    assert len(compare_rows) >= 1
    assert compare_rows[0]['summary'] in {'improved', 'regressed', 'mixed', 'new profile in current run'}
