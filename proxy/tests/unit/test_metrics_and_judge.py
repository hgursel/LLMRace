from app.runs.judge import parse_judge_json
from app.runs.metrics import compute_metrics


def test_compute_metrics_estimated_tokens() -> None:
    metrics = compute_metrics(
        started_ms=100,
        finished_ms=1200,
        ttft_ms=200,
        output_text='hello world from llm',
        usage_completion_tokens=None,
        usage_estimated=False,
    )
    assert metrics.total_latency_ms == 1100
    assert metrics.generation_ms == 900
    assert metrics.output_tokens > 0
    assert metrics.output_tokens_estimated is True
    assert metrics.tokens_per_sec is not None


def test_parse_judge_json() -> None:
    payload = parse_judge_json('{"writing_score":8,"coding_score":7,"tool_score":9,"overall":8,"rationale":"Solid"}')
    assert payload['overall'] == 8
    assert payload['rationale'] == 'Solid'
