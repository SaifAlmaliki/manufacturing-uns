import ast

import pytest

from uns_simulator.expressions import ExpressionError, compile_expression


def test_arithmetic_and_precedence():
    assert compile_expression("2 + 3 * 4").evaluate({}) == 14


def test_reads_names_from_namespace():
    expr = compile_expression("flow * density")
    assert expr.evaluate({"flow": 10.0, "density": 1.2}) == pytest.approx(12.0)


def test_reports_free_variables():
    assert compile_expression("a + b * ctx.ambient_temp_c").names == frozenset({"a", "b", "ctx"})


@pytest.mark.parametrize(
    "source",
    [
        "__import__('os').system('echo hi')",
        "().__class__.__bases__",
        "flow._secret",
        "[i for i in range(10)]",
        "lambda: 1",
        "open('/etc/passwd')",
        "(1).__class__",
        "f'{flow}'",
    ],
)
def test_rejects_dangerous_source(source):
    with pytest.raises(ExpressionError):
        compile_expression(source)


def test_rejects_unknown_function():
    with pytest.raises(ExpressionError, match="whitelisted function"):
        compile_expression("eval('1')").evaluate({})


def test_rejects_unknown_name_at_evaluation():
    with pytest.raises(ExpressionError, match="unknown name"):
        compile_expression("missing + 1").evaluate({})


def test_whitelisted_helpers_work():
    assert compile_expression("clamp(120, 0, 100)").evaluate({}) == 100
    assert compile_expression("sqrt(x)").evaluate({"x": 9.0}) == pytest.approx(3.0)
    assert compile_expression("a if a > b else b").evaluate({"a": 1, "b": 5}) == 5


def test_attribute_access_on_context_object_works():
    class View:
        ambient_temp_c = 21.5

    assert compile_expression("ctx.ambient_temp_c * 2").evaluate({"ctx": View()}) == pytest.approx(43.0)


def test_module_source_contains_no_eval_or_exec():
    from pathlib import Path

    import uns_simulator.expressions as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "eval" not in called
    assert "exec" not in called
