from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MetricComputation:
    ttft_ms: int | None
    total_latency_ms: int
    generation_ms: int | None
    output_tokens: int
    output_tokens_estimated: bool
    tokens_per_sec: float | None


def estimate_tokens(text: str) -> int:
    # Simple heuristic for providers that do not return token usage.
    return max(1, int(len(text.split()) * 1.25))


def compute_metrics(
    started_ms: int,
    finished_ms: int,
    ttft_ms: int | None,
    output_text: str,
    usage_completion_tokens: int | None,
    usage_estimated: bool,
) -> MetricComputation:
    total_latency_ms = max(0, finished_ms - started_ms)
    generation_ms = None
    if ttft_ms is not None:
        generation_ms = max(1, total_latency_ms - ttft_ms)

    if usage_completion_tokens is None:
        output_tokens = estimate_tokens(output_text)
        output_tokens_estimated = True
    else:
        output_tokens = max(1, usage_completion_tokens)
        output_tokens_estimated = usage_estimated

    tokens_per_sec = None
    if generation_ms and generation_ms > 0:
        tokens_per_sec = output_tokens / (generation_ms / 1000)

    return MetricComputation(
        ttft_ms=ttft_ms,
        total_latency_ms=total_latency_ms,
        generation_ms=generation_ms,
        output_tokens=output_tokens,
        output_tokens_estimated=output_tokens_estimated,
        tokens_per_sec=tokens_per_sec,
    )
