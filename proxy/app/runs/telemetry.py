from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import TelemetryEvent


def emit_event(
    db: Session,
    run_id: int,
    event_type: str,
    payload: dict[str, Any],
    run_item_id: int | None = None,
) -> TelemetryEvent:
    max_seq = db.scalar(select(func.max(TelemetryEvent.seq_no)).where(TelemetryEvent.run_id == run_id)) or 0
    event = TelemetryEvent(
        run_id=run_id,
        run_item_id_nullable=run_item_id,
        seq_no=max_seq + 1,
        event_type=event_type,
        payload_json={
            **payload,
            "timestamp": datetime.utcnow().isoformat(),
            "run_id": run_id,
            "run_item_id": run_item_id,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_events_after(db: Session, run_id: int, after_seq: int) -> list[TelemetryEvent]:
    return list(
        db.scalars(
            select(TelemetryEvent)
            .where(TelemetryEvent.run_id == run_id, TelemetryEvent.seq_no > after_seq)
            .order_by(TelemetryEvent.seq_no.asc())
        )
    )
