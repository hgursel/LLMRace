from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import cars, connections, health, leaderboard, provider_settings, runs, suites
from app.core.settings import get_settings
from app.db.base import Base
from app.db.seeds import seed_all
from app.db.session import SessionLocal, engine
from app.providers.adapters import ProviderClient
from app.runs.executor import RaceExecutor

settings = get_settings()
provider_client = ProviderClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_all(db)

    executor = RaceExecutor(session_factory=SessionLocal, provider_client=provider_client, settings=settings)
    executor.start()
    app.state.executor = executor

    yield
    await executor.stop()

def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(connections.router)
    app.include_router(cars.router)
    app.include_router(suites.router)
    app.include_router(provider_settings.router)
    app.include_router(runs.router)
    app.include_router(leaderboard.router)
    return app

app = create_app()
