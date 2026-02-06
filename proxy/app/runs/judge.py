from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class JudgePayload(BaseModel):
    writing_score: float = Field(ge=0, le=10)
    coding_score: float = Field(ge=0, le=10)
    tool_score: float = Field(ge=0, le=10)
    overall: float = Field(ge=0, le=10)
    rationale: str


def build_judge_messages(test_name: str, prompt: str, output_text: str) -> list[dict[str, str]]:
    rubric = (
        "You are an LLM judge. Score output quality in strict JSON only. "
        "Scores are 0-10. Be deterministic and concise."
    )
    user = (
        f"Test Name: {test_name}\n"
        f"Prompt: {prompt}\n"
        f"Model Output:\n{output_text}\n\n"
        "Return JSON with keys: writing_score, coding_score, tool_score, overall, rationale."
    )
    return [
        {"role": "system", "content": rubric},
        {"role": "user", "content": user},
    ]


def parse_judge_json(raw_text: str) -> dict[str, Any]:
    stripped = raw_text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        payload = json.loads(stripped)
        return JudgePayload.model_validate(payload).model_dump()

    # Recover from wrappers like markdown fences.
    match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
    if not match:
        raise ValidationError.from_exception_data("JudgePayload", [])

    payload = json.loads(match.group(0))
    return JudgePayload.model_validate(payload).model_dump()
