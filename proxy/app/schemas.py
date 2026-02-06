from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.db.models import ConnectionType, RunItemStatus, RunStatus


class HealthResponse(BaseModel):
    status: str


class ConnectionCreate(BaseModel):
    name: str
    type: ConnectionType
    base_url: str
    api_key_env_var: str | None = None


class ConnectionUpdate(BaseModel):
    name: str | None = None
    type: ConnectionType | None = None
    base_url: str | None = None
    api_key_env_var: str | None = None


class ConnectionOut(BaseModel):
    id: int
    name: str
    type: ConnectionType
    base_url: str
    api_key_env_var: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConnectionTestResponse(BaseModel):
    ok: bool
    latency_ms: int | None
    models: list[str] = Field(default_factory=list)
    error: str | None = None


class CarCreate(BaseModel):
    name: str
    connection_id: int
    model_name: str
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int | None = None
    stop_json: list[str] | None = None
    seed: int | None = None


class CarUpdate(BaseModel):
    name: str | None = None
    connection_id: int | None = None
    model_name: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop_json: list[str] | None = None
    seed: int | None = None


class CarOut(BaseModel):
    id: int
    name: str
    connection_id: int
    model_name: str
    temperature: float
    top_p: float
    max_tokens: int | None
    stop_json: list[str] | None
    seed: int | None
    created_at: datetime

    class Config:
        from_attributes = True


class TestCaseIn(BaseModel):
    order_index: int
    name: str
    system_prompt: str | None = None
    user_prompt: str
    expected_constraints: str | None = None
    tools_schema_json: list[dict[str, Any]] | None = None


class TestCaseOut(TestCaseIn):
    id: int
    suite_id: int

    class Config:
        from_attributes = True


class SuiteCreate(BaseModel):
    name: str
    category: str
    description: str | None = None
    tests: list[TestCaseIn]


class SuiteUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    tests: list[TestCaseIn] | None = None


class SuiteOut(BaseModel):
    id: int
    name: str
    category: str
    description: str | None
    is_demo: bool
    created_at: datetime
    updated_at: datetime
    tests: list[TestCaseOut]

    class Config:
        from_attributes = True


class StartRunRequest(BaseModel):
    suite_id: int
    car_ids: list[int]
    judge_car_id: int | None = None


class StartRunResponse(BaseModel):
    run_id: int


class RunItemOut(BaseModel):
    id: int
    test_id: int | None
    car_id: int | None
    status: RunItemStatus
    attempt_count: int
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None

    class Config:
        from_attributes = True


class RunOut(BaseModel):
    id: int
    suite_id: int | None
    status: RunStatus
    started_at: datetime | None
    finished_at: datetime | None
    selected_car_ids_json: list[int]
    judge_car_id_nullable: int | None
    items: list[RunItemOut] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ProviderSettingOut(BaseModel):
    provider_type: ConnectionType
    max_in_flight: int
    timeout_ms: int
    retry_count: int
    retry_backoff_ms: int

    class Config:
        from_attributes = True


class ProviderSettingsUpdateItem(BaseModel):
    provider_type: ConnectionType
    max_in_flight: int | None = None
    timeout_ms: int | None = None
    retry_count: int | None = None
    retry_backoff_ms: int | None = None


class ProviderSettingsUpdate(BaseModel):
    items: list[ProviderSettingsUpdateItem]


class JudgeRequest(BaseModel):
    judge_car_id: int | None = None


class JudgeScore(BaseModel):
    writing_score: float
    coding_score: float
    tool_score: float
    overall: float
    rationale: str


class JudgeResponse(BaseModel):
    run_id: int
    item_scores: int
    car_aggregates: int


class LeaderboardRow(BaseModel):
    car_id: int
    car_name: str
    connection_name: str
    model_name: str
    items_total: int
    items_failed: int
    items_partial: int
    avg_ttft_ms: float | None
    avg_latency_ms: float | None
    avg_tokens_per_sec: float | None
    error_rate: float
    avg_assertion_pass_rate: float | None
    avg_judge_overall: float | None


class LeaderboardResponse(BaseModel):
    rows: list[LeaderboardRow]


class RunScorecardRow(BaseModel):
    car_id: int
    car_name: str
    model_name: str
    items_total: int
    items_completed: int
    items_failed: int
    items_partial: int
    error_rate: float
    avg_ttft_ms: float | None
    avg_latency_ms: float | None
    avg_tokens_per_sec: float | None
    assertion_pass_rate: float | None
    avg_judge_overall: float | None


class RunScorecardResponse(BaseModel):
    run_id: int
    rows: list[RunScorecardRow]


class RunComparisonRow(BaseModel):
    car_id: int
    car_name: str
    model_name: str
    latency_delta_ms: float | None
    tokens_per_sec_delta: float | None
    error_rate_delta: float | None
    assertion_pass_rate_delta: float | None
    judge_overall_delta: float | None
    summary: str


class RunComparisonResponse(BaseModel):
    run_id: int
    baseline_run_id: int
    rows: list[RunComparisonRow]
