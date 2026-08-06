"""A single safe calculator exposed to the ReAct agent."""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass, field
from typing import Any


def _safe_calculate(expression: str) -> int | float:
    """Evaluate numeric arithmetic and the three-argument modular ``pow`` only."""

    binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    unary_ops = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def visit(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id != "pow":
                raise ValueError("Only pow(base, exponent, modulus) is allowed")
            if node.keywords or len(node.args) != 3:
                raise ValueError("Use exactly pow(base, exponent, modulus)")
            base, exponent, modulus = (visit(arg) for arg in node.args)
            if not all(isinstance(value, int) for value in (base, exponent, modulus)):
                raise ValueError("pow arguments must be integers")
            if exponent < 0 or exponent > 10**9:
                raise ValueError("Exponent is outside the safe range")
            if modulus <= 0 or modulus > 10**12:
                raise ValueError("Modulus is outside the safe range")
            if abs(base) > 10**12:
                raise ValueError("Base is outside the safe range")
            return pow(base, exponent, modulus)
        if isinstance(node, ast.BinOp) and type(node.op) in binary_ops:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise ValueError("For large powers, use pow(base, exponent, modulus)")
            value = binary_ops[type(node.op)](left, right)
            if abs(value) > 10**15:
                raise ValueError("Intermediate result is too large")
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in unary_ops:
            return unary_ops[type(node.op)](visit(node.operand))
        raise ValueError("Only numeric arithmetic is allowed")

    if len(expression) > 240:
        raise ValueError("Expression is too long")
    return visit(ast.parse(expression, mode="eval"))


@dataclass
class ToolEnvironment:
    """Calculator environment with an auditable action history."""

    history: list[dict[str, Any]] = field(default_factory=list)

    def calculate(self, expression: str) -> str:
        expression = expression.strip().strip("`")
        expression = expression.replace("×", "*").replace("÷", "/")
        expression = re.sub(r"\bmod\b", "%", expression, flags=re.IGNORECASE)
        # Weak models often use the conventional mathematical caret notation
        # even after being shown Python's three-argument pow form. Convert only
        # the tightly constrained modular-power pattern; a general caret still
        # remains invalid rather than being interpreted as code.
        modular_power = re.fullmatch(
            r"\s*([+-]?\d+)\s*\^\s*(\d+)\s*%\s*(\d+)\s*",
            expression,
        )
        if modular_power:
            base, exponent, modulus = modular_power.groups()
            expression = f"pow({base},{exponent},{modulus})"
        try:
            value = _safe_calculate(expression)
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            result = str(value)
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as exc:
            result = f"Calculation error: {exc}"
        self.history.append({"tool": "calculate", "input": expression, "output": result})
        return result

    def execute(self, tool_name: str, argument: str) -> str:
        if tool_name.lower() == "calculate":
            return self.calculate(argument)
        return f"Unknown tool: {tool_name}. Allowed tools: Calculate, Finish."
