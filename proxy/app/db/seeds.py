from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ConnectionType, ProviderSettings, Suite, TestCase


def seed_provider_settings(db: Session) -> None:
    defaults = {
        ConnectionType.OLLAMA: dict(max_in_flight=1, timeout_ms=90000, retry_count=1, retry_backoff_ms=500),
        ConnectionType.OPENAI: dict(max_in_flight=1, timeout_ms=90000, retry_count=1, retry_backoff_ms=500),
        ConnectionType.ANTHROPIC: dict(max_in_flight=1, timeout_ms=90000, retry_count=1, retry_backoff_ms=500),
        ConnectionType.OPENROUTER: dict(max_in_flight=1, timeout_ms=90000, retry_count=1, retry_backoff_ms=500),
        ConnectionType.OPENAI_COMPAT: dict(max_in_flight=1, timeout_ms=90000, retry_count=1, retry_backoff_ms=500),
        ConnectionType.LLAMACPP_OPENAI: dict(max_in_flight=1, timeout_ms=90000, retry_count=1, retry_backoff_ms=500),
        ConnectionType.CUSTOM: dict(max_in_flight=1, timeout_ms=90000, retry_count=1, retry_backoff_ms=500),
    }

    for provider_type, values in defaults.items():
        existing = db.scalar(
            select(ProviderSettings).where(ProviderSettings.provider_type == provider_type)
        )
        if not existing:
            db.add(ProviderSettings(provider_type=provider_type, **values))
    db.commit()


def seed_demo_suites(db: Session) -> None:
    suite_definitions = [
        {
            "name": "Writing Basic",
            "category": "writing",
            "description": "Core writing prompts for style and clarity.",
            "tests": [
                (1, "Humor Rewrite", None, "Rewrite this sentence to sound playful: 'The deployment finished successfully.'", "Keep it to one sentence.", None),
                (2, "Tone Shift", None, "Turn this urgent note into a calm update: 'Fix this now, production is broken.'", "2-3 sentences.", None),
                (3, "Summary", None, "Summarize this paragraph in 2 bullets: Local model testing helps evaluate speed, quality, and reliability across prompts.", "Return bullet list only.", None),
                (4, "Email Rewrite", None, "Rewrite into a professional email:\nhey team, can u send the numbers asap", "Include greeting and sign-off.", None),
            ],
        },
        {
            "name": "Coding Basic",
            "category": "coding",
            "description": "Everyday coding tasks.",
            "tests": [
                (1, "Bugfix", None, "Fix this Python function: def add(a,b): return a-b", "Return only corrected code.", None),
                (2, "Function", None, "Write a JavaScript function that debounces a callback.", "Include usage example.", None),
                (3, "Refactor", None, "Refactor this pseudo-code for readability: loop i do if x then y end", "Explain key changes briefly.", None),
                (4, "Explain", None, "Explain big-O for binary search to a junior developer.", "Under 120 words.", None),
            ],
        },
        {
            "name": "Tool Calling Basic",
            "category": "tool-calling",
            "description": "Tool use and structured interactions.",
            "tests": [
                (
                    1,
                    "Calculator",
                    "Use tools when needed.",
                    "Compute (17*4)+11 and return concise answer.",
                    "Final answer must include numeric result.",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "calculator",
                                "description": "Evaluate arithmetic expression",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"expression": {"type": "string"}},
                                    "required": ["expression"],
                                },
                            },
                        }
                    ],
                ),
                (
                    2,
                    "JSON Validate",
                    "Use tools when needed.",
                    "Check if this JSON is valid: {\"a\":1,}",
                    "State valid true/false.",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "json_validate",
                                "description": "Validate JSON string",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"json_string": {"type": "string"}},
                                    "required": ["json_string"],
                                },
                            },
                        }
                    ],
                ),
                (
                    3,
                    "Extract Code Blocks",
                    "Use tools when needed.",
                    "Given text: Here is code ```python\nprint(1)\n``` and ```js\nconsole.log(2)\n```, extract the code blocks.",
                    "Return count and each block.",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "extract_code_blocks",
                                "description": "Extract fenced code",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"text": {"type": "string"}},
                                    "required": ["text"],
                                },
                            },
                        }
                    ],
                ),
                (
                    4,
                    "Mixed Tool",
                    "Use tools when needed.",
                    "Validate JSON {'x':1} then calculate 9*9 and report both.",
                    "Explain what tools were used.",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "calculator",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"expression": {"type": "string"}},
                                    "required": ["expression"],
                                },
                            },
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "json_validate",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"json_string": {"type": "string"}},
                                    "required": ["json_string"],
                                },
                            },
                        },
                    ],
                ),
            ],
        },
    ]

    for suite_def in suite_definitions:
        suite = db.scalar(select(Suite).where(Suite.name == suite_def["name"]))
        if suite:
            continue

        suite = Suite(
            name=suite_def["name"],
            category=suite_def["category"],
            description=suite_def["description"],
            is_demo=True,
        )
        db.add(suite)
        db.flush()

        for order_index, name, system_prompt, user_prompt, constraints, tools in suite_def["tests"]:
            db.add(
                TestCase(
                    suite_id=suite.id,
                    order_index=order_index,
                    name=name,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    expected_constraints=constraints,
                    tools_schema_json=tools,
                )
            )

    db.commit()


def seed_all(db: Session) -> None:
    seed_provider_settings(db)
    seed_demo_suites(db)
