"""Safe calculator carried over from 01Introduction/tools.py.

Lesson 1 built this as the agent's only tool. Lesson 2 keeps it unchanged and
registers it alongside the new file tools — the first concrete payoff of giving
tools a stable interface instead of hard-coding one.
"""

from __future__ import annotations

import ast
import operator
import re

BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def safe_calculate(expression: str) -> int | float:
    """Evaluate numeric arithmetic and the three-argument modular ``pow`` only."""

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
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPS:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise ValueError("For large powers, use pow(base, exponent, modulus)")
            value = BINARY_OPS[type(node.op)](left, right)
            if abs(value) > 10**15:
                raise ValueError("Intermediate result is too large")
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPS:
            return UNARY_OPS[type(node.op)](visit(node.operand))
        raise ValueError("Only numeric arithmetic is allowed")

    if len(expression) > 240:
        raise ValueError("Expression is too long")
    return visit(ast.parse(expression, mode="eval"))


def normalize_expression(expression: str) -> str:
    """Rewrite the notations weak models reach for into calculator syntax."""

    expression = expression.strip().strip("`")
    expression = expression.replace("×", "*").replace("÷", "/")
    expression = re.sub(r"\bmod\b", "%", expression, flags=re.IGNORECASE)
    modular_power = re.fullmatch(r"\s*([+-]?\d+)\s*\^\s*(\d+)\s*%\s*(\d+)\s*", expression)
    if modular_power:
        base, exponent, modulus = modular_power.groups()
        return f"pow({base},{exponent},{modulus})"
    return expression
