from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Connection
from app.db.session import get_db
from app.providers.adapters import ProviderClient
from app.schemas import (
    ConnectionCreate,
    ConnectionOut,
    ConnectionTestResponse,
    ConnectionUpdate,
)

router = APIRouter(prefix="/api/connections", tags=["connections"])
provider_client = ProviderClient()


@router.get("", response_model=list[ConnectionOut])
def list_connections(db: Session = Depends(get_db)) -> list[Connection]:
    return list(db.scalars(select(Connection).order_by(Connection.created_at.desc())))


@router.post("", response_model=ConnectionOut)
def create_connection(payload: ConnectionCreate, db: Session = Depends(get_db)) -> Connection:
    connection = Connection(**payload.model_dump())
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


@router.get("/{connection_id}", response_model=ConnectionOut)
def get_connection(connection_id: int, db: Session = Depends(get_db)) -> Connection:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


@router.put("/{connection_id}", response_model=ConnectionOut)
def update_connection(
    connection_id: int,
    payload: ConnectionUpdate,
    db: Session = Depends(get_db),
) -> Connection:
    connection = db.get(Connection, connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(connection, key, value)

    db.commit()
    db.refresh(connection)
    return connection


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
