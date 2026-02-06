"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-02-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


connection_enum = sa.Enum("OLLAMA", "OPENAI_COMPAT", "LLAMACPP_OPENAI", "CUSTOM", name="connectiontype")
run_status_enum = sa.Enum("QUEUED", "RUNNING", "COMPLETED", "FAILED", name="runstatus")
run_item_status_enum = sa.Enum(
    "PENDING", "RUNNING", "COMPLETED", "FAILED", "PARTIAL_TOOL_SUPPORT", name="runitemstatus"
)


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("type", connection_enum, nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("api_key_env_var", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_connections_id", "connections", ["id"])

    op.create_table(
        "provider_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_type", connection_enum, nullable=False, unique=True),
        sa.Column("max_in_flight", sa.Integer(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("retry_backoff_ms", sa.Integer(), nullable=False),
    )
    op.create_index("ix_provider_settings_id", "provider_settings", ["id"])

    op.create_table(
        "cars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("connection_id", sa.Integer(), sa.ForeignKey("connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_name", sa.String(length=256), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("top_p", sa.Float(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("stop_json", sa.JSON(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_cars_id", "cars", ["id"])

    op.create_table(
        "suites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_suites_id", "suites", ["id"])

    op.create_table(
        "tests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("suite_id", sa.Integer(), sa.ForeignKey("suites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("expected_constraints", sa.Text(), nullable=True),
        sa.Column("tools_schema_json", sa.JSON(), nullable=True),
        sa.UniqueConstraint("suite_id", "order_index", name="uq_suite_order"),
    )
    op.create_index("ix_tests_id", "tests", ["id"])

    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("suite_id", sa.Integer(), sa.ForeignKey("suites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", run_status_enum, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("selected_car_ids_json", sa.JSON(), nullable=False),
        sa.Column("judge_car_id_nullable", sa.Integer(), sa.ForeignKey("cars.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_runs_id", "runs", ["id"])

    op.create_table(
        "run_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("test_id", sa.Integer(), sa.ForeignKey("tests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("car_id", sa.Integer(), sa.ForeignKey("cars.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", run_item_status_enum, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_run_items_id", "run_items", ["id"])

    op.create_table(
        "outputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_item_id", sa.Integer(), sa.ForeignKey("run_items.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("request_messages_json", sa.JSON(), nullable=False),
        sa.Column("streamed_text", sa.Text(), nullable=True),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("raw_provider_payload_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_outputs_id", "outputs", ["id"])

    op.create_table(
        "metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_item_id", sa.Integer(), sa.ForeignKey("run_items.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("generation_ms", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens_estimated", sa.Boolean(), nullable=False),
        sa.Column("tokens_per_sec", sa.Float(), nullable=True),
        sa.Column("error_flag", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_metrics_id", "metrics", ["id"])

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_item_id", sa.Integer(), sa.ForeignKey("run_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("loop_index", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("args_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_style", sa.String(length=32), nullable=False),
    )
    op.create_index("ix_tool_calls_id", "tool_calls", ["id"])

    op.create_table(
        "judge_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_item_id_nullable", sa.Integer(), sa.ForeignKey("run_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("car_id_nullable", sa.Integer(), sa.ForeignKey("cars.id", ondelete="SET NULL"), nullable=True),
        sa.Column("writing_score", sa.Float(), nullable=False),
        sa.Column("coding_score", sa.Float(), nullable=False),
        sa.Column("tool_score", sa.Float(), nullable=False),
        sa.Column("overall", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_judge_results_id", "judge_results", ["id"])

    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_item_id_nullable", sa.Integer(), sa.ForeignKey("run_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("seq_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_telemetry_events_id", "telemetry_events", ["id"])
    op.create_index("ix_telemetry_events_run_id", "telemetry_events", ["run_id"])
    op.create_index("ix_telemetry_events_seq_no", "telemetry_events", ["seq_no"])


def downgrade() -> None:
    op.drop_index("ix_telemetry_events_seq_no", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_run_id", table_name="telemetry_events")
    op.drop_index("ix_telemetry_events_id", table_name="telemetry_events")
    op.drop_table("telemetry_events")

    op.drop_index("ix_judge_results_id", table_name="judge_results")
    op.drop_table("judge_results")

    op.drop_index("ix_tool_calls_id", table_name="tool_calls")
    op.drop_table("tool_calls")

    op.drop_index("ix_metrics_id", table_name="metrics")
    op.drop_table("metrics")

    op.drop_index("ix_outputs_id", table_name="outputs")
    op.drop_table("outputs")

    op.drop_index("ix_run_items_id", table_name="run_items")
    op.drop_table("run_items")

    op.drop_index("ix_runs_id", table_name="runs")
    op.drop_table("runs")

    op.drop_index("ix_tests_id", table_name="tests")
    op.drop_table("tests")

    op.drop_index("ix_suites_id", table_name="suites")
    op.drop_table("suites")

    op.drop_index("ix_cars_id", table_name="cars")
    op.drop_table("cars")

    op.drop_index("ix_provider_settings_id", table_name="provider_settings")
    op.drop_table("provider_settings")

    op.drop_index("ix_connections_id", table_name="connections")
    op.drop_table("connections")

    run_item_status_enum.drop(op.get_bind(), checkfirst=False)
    run_status_enum.drop(op.get_bind(), checkfirst=False)
    connection_enum.drop(op.get_bind(), checkfirst=False)
