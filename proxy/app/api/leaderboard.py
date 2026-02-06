from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Car, Connection, JudgeResult, Metric, Output, RunItem, RunItemStatus
from app.db.session import get_db
from app.schemas import LeaderboardResponse, LeaderboardRow

router = APIRouter(prefix="/api/leaderboard", tags=["leaderboard"])


@router.get("", response_model=LeaderboardResponse)
def leaderboard(db: Session = Depends(get_db)) -> LeaderboardResponse:
    stats: dict[int, dict[str, float | int]] = {}
    metrics_rows = db.execute(
        select(
            RunItem.id,
            RunItem.car_id,
            RunItem.status,
            Metric.ttft_ms,
            Metric.total_latency_ms,
            Metric.tokens_per_sec,
            Metric.error_flag,
        )
        .join(Metric, Metric.run_item_id == RunItem.id)
        .where(RunItem.car_id.is_not(None))
    ).all()

    for _, car_id, status, ttft_ms, latency_ms, tokens_per_sec, error_flag in metrics_rows:
        if car_id is None:
            continue
        row = stats.setdefault(
            int(car_id),
            {
                "items_total": 0,
                "items_failed": 0,
                "items_partial": 0,
                "error_count": 0,
                "ttft_sum": 0.0,
                "ttft_count": 0,
                "latency_sum": 0.0,
                "latency_count": 0,
                "tps_sum": 0.0,
                "tps_count": 0,
                "assertions_passed": 0,
                "assertions_total": 0,
            },
        )

        row["items_total"] += 1
        if status == RunItemStatus.FAILED:
            row["items_failed"] += 1
        if status == RunItemStatus.PARTIAL_TOOL_SUPPORT:
            row["items_partial"] += 1
        if error_flag:
            row["error_count"] += 1
        if ttft_ms is not None:
            row["ttft_sum"] += float(ttft_ms)
            row["ttft_count"] += 1
        if latency_ms is not None:
            row["latency_sum"] += float(latency_ms)
            row["latency_count"] += 1
        if tokens_per_sec is not None:
            row["tps_sum"] += float(tokens_per_sec)
            row["tps_count"] += 1

    judge_rows = db.execute(
        select(JudgeResult.car_id_nullable, JudgeResult.overall)
        .where(
            JudgeResult.car_id_nullable.is_not(None),
            JudgeResult.run_item_id_nullable.is_not(None),
        )
    ).all()
    judge_by_car: dict[int, list[float]] = {}
    for car_id, overall in judge_rows:
        if car_id is None or overall is None:
            continue
        judge_by_car.setdefault(int(car_id), []).append(float(overall))

    assertion_rows = db.execute(
        select(RunItem.car_id, Output.raw_provider_payload_json)
        .join(Output, Output.run_item_id == RunItem.id)
        .where(RunItem.car_id.is_not(None))
    ).all()
    for car_id, raw_payload in assertion_rows:
        if car_id is None:
            continue
        row = stats.setdefault(
            int(car_id),
            {
                "items_total": 0,
                "items_failed": 0,
                "items_partial": 0,
                "error_count": 0,
                "ttft_sum": 0.0,
                "ttft_count": 0,
                "latency_sum": 0.0,
                "latency_count": 0,
                "tps_sum": 0.0,
                "tps_count": 0,
                "assertions_passed": 0,
                "assertions_total": 0,
            },
        )
        payload = raw_payload or {}
        assertions = payload.get("assertions") if isinstance(payload, dict) else None
        if isinstance(assertions, dict):
            total = assertions.get("total")
            passed = assertions.get("passed")
            if isinstance(total, int) and isinstance(passed, int) and total > 0:
                row["assertions_total"] += total
                row["assertions_passed"] += passed

    rows: list[LeaderboardRow] = []
    for car_id, agg in stats.items():
        car = db.get(Car, int(car_id))
        if not car:
            continue
        connection = db.get(Connection, car.connection_id)
        items_total = int(agg["items_total"])
        items_failed = int(agg["items_failed"])
        items_partial = int(agg["items_partial"])
        avg_ttft = float(agg["ttft_sum"]) / int(agg["ttft_count"]) if int(agg["ttft_count"]) > 0 else None
        avg_latency = (
            float(agg["latency_sum"]) / int(agg["latency_count"]) if int(agg["latency_count"]) > 0 else None
        )
        avg_tps = float(agg["tps_sum"]) / int(agg["tps_count"]) if int(agg["tps_count"]) > 0 else None
        error_rate = float(agg["error_count"]) / items_total if items_total > 0 else 0.0
        assertions_total = int(agg["assertions_total"])
        assertions_pass_rate = (
            float(agg["assertions_passed"]) / assertions_total if assertions_total > 0 else None
        )
        judge_values = judge_by_car.get(car.id, [])
        rows.append(
            LeaderboardRow(
                car_id=car.id,
                car_name=car.name,
                connection_name=connection.name if connection else "unknown",
                model_name=car.model_name,
                items_total=items_total,
                items_failed=items_failed,
                items_partial=items_partial,
                avg_ttft_ms=avg_ttft,
                avg_latency_ms=avg_latency,
                avg_tokens_per_sec=avg_tps,
                error_rate=error_rate,
                avg_assertion_pass_rate=assertions_pass_rate,
                avg_judge_overall=(sum(judge_values) / len(judge_values)) if judge_values else None,
            )
        )

    rows.sort(
        key=lambda r: (
            r.avg_judge_overall if r.avg_judge_overall is not None else -1,
            r.avg_assertion_pass_rate if r.avg_assertion_pass_rate is not None else -1,
            -r.error_rate,
        ),
        reverse=True,
    )
    return LeaderboardResponse(rows=rows)
