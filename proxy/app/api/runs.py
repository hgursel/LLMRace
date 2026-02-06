from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_executor
from app.core.settings import get_settings
from app.db.models import (
    Car,
    Connection,
    JudgeResult,
    Metric,
    Output,
    Run,
    RunItem,
    RunItemStatus,
    RunStatus,
    Suite,
    TestCase,
    ToolCall,
)
from app.db.session import SessionLocal, get_db
from app.providers.adapters import ProviderClient
from app.providers.types import NormalizedChatRequest, NormalizedMessage
from app.runs.executor import RaceExecutor
from app.runs.judge import build_judge_messages, parse_judge_json
from app.runs.telemetry import emit_event, list_events_after
from app.schemas import JudgeRequest, JudgeResponse, RunOut, StartRunRequest, StartRunResponse
from app.schemas import RunComparisonResponse, RunComparisonRow, RunScorecardResponse, RunScorecardRow

router = APIRouter(prefix="/api/runs", tags=["runs"])
provider_client = ProviderClient()
settings = get_settings()


def _build_run_scorecard_rows(db: Session, run_id: int) -> list[RunScorecardRow]:
    run_items = list(db.scalars(select(RunItem).where(RunItem.run_id == run_id).order_by(RunItem.id.asc())))
    if not run_items:
        return []

    metrics_by_item = {
        row.run_item_id: row
        for row in db.scalars(select(Metric).join(RunItem, Metric.run_item_id == RunItem.id).where(RunItem.run_id == run_id))
    }
    outputs_by_item = {
        row.run_item_id: row
        for row in db.scalars(select(Output).join(RunItem, Output.run_item_id == RunItem.id).where(RunItem.run_id == run_id))
    }
    judge_by_item = {
        row.run_item_id_nullable: row
        for row in db.scalars(
            select(JudgeResult).where(
                JudgeResult.run_id == run_id,
                JudgeResult.run_item_id_nullable.is_not(None),
            )
        )
        if row.run_item_id_nullable is not None
    }

    car_ids = [item.car_id for item in run_items if item.car_id is not None]
    cars = {car.id: car for car in db.scalars(select(Car).where(Car.id.in_(car_ids)))}

    aggregates: dict[int, dict[str, float | int]] = {}
    for item in run_items:
        car_id = item.car_id
        if car_id is None:
            continue
        bucket = aggregates.setdefault(
            int(car_id),
            {
                "items_total": 0,
                "items_completed": 0,
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
                "judge_sum": 0.0,
                "judge_count": 0,
            },
        )
        bucket["items_total"] += 1
        if item.status == RunItemStatus.COMPLETED:
            bucket["items_completed"] += 1
        if item.status == RunItemStatus.FAILED:
            bucket["items_failed"] += 1
        if item.status == RunItemStatus.PARTIAL_TOOL_SUPPORT:
            bucket["items_partial"] += 1

        metric = metrics_by_item.get(item.id)
        if metric:
            if metric.error_flag:
                bucket["error_count"] += 1
            if metric.ttft_ms is not None:
                bucket["ttft_sum"] += float(metric.ttft_ms)
                bucket["ttft_count"] += 1
            if metric.total_latency_ms is not None:
                bucket["latency_sum"] += float(metric.total_latency_ms)
                bucket["latency_count"] += 1
            if metric.tokens_per_sec is not None:
                bucket["tps_sum"] += float(metric.tokens_per_sec)
                bucket["tps_count"] += 1
        elif item.status == RunItemStatus.FAILED:
            bucket["error_count"] += 1

        output = outputs_by_item.get(item.id)
        raw_payload = output.raw_provider_payload_json if output else None
        assertions = raw_payload.get("assertions") if isinstance(raw_payload, dict) else None
        if isinstance(assertions, dict):
            total = assertions.get("total")
            passed = assertions.get("passed")
            if isinstance(total, int) and isinstance(passed, int) and total > 0:
                bucket["assertions_total"] += total
                bucket["assertions_passed"] += passed

        judge = judge_by_item.get(item.id)
        if judge is not None:
            bucket["judge_sum"] += float(judge.overall)
            bucket["judge_count"] += 1

    rows: list[RunScorecardRow] = []
    for car_id, bucket in aggregates.items():
        items_total = int(bucket["items_total"])
        assertions_total = int(bucket["assertions_total"])
        car = cars.get(car_id)
        rows.append(
            RunScorecardRow(
                car_id=car_id,
                car_name=car.name if car else f"car:{car_id}",
                model_name=car.model_name if car else "unknown",
                items_total=items_total,
                items_completed=int(bucket["items_completed"]),
                items_failed=int(bucket["items_failed"]),
                items_partial=int(bucket["items_partial"]),
                error_rate=(float(bucket["error_count"]) / items_total) if items_total > 0 else 0.0,
                avg_ttft_ms=(
                    float(bucket["ttft_sum"]) / int(bucket["ttft_count"]) if int(bucket["ttft_count"]) > 0 else None
                ),
                avg_latency_ms=(
                    float(bucket["latency_sum"]) / int(bucket["latency_count"]) if int(bucket["latency_count"]) > 0 else None
                ),
                avg_tokens_per_sec=(
                    float(bucket["tps_sum"]) / int(bucket["tps_count"]) if int(bucket["tps_count"]) > 0 else None
                ),
                assertion_pass_rate=(
                    float(bucket["assertions_passed"]) / assertions_total if assertions_total > 0 else None
                ),
                avg_judge_overall=(
                    float(bucket["judge_sum"]) / int(bucket["judge_count"]) if int(bucket["judge_count"]) > 0 else None
                ),
            )
        )

    rows.sort(
        key=lambda row: (
            row.avg_judge_overall if row.avg_judge_overall is not None else -1,
            row.assertion_pass_rate if row.assertion_pass_rate is not None else -1,
            -row.error_rate,
        ),
        reverse=True,
    )
    return rows


