from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Suite, TestCase
from app.db.session import get_db
from app.schemas import SuiteCreate, SuiteOut, SuiteUpdate

router = APIRouter(prefix="/api/suites", tags=["suites"])


def _get_suite(db: Session, suite_id: int) -> Suite | None:
    return db.scalar(
        select(Suite)
        .options(selectinload(Suite.tests))
        .where(Suite.id == suite_id)
    )


@router.get("", response_model=list[SuiteOut])
def list_suites(db: Session = Depends(get_db)) -> list[Suite]:
    return list(db.scalars(select(Suite).options(selectinload(Suite.tests)).order_by(Suite.created_at.desc())))


@router.post("", response_model=SuiteOut)
def create_suite(payload: SuiteCreate, db: Session = Depends(get_db)) -> Suite:
    suite = Suite(name=payload.name, category=payload.category, description=payload.description, is_demo=False)
    db.add(suite)
    db.flush()

    for test in payload.tests:
        db.add(TestCase(suite_id=suite.id, **test.model_dump()))

    db.commit()
    return _get_suite(db, suite.id)  # type: ignore[return-value]


@router.get("/{suite_id}", response_model=SuiteOut)
def get_suite(suite_id: int, db: Session = Depends(get_db)) -> Suite:
    suite = _get_suite(db, suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


@router.put("/{suite_id}", response_model=SuiteOut)
def update_suite(suite_id: int, payload: SuiteUpdate, db: Session = Depends(get_db)) -> Suite:
    suite = db.get(Suite, suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    updates = payload.model_dump(exclude_unset=True, exclude={"tests"})
    for key, value in updates.items():
        setattr(suite, key, value)

    if payload.tests is not None:
        db.execute(delete(TestCase).where(TestCase.suite_id == suite_id))
        for test in payload.tests:
            db.add(TestCase(suite_id=suite_id, **test.model_dump()))

    db.commit()
    return _get_suite(db, suite_id)  # type: ignore[return-value]


@router.delete("/{suite_id}")
def delete_suite(suite_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    suite = db.get(Suite, suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    db.delete(suite)
    db.commit()
    return {"status": "deleted"}
