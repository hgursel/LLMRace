from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import encrypt_secret
from app.db.models import Connection
from app.db.session import get_db
from app.providers.adapters import ProviderClient
from app.schemas import (
    ConnectionCreate,
    ConnectionRuntimeCheckResponse,
    ConnectionOut,
    ConnectionTestResponse,
    ConnectionUpdate,
)

router = APIRouter(prefix="/api/connections", tags=["connections"])
provider_client = ProviderClient()


def _to_connection_out(connection: Connection) -> ConnectionOut:
    data = ConnectionOut.model_validate(connection)
    data.has_stored_api_key = bool(connection.api_key_encrypted)
    return data


@router.get("", response_model=list[ConnectionOut])
def list_connections(db: Session = Depends(get_db)) -> list[ConnectionOut]:
    rows = list(db.scalars(select(Connection).order_by(Connection.created_at.desc())))
    return [_to_connection_out(row) for row in rows]


@router.post("", response_model=ConnectionOut)
def create_connection(payload: ConnectionCreate, db: Session = Depends(get_db)) -> ConnectionOut:
    values = payload.model_dump(exclude={"api_key"})
    if payload.api_key:
        values["api_key_encrypted"] = encrypt_secret(payload.api_key)
    connection = Connection(**values)
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return _to_connection_out(connection)


@router.get("/{connection_id}", response_model=ConnectionOut)
def get_connection(connection_id: int, db: Session = Depends(get_db)) -> ConnectionOut:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    return _to_connection_out(connection)


@router.put("/{connection_id}", response_model=ConnectionOut)
def update_connection(
    connection_id: int,
    payload: ConnectionUpdate,
    db: Session = Depends(get_db),
) -> ConnectionOut:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    updates = payload.model_dump(exclude_unset=True, exclude={"api_key", "clear_api_key"})
    for key, value in updates.items():
        setattr(connection, key, value)
    if payload.api_key is not None:
        connection.api_key_encrypted = encrypt_secret(payload.api_key) if payload.api_key else None
    if payload.clear_api_key:
        connection.api_key_encrypted = None

    db.commit()
    db.refresh(connection)
    return _to_connection_out(connection)


@router.delete("/{connection_id}")
def delete_connection(connection_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    db.delete(connection)
    db.commit()
    return {"status": "deleted"}


@router.get("/{connection_id}/models", response_model=list[str])
async def discover_models(connection_id: int, db: Session = Depends(get_db)) -> list[str]:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    try:
        return await provider_client.discover_models(connection)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Model discovery failed: {exc}") from exc


@router.post("/{connection_id}/test", response_model=ConnectionTestResponse)
async def test_connection(connection_id: int, db: Session = Depends(get_db)) -> ConnectionTestResponse:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    ok, latency_ms, models, error = await provider_client.test_connection(connection)
    return ConnectionTestResponse(ok=ok, latency_ms=latency_ms, models=models, error=error)


@router.post("/{connection_id}/verify-runtime", response_model=ConnectionRuntimeCheckResponse)
async def verify_runtime(connection_id: int, db: Session = Depends(get_db)) -> ConnectionRuntimeCheckResponse:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    payload = await provider_client.verify_runtime(connection)
    return ConnectionRuntimeCheckResponse(**payload)
