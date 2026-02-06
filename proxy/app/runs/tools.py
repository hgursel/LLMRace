from __future__ import annotations

import ast
import json
import operator
import re
from typing import Any

_ALLOWED_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_ALLOWED_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class ToolExecutionError(Exception):
    pass


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BIN_OPS:
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return float(_ALLOWED_BIN_OPS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY_OPS:
        return float(_ALLOWED_UNARY_OPS[type(node.op)](_safe_eval(node.operand)))
    raise ToolExecutionError("Unsupported expression")


def calculator(expression: str) -> float:
    try:
        tree = ast.parse(expression, mode="eval")
        return _safe_eval(tree)
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(f"calculator failed: {exc}") from exc


def json_validate(json_string: str) -> dict[str, Any]:
    try:
        json.loads(json_string)
        return {"valid": True}
    except json.JSONDecodeError as exc:
        return {"valid": False, "error": str(exc)}


def extract_code_blocks(text: str) -> list[str]:
    pattern = re.compile(r"```(?:[a-zA-Z0-9_+-]+)?\n(.*?)```", re.DOTALL)
    return [m.strip() for m in pattern.findall(text)]


def execute_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "calculator":
        expression = str(args.get("expression", ""))
        return {"result": calculator(expression)}
    if tool_name == "json_validate":
        return json_validate(str(args.get("json_string", "")))
    if tool_name == "extract_code_blocks":
        return {"blocks": extract_code_blocks(str(args.get("text", "")))}
    raise ToolExecutionError(f"Unknown tool: {tool_name}")


def parse_fallback_tool_command(text: str) -> dict[str, Any] | None:
    # Fallback for models that output a JSON command instead of native tool_calls.
    payload: dict[str, Any] | None = None
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = None

    if payload is None:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            return None

    if payload is None:
        return None

    tool = payload.get("tool")
    args = payload.get("args", {})
    if not isinstance(tool, str) or not isinstance(args, dict):
        return None
    return {"name": tool, "arguments": args}
