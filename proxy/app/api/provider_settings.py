from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderSettings
from app.db.session import get_db
from app.schemas import ProviderSettingOut, ProviderSettingsUpdate

router = APIRouter(prefix="/api/settings/providers", tags=["settings"])


@router.get("", response_model=list[ProviderSettingOut])
def list_provider_settings(db: Session = Depends(get_db)) -> list[ProviderSettings]:
    return list(db.scalars(select(ProviderSettings)))


@router.put("", response_model=list[ProviderSettingOut])
def update_provider_settings(payload: ProviderSettingsUpdate, db: Session = Depends(get_db)) -> list[ProviderSettings]:
    for item in payload.items:
        row = db.scalar(select(ProviderSettings).where(ProviderSettings.provider_type == item.provider_type))
        if not row:
            row = ProviderSettings(
                provider_type=item.provider_type,
                max_in_flight=item.max_in_flight or 1,
                timeout_ms=item.timeout_ms or 90000,
                retry_count=item.retry_count or 1,
                retry_backoff_ms=item.retry_backoff_ms or 500,
            )
            db.add(row)
        else:
            if item.max_in_flight is not None:
                row.max_in_flight = item.max_in_flight
            if item.timeout_ms is not None:
                row.timeout_ms = item.timeout_ms
            if item.retry_count is not None:
                row.retry_count = item.retry_count
            if item.retry_backoff_ms is not None:
                row.retry_backoff_ms = item.retry_backoff_ms

    db.commit()
    return list(db.scalars(select(ProviderSettings)))
