from fastapi import Request

from app.runs.executor import RaceExecutor


def get_executor(request: Request) -> RaceExecutor:
    return request.app.state.executor
