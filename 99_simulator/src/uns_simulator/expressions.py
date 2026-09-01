"""Evaluate small arithmetic expressions from YAML without executing arbitrary code.

`eval()` on configuration is a remote-code-execution hole even when the configuration is
trusted today, so this module walks a whitelisted AST instead. Anything not explicitly
allowed raises ExpressionError at compile time, before any value is produced.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Mapping
from typing import Any, Final


class ExpressionError(ValueError):
    """An expression could not be compiled or could not be evaluated."""


_BIN_OPS: Final = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: Final = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
_COMPARE_OPS: Final = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
# Exactly the seven calls spec 5.4 permits - no more.
_FUNCTIONS: Final = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "clamp": lambda value, low, high: max(low, min(high, value)),
    "sqrt": math.sqrt,
    "exp": math.exp,
}
ATTRIBUTE_ROOT: Final = "ctx"
_ALLOWED_NODES: Final = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Attribute,
    ast.And,
    ast.Or,
    *_BIN_OPS,
    *_UNARY_OPS,
    *_COMPARE_OPS,
)


class CompiledExpression:
    """A validated expression, reusable across ticks."""

    __slots__ = ("_tree", "names", "source")

    def __init__(self, source: str, tree: ast.Expression, names: frozenset[str]) -> None:
        self.source = source
        self._tree = tree
        self.names = names

    def evaluate(self, namespace: Mapping[str, Any]) -> Any:
        try:
            return _eval_node(self._tree.body, namespace)
        except ExpressionError:
            raise
        except Exception as exc:
            raise ExpressionError(f"evaluating {self.source!r} failed: {exc}") from exc

    def __repr__(self) -> str:
        return f"CompiledExpression({self.source!r})"


def compile_expression(source: str) -> CompiledExpression:
    """Parse and validate `source`, rejecting anything outside the whitelist."""
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"{source!r} is not a valid expression: {exc.msg}") from exc

    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"{type(node).__name__} is not allowed in {source!r}")
        if isinstance(node, ast.Attribute):
            # Spec 5.4: attribute access is permitted on the `ctx` root only. Allowing it
            # anywhere would reopen the `().__class__.__bases__` route to arbitrary objects.
            # Nested hops (`ctx.line.production_rate`) are allowed so long as the chain
            # bottoms out at `ctx` and no private attribute is named.
            current = node
            while isinstance(current, ast.Attribute):
                if current.attr.startswith("_"):
                    raise ExpressionError(f"private attribute {current.attr!r} is not allowed in {source!r}")
                current = current.value
            if not (isinstance(current, ast.Name) and current.id == ATTRIBUTE_ROOT):
                raise ExpressionError(f"attribute access is only allowed on {ATTRIBUTE_ROOT!r} in {source!r}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ExpressionError(f"only direct calls to whitelisted functions are allowed in {source!r}")
            if node.func.id not in _FUNCTIONS:
                raise ExpressionError(f"{node.func.id!r} is not a whitelisted function")
        if isinstance(node, ast.Name) and node.id not in _FUNCTIONS:
            names.add(node.id)
    return CompiledExpression(source, tree, frozenset(names))


def _eval_node(node: ast.AST, ns: Mapping[str, Any]) -> Any:  # ruff: ignore[complex-structure]
    match node:
        case ast.Constant(value=value):
            return value
        case ast.Name(id=name):
            if name in ns:
                return ns[name]
            if name in _FUNCTIONS:
                return _FUNCTIONS[name]
            raise ExpressionError(f"unknown name {name!r}")
        case ast.Attribute(value=value, attr=attr):
            target = _eval_node(value, ns)
            try:
                return getattr(target, attr)
            except AttributeError as exc:
                raise ExpressionError(f"{type(target).__name__} has no attribute {attr!r}") from exc
        case ast.BinOp(left=left, op=op, right=right):
            return _BIN_OPS[type(op)](_eval_node(left, ns), _eval_node(right, ns))
        case ast.UnaryOp(op=op, operand=operand):
            return _UNARY_OPS[type(op)](_eval_node(operand, ns))
        case ast.BoolOp(op=op, values=values):
            evaluated = [_eval_node(value, ns) for value in values]
            return all(evaluated) if isinstance(op, ast.And) else any(evaluated)
        case ast.Compare(left=left, ops=ops, comparators=comparators):
            current = _eval_node(left, ns)
            for op, comparator in zip(ops, comparators, strict=True):
                right = _eval_node(comparator, ns)
                if not _COMPARE_OPS[type(op)](current, right):
                    return False
                current = right
            return True
        case ast.IfExp(test=test, body=body, orelse=orelse):
            return _eval_node(body if _eval_node(test, ns) else orelse, ns)
        case ast.Call(func=ast.Name(id=name), args=args, keywords=keywords):
            if keywords:
                raise ExpressionError(f"keyword arguments are not allowed in a call to {name!r}")
            if name not in _FUNCTIONS:
                raise ExpressionError(f"{name!r} is not a whitelisted function")
            return _FUNCTIONS[name](*[_eval_node(arg, ns) for arg in args])
        case _:
            raise ExpressionError(f"{type(node).__name__} is not supported")