def _classify_delta(
    latency_delta: float | None,
    tps_delta: float | None,
    error_delta: float | None,
    assertion_delta: float | None,
    judge_delta: float | None,
) -> str:
    score = 0
    if latency_delta is not None:
        if latency_delta <= -50:
            score += 1
        elif latency_delta >= 50:
            score -= 1
    if tps_delta is not None:
        if tps_delta >= 0.5:
            score += 1
        elif tps_delta <= -0.5:
            score -= 1
    if error_delta is not None:
        if error_delta <= -0.05:
            score += 1
        elif error_delta >= 0.05:
            score -= 1
    if assertion_delta is not None:
        if assertion_delta >= 0.05:
            score += 1
        elif assertion_delta <= -0.05:
            score -= 1
    if judge_delta is not None:
        if judge_delta >= 0.3:
            score += 1
        elif judge_delta <= -0.3:
            score -= 1

    if score >= 2:
        return "improved"
    if score <= -2:
        return "regressed"
    return "mixed"


@router.post("/start", response_model=StartRunResponse)
async def start_run(
    payload: StartRunRequest,
    db: Session = Depends(get_db),
    executor: RaceExecutor = Depends(get_executor),
) -> StartRunResponse:
    suite = db.get(Suite, payload.suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    cars = list(db.scalars(select(Car).where(Car.id.in_(payload.car_ids))))
    if len(cars) != len(set(payload.car_ids)):
        raise HTTPException(status_code=400, detail="One or more car IDs are invalid")

    tests = list(db.scalars(select(TestCase).where(TestCase.suite_id == payload.suite_id).order_by(TestCase.order_index.asc())))
    if not tests:
        raise HTTPException(status_code=400, detail="Suite has no tests")

    run = Run(
        suite_id=payload.suite_id,
        status=RunStatus.QUEUED,
        selected_car_ids_json=payload.car_ids,
        judge_car_id_nullable=payload.judge_car_id,
    )
    db.add(run)
    db.flush()

    for test_case in tests:
        for car_id in payload.car_ids:
            db.add(
                RunItem(
                    run_id=run.id,
                    test_id=test_case.id,
                    car_id=car_id,
                    status=RunItemStatus.PENDING,
                    attempt_count=0,
                )
            )

    db.commit()
    await executor.enqueue(run.id)
    return StartRunResponse(run_id=run.id)


@router.get("", response_model=list[RunOut])
def list_runs(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
    status: RunStatus | None = Query(default=None),
    suite_id: int | None = Query(default=None, ge=1),
    car_id: int | None = Query(default=None, ge=1),
) -> list[Run]:
    stmt = select(Run).order_by(Run.id.desc())
    if status is not None:
        stmt = stmt.where(Run.status == status)
    if suite_id is not None:
        stmt = stmt.where(Run.suite_id == suite_id)
    if car_id is not None:
        stmt = stmt.join(RunItem, RunItem.run_id == Run.id).where(RunItem.car_id == car_id).distinct()
    stmt = stmt.limit(limit)
    return list(db.scalars(stmt))


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.scalar(select(Run).where(Run.id == run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    items = list(db.scalars(select(RunItem).where(RunItem.run_id == run_id).order_by(RunItem.id.asc())))
    outputs = list(db.scalars(select(Output).join(RunItem, Output.run_item_id == RunItem.id).where(RunItem.run_id == run_id)))
    metrics = list(db.scalars(select(Metric).join(RunItem, Metric.run_item_id == RunItem.id).where(RunItem.run_id == run_id)))
    tool_calls = list(
        db.scalars(select(ToolCall).join(RunItem, ToolCall.run_item_id == RunItem.id).where(RunItem.run_id == run_id))
    )
    judge_rows = list(db.scalars(select(JudgeResult).where(JudgeResult.run_id == run_id).order_by(JudgeResult.id.asc())))

    return {
        "run": {
            "id": run.id,
            "suite_id": run.suite_id,
            "status": run.status.value,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "selected_car_ids_json": run.selected_car_ids_json,
            "judge_car_id_nullable": run.judge_car_id_nullable,
        },
        "items": [
            {
                "id": item.id,
                "test_id": item.test_id,
                "car_id": item.car_id,
                "status": item.status.value,
                "attempt_count": item.attempt_count,
                "started_at": item.started_at,
                "finished_at": item.finished_at,
                "error_message": item.error_message,
            }
            for item in items
        ],
        "outputs": [
            {
                "run_item_id": out.run_item_id,
                "request_messages_json": out.request_messages_json,
                "streamed_text": out.streamed_text,
                "final_text": out.final_text,
                "raw_provider_payload_json": out.raw_provider_payload_json,
            }
            for out in outputs
        ],
        "metrics": [
            {
                "run_item_id": metric.run_item_id,
                "ttft_ms": metric.ttft_ms,
                "total_latency_ms": metric.total_latency_ms,
                "generation_ms": metric.generation_ms,
                "output_tokens": metric.output_tokens,
                "output_tokens_estimated": metric.output_tokens_estimated,
                "tokens_per_sec": metric.tokens_per_sec,
                "error_flag": metric.error_flag,
            }
            for metric in metrics
        ],
        "tool_calls": [
            {
                "run_item_id": tool.run_item_id,
                "loop_index": tool.loop_index,
                "tool_name": tool.tool_name,
                "args_json": tool.args_json,
                "result_json": tool.result_json,
                "status": tool.status,
                "provider_style": tool.provider_style,
            }
            for tool in tool_calls
        ],
        "judge_results": [
            {
                "id": row.id,
                "run_item_id": row.run_item_id_nullable,
                "car_id": row.car_id_nullable,
                "writing_score": row.writing_score,
                "coding_score": row.coding_score,
                "tool_score": row.tool_score,
                "overall": row.overall,
                "rationale": row.rationale,
            }
            for row in judge_rows
        ],
    }


@router.get("/{run_id}/scorecard", response_model=RunScorecardResponse)
def get_run_scorecard(run_id: int, db: Session = Depends(get_db)) -> RunScorecardResponse:
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rows = _build_run_scorecard_rows(db, run_id)
    return RunScorecardResponse(run_id=run_id, rows=rows)


@router.get("/{run_id}/compare", response_model=RunComparisonResponse)
def compare_runs(
    run_id: int,
    baseline_run_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
) -> RunComparisonResponse:
    run = db.get(Run, run_id)
    baseline_run = db.get(Run, baseline_run_id)
    if not run or not baseline_run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run_id == baseline_run_id:
        raise HTTPException(status_code=400, detail="Baseline run must be different")

    current_rows = _build_run_scorecard_rows(db, run_id)
    baseline_rows = _build_run_scorecard_rows(db, baseline_run_id)
    baseline_by_car = {row.car_id: row for row in baseline_rows}
    result_rows: list[RunComparisonRow] = []

    for current in current_rows:
        baseline = baseline_by_car.get(current.car_id)
        if baseline is None:
            result_rows.append(
                RunComparisonRow(
                    car_id=current.car_id,
                    car_name=current.car_name,
                    model_name=current.model_name,
                    latency_delta_ms=None,
                    tokens_per_sec_delta=None,
                    error_rate_delta=None,
                    assertion_pass_rate_delta=None,
                    judge_overall_delta=None,
                    summary="new profile in current run",
                )
            )
            continue

        latency_delta = (
            (current.avg_latency_ms - baseline.avg_latency_ms)
            if current.avg_latency_ms is not None and baseline.avg_latency_ms is not None
            else None
        )
        tps_delta = (
            (current.avg_tokens_per_sec - baseline.avg_tokens_per_sec)
            if current.avg_tokens_per_sec is not None and baseline.avg_tokens_per_sec is not None
            else None
        )
        error_delta = current.error_rate - baseline.error_rate
        assertion_delta = (
            (current.assertion_pass_rate - baseline.assertion_pass_rate)
            if current.assertion_pass_rate is not None and baseline.assertion_pass_rate is not None
            else None
        )
        judge_delta = (
            (current.avg_judge_overall - baseline.avg_judge_overall)
            if current.avg_judge_overall is not None and baseline.avg_judge_overall is not None
            else None
        )

        result_rows.append(
            RunComparisonRow(
                car_id=current.car_id,
                car_name=current.car_name,
                model_name=current.model_name,
                latency_delta_ms=latency_delta,
                tokens_per_sec_delta=tps_delta,
                error_rate_delta=error_delta,
                assertion_pass_rate_delta=assertion_delta,
                judge_overall_delta=judge_delta,
                summary=_classify_delta(latency_delta, tps_delta, error_delta, assertion_delta, judge_delta),
            )
        )

    result_rows.sort(key=lambda row: row.car_name.lower())
    return RunComparisonResponse(run_id=run_id, baseline_run_id=baseline_run_id, rows=result_rows)


@router.get("/{run_id}/stream")
async def stream_run(
    run_id: int,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after_seq: int | None = Query(default=None, ge=0),
) -> StreamingResponse:
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

    start_after = after_seq
    if start_after is None:
        try:
            start_after = int(last_event_id) if last_event_id else 0
        except ValueError:
            start_after = 0

    async def event_generator() -> Any:
        current_seq = start_after or 0
        last_heartbeat = asyncio.get_event_loop().time()

        while True:
            with SessionLocal() as db:
                events = list_events_after(db, run_id, current_seq)
                run = db.get(Run, run_id)

            if events:
                for event in events:
                    current_seq = event.seq_no
                    data = json.dumps(event.payload_json)
                    yield f"id: {event.seq_no}\nevent: {event.event_type}\ndata: {data}\n\n"

            now = asyncio.get_event_loop().time()
            if now - last_heartbeat >= settings.telemetry_heartbeat_seconds:
                yield ": heartbeat\n\n"
                last_heartbeat = now

            if run and run.status in (RunStatus.COMPLETED, RunStatus.FAILED) and not events:
                break

            await asyncio.sleep(settings.telemetry_poll_interval_seconds)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{run_id}/judge", response_model=JudgeResponse)
async def judge_run(run_id: int, payload: JudgeRequest, db: Session = Depends(get_db)) -> JudgeResponse:
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    judge_car_id = payload.judge_car_id or run.judge_car_id_nullable
    if not judge_car_id:
        raise HTTPException(status_code=400, detail="No judge car selected")

    judge_car = db.get(Car, judge_car_id)
    if not judge_car:
        raise HTTPException(status_code=404, detail="Judge car not found")

    judge_connection = db.get(Connection, judge_car.connection_id)
    if not judge_connection:
        raise HTTPException(status_code=404, detail="Judge connection not found")

    emit_event(db, run_id, "judge.started", {"judge_car_id": judge_car_id})

    db.execute(delete(JudgeResult).where(JudgeResult.run_id == run_id))
    db.commit()

    run_items = list(db.scalars(select(RunItem).where(RunItem.run_id == run_id).order_by(RunItem.id.asc())))
    outputs_by_item = {
        row.run_item_id: row
        for row in db.scalars(select(Output).join(RunItem, Output.run_item_id == RunItem.id).where(RunItem.run_id == run_id))
    }
    tests_by_id = {row.id: row for row in db.scalars(select(TestCase).where(TestCase.id.in_([item.test_id for item in run_items if item.test_id])))}

    item_scores = 0
    for item in run_items:
        output = outputs_by_item.get(item.id)
        test_case = tests_by_id.get(item.test_id)
        if not output or not test_case:
            continue

        messages = build_judge_messages(test_case.name, test_case.user_prompt, output.final_text or output.streamed_text or "")
        request = NormalizedChatRequest(
            model=judge_car.model_name,
            messages=[NormalizedMessage(role=m["role"], content=m["content"]) for m in messages],
            temperature=0,
            top_p=1,
            max_tokens=300,
            stream=True,
            metadata={"judge": True, "run_id": run_id, "run_item_id": item.id},
        )

        chunks: list[str] = []

        async def on_token(token: str) -> None:
            chunks.append(token)

        judge_response = await provider_client.generate(
            connection=judge_connection,
            request=request,
            timeout_ms=60000,
            on_token=on_token,
            on_telemetry=None,
        )

        raw_text = judge_response.text or "".join(chunks)
        try:
            parsed = parse_judge_json(raw_text)
        except Exception:  # noqa: BLE001
            parsed = {
                "writing_score": 0.0,
                "coding_score": 0.0,
                "tool_score": 0.0,
                "overall": 0.0,
                "rationale": "Judge JSON parse failed",
            }

        db.add(
            JudgeResult(
                run_id=run_id,
                run_item_id_nullable=item.id,
                car_id_nullable=item.car_id,
                writing_score=parsed["writing_score"],
                coding_score=parsed["coding_score"],
                tool_score=parsed["tool_score"],
                overall=parsed["overall"],
                rationale=parsed["rationale"],
                raw_json=parsed,
            )
        )
        item_scores += 1

    db.commit()

    rows = list(
        db.scalars(
            select(JudgeResult).where(
                JudgeResult.run_id == run_id,
                JudgeResult.run_item_id_nullable.is_not(None),
            )
        )
    )

    aggregates_by_car: dict[int, list[JudgeResult]] = {}
    for row in rows:
        if row.car_id_nullable is None:
            continue
        aggregates_by_car.setdefault(row.car_id_nullable, []).append(row)

    car_aggregates = 0
    for car_id, items in aggregates_by_car.items():
        total = len(items)
        if not total:
            continue
        db.add(
            JudgeResult(
                run_id=run_id,
                run_item_id_nullable=None,
                car_id_nullable=car_id,
                writing_score=sum(i.writing_score for i in items) / total,
                coding_score=sum(i.coding_score for i in items) / total,
                tool_score=sum(i.tool_score for i in items) / total,
                overall=sum(i.overall for i in items) / total,
                rationale="Per-car aggregate",
                raw_json={"aggregate": "car", "count": total},
            )
        )
        car_aggregates += 1

    if rows:
        total = len(rows)
        db.add(
            JudgeResult(
                run_id=run_id,
                run_item_id_nullable=None,
                car_id_nullable=None,
                writing_score=sum(i.writing_score for i in rows) / total,
                coding_score=sum(i.coding_score for i in rows) / total,
                tool_score=sum(i.tool_score for i in rows) / total,
                overall=sum(i.overall for i in rows) / total,
                rationale="Run aggregate",
                raw_json={"aggregate": "run", "count": total},
            )
        )

    db.commit()
    emit_event(db, run_id, "judge.completed", {"item_scores": item_scores, "car_aggregates": car_aggregates})

    return JudgeResponse(run_id=run_id, item_scores=item_scores, car_aggregates=car_aggregates)
