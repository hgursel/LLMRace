from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SqlEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def now_utc() -> datetime:
    return datetime.utcnow()


class ConnectionType(str, Enum):
    OLLAMA = "OLLAMA"
    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"
    OPENROUTER = "OPENROUTER"
    OPENAI_COMPAT = "OPENAI_COMPAT"
    LLAMACPP_OPENAI = "LLAMACPP_OPENAI"
    CUSTOM = "CUSTOM"


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RunItemStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL_TOOL_SUPPORT = "PARTIAL_TOOL_SUPPORT"


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    type: Mapped[ConnectionType] = mapped_column(SqlEnum(ConnectionType), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key_env_var: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    cars: Mapped[list[Car]] = relationship("Car", back_populates="connection", cascade="all, delete-orphan")


class ProviderSettings(Base):
    __tablename__ = "provider_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider_type: Mapped[ConnectionType] = mapped_column(SqlEnum(ConnectionType), unique=True, nullable=False)
    max_in_flight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=60000, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    retry_backoff_ms: Mapped[int] = mapped_column(Integer, default=400, nullable=False)


class Car(Base):
    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    connection_id: Mapped[int] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    top_p: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)

    connection: Mapped[Connection] = relationship("Connection", back_populates="cars")


class Suite(Base):
    __tablename__ = "suites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc, nullable=False)

    tests: Mapped[list[TestCase]] = relationship("TestCase", back_populates="suite", cascade="all, delete-orphan")


class TestCase(Base):
    __tablename__ = "tests"
    __table_args__ = (UniqueConstraint("suite_id", "order_index", name="uq_suite_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    suite_id: Mapped[int] = mapped_column(ForeignKey("suites.id", ondelete="CASCADE"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    expected_constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_schema_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    suite: Mapped[Suite] = relationship("Suite", back_populates="tests")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    suite_id: Mapped[int] = mapped_column(ForeignKey("suites.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[RunStatus] = mapped_column(SqlEnum(RunStatus), default=RunStatus.QUEUED, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    selected_car_ids_json: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    judge_car_id_nullable: Mapped[int | None] = mapped_column(ForeignKey("cars.id", ondelete="SET NULL"), nullable=True)

    items: Mapped[list[RunItem]] = relationship("RunItem", back_populates="run", cascade="all, delete-orphan")


class RunItem(Base):
    __tablename__ = "run_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id", ondelete="SET NULL"), nullable=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[RunItemStatus] = mapped_column(SqlEnum(RunItemStatus), default=RunItemStatus.PENDING, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[Run] = relationship("Run", back_populates="items")


class Output(Base):
    __tablename__ = "outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_item_id: Mapped[int] = mapped_column(ForeignKey("run_items.id", ondelete="CASCADE"), nullable=False, unique=True)
    request_messages_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    streamed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_provider_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_item_id: Mapped[int] = mapped_column(ForeignKey("run_items.id", ondelete="CASCADE"), nullable=False, unique=True)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens_estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tokens_per_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_item_id: Mapped[int] = mapped_column(ForeignKey("run_items.id", ondelete="CASCADE"), nullable=False)
    loop_index: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False)
    args_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_style: Mapped[str] = mapped_column(String(32), nullable=False)


class JudgeResult(Base):
    __tablename__ = "judge_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    run_item_id_nullable: Mapped[int | None] = mapped_column(ForeignKey("run_items.id", ondelete="SET NULL"), nullable=True)
    car_id_nullable: Mapped[int | None] = mapped_column(ForeignKey("cars.id", ondelete="SET NULL"), nullable=True)
    writing_score: Mapped[float] = mapped_column(Float, nullable=False)
    coding_score: Mapped[float] = mapped_column(Float, nullable=False)
    tool_score: Mapped[float] = mapped_column(Float, nullable=False)
    overall: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    run_item_id_nullable: Mapped[int | None] = mapped_column(ForeignKey("run_items.id", ondelete="SET NULL"), nullable=True)
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, nullable=False)
