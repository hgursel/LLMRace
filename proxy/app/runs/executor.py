from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.db.models import (
    Car,
    Connection,
    Metric,
    Output,
    ProviderSettings,
    Run,
    RunItem,
    RunItemStatus,
    RunStatus,
    Suite,
    TestCase,
    ToolCall,
)
from app.providers.adapters import ProviderClient
from app.providers.normalize import build_request
from app.providers.types import NormalizedChatRequest, NormalizedMessage
from app.runs.assertions import evaluate_expected_constraints
from app.runs.metrics import compute_metrics
from app.runs.telemetry import emit_event
from app.runs.tools import ToolExecutionError, execute_tool, parse_fallback_tool_command


class RaceExecutor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider_client: ProviderClient,
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.provider_client = provider_client
        self.settings = settings
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def enqueue(self, run_id: int) -> None:
        await self._queue.put(run_id)

    async def _worker_loop(self) -> None:
        while True:
            run_id = await self._queue.get()
            try:
                await self._execute_run(run_id)
            except Exception as exc:  # noqa: BLE001
                with self.session_factory() as db:
                    run = db.get(Run, run_id)
                    if run:
                        run.status = RunStatus.FAILED
                        run.finished_at = datetime.utcnow()
                        db.commit()
                        emit_event(db, run_id, "run.completed", {"status": "FAILED", "error": str(exc)})
            finally:
                self._queue.task_done()

    async def _execute_run(self, run_id: int) -> None:
        with self.session_factory() as db:
            run = db.get(Run, run_id)
            if not run:
                return
            run.status = RunStatus.RUNNING
            run.started_at = datetime.utcnow()
            db.commit()
            emit_event(db, run_id, "run.started", {"status": run.status.value})

        with self.session_factory() as db:
            run = db.get(Run, run_id)
            if not run:
                return
            suite = db.get(Suite, run.suite_id)
            if not suite:
                raise RuntimeError(f"Suite not found for run {run_id}")
            tests = list(
                db.scalars(
                    select(TestCase).where(TestCase.suite_id == suite.id).order_by(TestCase.order_index.asc())
                )
            )
            cars = list(db.scalars(select(Car).where(Car.id.in_(run.selected_car_ids_json))))
            car_by_id = {car.id: car for car in cars}
            ordered_cars = [car_by_id[cid] for cid in run.selected_car_ids_json if cid in car_by_id]

        for test_case in tests:
            for car in ordered_cars:
                with self.session_factory() as db:
                    run_item = db.scalar(
                        select(RunItem).where(
                            RunItem.run_id == run_id,
                            RunItem.test_id == test_case.id,
                            RunItem.car_id == car.id,
                        )
                    )
                    if not run_item:
                        continue
                    connection = db.get(Connection, car.connection_id)
                    if not connection:
                        run_item.status = RunItemStatus.FAILED
                        run_item.error_message = "Connection missing"
                        db.commit()
                        emit_event(
                            db,
                            run_id,
                            "item.error",
                            {"error": "Connection missing", "car_id": car.id, "test_id": test_case.id},
                            run_item_id=run_item.id,
                        )
                        continue

                await self._execute_item(run_id, run_item.id, test_case.id, car.id, connection.id)

        with self.session_factory() as db:
            run = db.get(Run, run_id)
            if not run:
                return
            total_items = db.scalar(select(func.count(RunItem.id)).where(RunItem.run_id == run_id)) or 0
            failed_items = db.scalar(
                select(func.count(RunItem.id)).where(
                    RunItem.run_id == run_id,
                    RunItem.status == RunItemStatus.FAILED,
                )
            ) or 0
            run.status = RunStatus.FAILED if total_items > 0 and failed_items == total_items else RunStatus.COMPLETED
            run.finished_at = datetime.utcnow()
            db.commit()
            emit_event(db, run_id, "run.completed", {"status": run.status.value})

    async def _execute_item(self, run_id: int, run_item_id: int, test_id: int, car_id: int, connection_id: int) -> None:
        with self.session_factory() as db:
            run_item = db.get(RunItem, run_item_id)
            test_case = db.get(TestCase, test_id)
            car = db.get(Car, car_id)
            connection = db.get(Connection, connection_id)
            if not run_item or not test_case or not car or not connection:
                return

            provider_settings = db.scalar(
                select(ProviderSettings).where(ProviderSettings.provider_type == connection.type)
            )
            if not provider_settings:
                provider_settings = ProviderSettings(provider_type=connection.type)
                db.add(provider_settings)
                db.commit()
                db.refresh(provider_settings)

            run_item.status = RunItemStatus.RUNNING
            run_item.started_at = datetime.utcnow()
            db.commit()

            emit_event(
                db,
                run_id,
                "item.started",
                {"run_item_id": run_item_id, "car_id": car_id, "test_id": test_id},
                run_item_id=run_item_id,
            )

            retries = max(0, provider_settings.retry_count)
            backoff = max(0, provider_settings.retry_backoff_ms) / 1000.0

        last_error: str | None = None
        for attempt in range(retries + 1):
            try:
                await self._execute_item_attempt(run_id, run_item_id, attempt + 1)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                with self.session_factory() as db:
                    emit_event(
                        db,
                        run_id,
                        "item.error",
                        {
                            "run_item_id": run_item_id,
                            "attempt": attempt + 1,
                            "error": last_error,
                            "retrying": attempt < retries,
                        },
                        run_item_id=run_item_id,
                    )
                if attempt < retries:
                    await asyncio.sleep(backoff)

        with self.session_factory() as db:
            run_item = db.get(RunItem, run_item_id)
            if not run_item:
                return
            run_item.status = RunItemStatus.FAILED
            run_item.error_message = last_error
            run_item.finished_at = datetime.utcnow()
            db.commit()

            metric = db.scalar(select(Metric).where(Metric.run_item_id == run_item_id))
            if not metric:
                db.add(Metric(run_item_id=run_item_id, error_flag=True, output_tokens_estimated=True))
                db.commit()

            emit_event(
                db,
                run_id,
                "item.completed",
                {"run_item_id": run_item_id, "status": RunItemStatus.FAILED.value},
                run_item_id=run_item_id,
            )

    async def _execute_item_attempt(self, run_id: int, run_item_id: int, attempt_number: int) -> None:
        with self.session_factory() as db:
            run_item = db.get(RunItem, run_item_id)
            if not run_item:
                return
            test_case = db.get(TestCase, run_item.test_id)
            car = db.get(Car, run_item.car_id)
            if not test_case or not car:
                raise RuntimeError("Missing test or car")
            connection = db.get(Connection, car.connection_id)
            if not connection:
                raise RuntimeError("Missing connection")
            provider_settings = db.scalar(
                select(ProviderSettings).where(ProviderSettings.provider_type == connection.type)
            )
            if not provider_settings:
                raise RuntimeError("Missing provider settings")

            connection_context = SimpleNamespace(
                id=connection.id,
                type=connection.type,
                base_url=connection.base_url,
                api_key_env_var=connection.api_key_env_var,
            )
            semaphore_key = connection.type.value
            max_in_flight = provider_settings.max_in_flight
            timeout_ms = provider_settings.timeout_ms

            run_item.attempt_count = attempt_number
            db.commit()

            request_template = build_request(connection, car, test_case)
            expected_constraints = test_case.expected_constraints

        semaphore = self._get_semaphore(semaphore_key, max_in_flight)

        started_ms = int(time.perf_counter() * 1000)
        ttft_ms: int | None = None
        streamed_parts: list[str] = []
        loop_messages = request_template.messages.copy()
        last_response: dict[str, Any] | None = None
        tool_loop_exhausted = False

        async with semaphore:
            for loop_idx in range(self.settings.tool_loop_limit):
                request = NormalizedChatRequest(
                    model=request_template.model,
                    messages=loop_messages,
                    temperature=request_template.temperature,
                    top_p=request_template.top_p,
                    max_tokens=request_template.max_tokens,
                    stop=request_template.stop,
                    seed=request_template.seed,
                    tools=request_template.tools,
                    tool_choice=request_template.tool_choice,
                    stream=True,
                    metadata=request_template.metadata,
                )

                with self.session_factory() as db:
                    emit_event(
                        db,
                        run_id,
                        "request.sent",
                        {
                            "run_item_id": run_item_id,
                            "attempt": attempt_number,
                            "loop": loop_idx,
                            "model": request.model,
                        },
                        run_item_id=run_item_id,
                    )

                async def on_token(token: str) -> None:
                    nonlocal ttft_ms
                    streamed_parts.append(token)
                    if ttft_ms is None:
                        now_ms = int(time.perf_counter() * 1000)
                        ttft_ms = max(0, now_ms - started_ms)
                        with self.session_factory() as db:
                            emit_event(
                                db,
                                run_id,
                                "ttft.recorded",
                                {"run_item_id": run_item_id, "ttft_ms": ttft_ms},
                                run_item_id=run_item_id,
                            )
                    with self.session_factory() as db:
                        emit_event(
                            db,
                            run_id,
                            "token.delta",
                            {"run_item_id": run_item_id, "token": token},
                            run_item_id=run_item_id,
                        )

                async def on_telemetry(event_type: str, payload: dict[str, Any]) -> None:
                    with self.session_factory() as db:
                        emit_event(db, run_id, event_type, payload, run_item_id=run_item_id)

                provider_response = await self.provider_client.generate(
                    connection=connection_context,  # detached-safe lightweight context
                    request=request,
                    timeout_ms=timeout_ms,
                    on_token=on_token,
                    on_telemetry=on_telemetry,
                )
                last_response = {
                    "text": provider_response.text,
                    "tool_calls": provider_response.tool_calls,
                    "usage": provider_response.usage,
                    "raw": provider_response.raw,
                }

                tool_calls = provider_response.tool_calls
                provider_style = "native"
                if not tool_calls:
                    fallback = parse_fallback_tool_command(provider_response.text)
                    if fallback:
                        tool_calls = [{"id": f"fallback_{loop_idx}", "name": fallback["name"], "arguments": fallback["arguments"]}]
                        provider_style = "fallback"

                if not tool_calls:
                    break

                if loop_idx == self.settings.tool_loop_limit - 1:
                    tool_loop_exhausted = True
                assistant_content = provider_response.text or ""
                if assistant_content:
                    loop_messages.append(NormalizedMessage(role="assistant", content=assistant_content))

                for tool in tool_calls:
                    tool_name = tool.get("name", "")
                    args = tool.get("arguments", {})
                    if not isinstance(args, dict):
                        args = {"raw": args}

                    try:
                        result = execute_tool(tool_name, args)
                        status = "ok"
                    except ToolExecutionError as exc:
                        result = {"error": str(exc)}
                        status = "error"

                    with self.session_factory() as db:
                        db.add(
                            ToolCall(
                                run_item_id=run_item_id,
                                loop_index=loop_idx,
                                tool_name=tool_name,
                                args_json=args,
                                result_json=result,
                                status=status,
                                provider_style=provider_style,
                            )
                        )
                        db.commit()
                        emit_event(
                            db,
                            run_id,
                            "tool.call.executed",
                            {
                                "run_item_id": run_item_id,
                                "tool_name": tool_name,
                                "args": args,
                                "result": result,
                                "status": status,
                            },
                            run_item_id=run_item_id,
                        )

                    loop_messages.append(
                        NormalizedMessage(
                            role="tool",
                            name=tool_name,
                            tool_call_id=tool.get("id"),
                            content=json.dumps(result),
                        )
                    )

                with self.session_factory() as db:
                    emit_event(
                        db,
                        run_id,
                        "tool.loop.continue",
                        {
                            "run_item_id": run_item_id,
                            "loop": loop_idx,
                            "tool_calls": len(tool_calls),
                        },
                        run_item_id=run_item_id,
                    )

        if tool_loop_exhausted:
            with self.session_factory() as db:
                emit_event(
                    db,
                    run_id,
                    "tool.loop.exhausted",
                    {
                        "run_item_id": run_item_id,
                        "limit": self.settings.tool_loop_limit,
                    },
                    run_item_id=run_item_id,
                )

        finished_ms = int(time.perf_counter() * 1000)
        output_text = "".join(streamed_parts) if streamed_parts else (last_response or {}).get("text", "")
        usage = (last_response or {}).get("usage", {})
        completion_tokens = usage.get("completion_tokens")
        usage_estimated = bool(usage.get("estimated", False))
        metric_values = compute_metrics(
            started_ms=started_ms,
            finished_ms=finished_ms,
            ttft_ms=ttft_ms,
            output_text=output_text,
            usage_completion_tokens=completion_tokens,
            usage_estimated=usage_estimated,
        )
        assertion_summary = evaluate_expected_constraints(expected_constraints, output_text)

        with self.session_factory() as db:
            run_item = db.get(RunItem, run_item_id)
            if not run_item:
                return

            existing_output = db.scalar(select(Output).where(Output.run_item_id == run_item_id))
            payload_raw = dict((last_response or {}).get("raw", {}) or {})
            if assertion_summary["total"] > 0:
                payload_raw["assertions"] = assertion_summary
            request_messages = [
                {
                    "role": m.role,
                    "content": m.content,
                    "tool_call_id": m.tool_call_id,
                    "name": m.name,
                }
                for m in loop_messages
            ]
            if existing_output:
                existing_output.request_messages_json = request_messages
                existing_output.streamed_text = "".join(streamed_parts)
                existing_output.final_text = output_text
                existing_output.raw_provider_payload_json = payload_raw
            else:
                db.add(
                    Output(
                        run_item_id=run_item_id,
                        request_messages_json=request_messages,
                        streamed_text="".join(streamed_parts),
                        final_text=output_text,
                        raw_provider_payload_json=payload_raw,
                    )
                )

            existing_metric = db.scalar(select(Metric).where(Metric.run_item_id == run_item_id))
            if existing_metric:
                existing_metric.ttft_ms = metric_values.ttft_ms
                existing_metric.total_latency_ms = metric_values.total_latency_ms
                existing_metric.generation_ms = metric_values.generation_ms
                existing_metric.output_tokens = metric_values.output_tokens
                existing_metric.output_tokens_estimated = metric_values.output_tokens_estimated
                existing_metric.tokens_per_sec = metric_values.tokens_per_sec
                existing_metric.error_flag = False
            else:
                db.add(
                    Metric(
                        run_item_id=run_item_id,
                        ttft_ms=metric_values.ttft_ms,
                        total_latency_ms=metric_values.total_latency_ms,
                        generation_ms=metric_values.generation_ms,
                        output_tokens=metric_values.output_tokens,
                        output_tokens_estimated=metric_values.output_tokens_estimated,
                        tokens_per_sec=metric_values.tokens_per_sec,
                        error_flag=False,
                    )
                )

            run_item.status = RunItemStatus.PARTIAL_TOOL_SUPPORT if tool_loop_exhausted else RunItemStatus.COMPLETED
            run_item.finished_at = datetime.utcnow()
            run_item.error_message = None
            db.commit()

            emit_event(
                db,
                run_id,
                "item.metrics",
                {
                    "run_item_id": run_item_id,
                    "ttft_ms": metric_values.ttft_ms,
                    "latency_ms": metric_values.total_latency_ms,
                    "tokens_per_sec": metric_values.tokens_per_sec,
                    "output_tokens": metric_values.output_tokens,
                    "estimated": metric_values.output_tokens_estimated,
                },
                run_item_id=run_item_id,
            )
            if assertion_summary["total"] > 0:
                emit_event(
                    db,
                    run_id,
                    "item.assertions",
                    {
                        "run_item_id": run_item_id,
                        "passed": assertion_summary["passed"],
                        "total": assertion_summary["total"],
                    },
                    run_item_id=run_item_id,
                )
            emit_event(
                db,
                run_id,
                "item.completed",
                {"run_item_id": run_item_id, "status": run_item.status.value},
                run_item_id=run_item_id,
            )

    def _get_semaphore(self, key: str, max_in_flight: int) -> asyncio.Semaphore:
        max_size = max(1, max_in_flight)
        existing = self._semaphores.get(key)
        if existing is None:
            existing = asyncio.Semaphore(max_size)
            self._semaphores[key] = existing
        return existing
