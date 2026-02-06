from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Car, Connection
from app.db.session import get_db
from app.schemas import CarCreate, CarOut, CarUpdate

router = APIRouter(prefix="/api/cars", tags=["cars"])


@router.get("", response_model=list[CarOut])
def list_cars(db: Session = Depends(get_db)) -> list[Car]:
    return list(db.scalars(select(Car).order_by(Car.created_at.desc())))


@router.post("", response_model=CarOut)
def create_car(payload: CarCreate, db: Session = Depends(get_db)) -> Car:
    connection = db.get(Connection, payload.connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    car = Car(**payload.model_dump())
    db.add(car)
    db.commit()
    db.refresh(car)
    return car


@router.get("/{car_id}", response_model=CarOut)
def get_car(car_id: int, db: Session = Depends(get_db)) -> Car:
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")
    return car


@router.put("/{car_id}", response_model=CarOut)
def update_car(car_id: int, payload: CarUpdate, db: Session = Depends(get_db)) -> Car:
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    updates = payload.model_dump(exclude_unset=True)
    if "connection_id" in updates:
        connection = db.get(Connection, updates["connection_id"])
        if not connection:
            raise HTTPException(status_code=404, detail="Connection not found")

    for key, value in updates.items():
        setattr(car, key, value)

    db.commit()
    db.refresh(car)
    return car


@router.delete("/{car_id}")
def delete_car(car_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")
    db.delete(car)
    db.commit()
    return {"status": "deleted"}
