from __future__ import annotations

import re
from typing import Any


def _check_max_words(expected: str, output_text: str) -> tuple[bool, str]:
    try:
        max_words = int(expected.strip())
    except ValueError:
        return False, f"invalid max_words value: {expected}"
    words = len([w for w in output_text.split() if w.strip()])
    return words <= max_words, f"words={words}, limit={max_words}"


def _parse_constraints(raw_constraints: str | None) -> list[tuple[str, str]]:
    if not raw_constraints:
        return []
    chunks = [part.strip() for part in re.split(r"[\n;]+", raw_constraints) if part.strip()]
    parsed: list[tuple[str, str]] = []
    for chunk in chunks:
        if ":" not in chunk:
            continue
        name, value = chunk.split(":", 1)
        parsed.append((name.strip().lower(), value.strip()))
    return parsed


def evaluate_expected_constraints(raw_constraints: str | None, output_text: str) -> dict[str, Any]:
    checks = _parse_constraints(raw_constraints)
    if not checks:
        return {"total": 0, "passed": 0, "results": []}

    results: list[dict[str, Any]] = []
    for check_type, expected in checks:
        passed = True
        detail = ""

        if check_type == "contains":
            passed = expected in output_text
            detail = f"contains={passed}"
        elif check_type == "icontains":
            passed = expected.lower() in output_text.lower()
            detail = f"icontains={passed}"
        elif check_type == "not_contains":
            passed = expected not in output_text
            detail = f"not_contains={passed}"
        elif check_type == "regex":
            passed = bool(re.search(expected, output_text, flags=re.MULTILINE))
            detail = f"regex_match={passed}"
        elif check_type == "max_words":
            passed, detail = _check_max_words(expected, output_text)
        else:
            detail = f"unsupported check: {check_type}"
            passed = False

        results.append(
            {
                "type": check_type,
                "expected": expected,
                "passed": passed,
                "detail": detail,
            }
        )

    passed_count = sum(1 for row in results if row["passed"])
    return {
        "total": len(results),
        "passed": passed_count,
        "results": results,
    }
