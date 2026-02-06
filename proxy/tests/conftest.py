from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ['DATABASE_URL'] = 'sqlite:////app/test_llmrace.db'


@pytest.fixture()
def client() -> TestClient:
    from app.db.base import Base
    from app.db.session import engine
    from app.main import create_app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
