from __future__ import annotations

from app.runs.assertions import evaluate_expected_constraints


def test_assertions_contains_regex_and_max_words() -> None:
    constraints = "contains:Hello;regex:^Hello;max_words:3"
    result = evaluate_expected_constraints(constraints, "Hello world")
    assert result["total"] == 3
    assert result["passed"] == 3


def test_assertions_failures_and_unsupported() -> None:
    constraints = "contains:Alpha;not_contains:world;unknown_check:abc"
    result = evaluate_expected_constraints(constraints, "Hello world")
    assert result["total"] == 3
    assert result["passed"] == 0
    assert any(row["type"] == "unknown_check" and row["passed"] is False for row in result["results"])
