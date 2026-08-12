"""변수 / 식 평가 테스트 — 특히 안전성."""

from __future__ import annotations

import pytest

from itda.core.variables import (
    ExpressionError,
    VariableStore,
    cast_value,
    interpolate,
    referenced_names,
    safe_eval,
)


def test_arithmetic_and_comparison():
    assert safe_eval("1 + 2 * 3") == 7
    assert safe_eval("count + 1", {"count": 41}) == 42
    assert safe_eval("score >= 90", {"score": 95}) is True
    assert safe_eval("a and b", {"a": True, "b": False}) is False


def test_string_helpers():
    assert safe_eval('upper("hi")') == "HI"
    assert safe_eval('contains(text, "로그인")', {"text": "로그인 화면"}) is True
    assert safe_eval('digits("가격: 1,200원")') == "1200"


def test_empty_expression_is_empty_string():
    assert safe_eval("") == ""
    assert safe_eval("   ") == ""


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('calc')",
        "open('secret.txt').read()",
        "(1).__class__",
        "[].__class__.__base__",
        "lambda: 1",
        "print('x')",
    ],
)
def test_dangerous_expressions_are_rejected(expr):
    with pytest.raises(ExpressionError):
        safe_eval(expr)


def test_slicing_is_supported():
    """a[1:3] 은 Subscript(slice=Slice(...)) 로 파싱된다 — 이 갈래가 없으면 전부 거부된다."""
    assert safe_eval("items[1:3]", {"items": [10, 20, 30, 40]}) == [20, 30]
    assert safe_eval("text[:3]", {"text": "가나다라"}) == "가나다"
    assert safe_eval("text[-2:]", {"text": "abcdef"}) == "ef"
    assert safe_eval("items[::2]", {"items": [1, 2, 3, 4, 5]}) == [1, 3, 5]


def test_interpolation_handles_braces_inside_the_expression():
    """식 안의 중괄호에서 잘리면 안 된다."""
    assert interpolate("${ {'key': 100}['key'] }") == "100"
    assert interpolate("값은 ${ {'a': 1, 'b': 2}['b'] } 입니다") == "값은 2 입니다"


def test_interpolation_handles_braces_inside_strings():
    assert interpolate("${ '}' }") == "}"
    assert interpolate("${ \"a}b\" }") == "a}b"


def test_unclosed_placeholder_is_left_alone():
    assert interpolate("${name") == "${name"
    assert interpolate("앞 ${a} 뒤 ${b", {"a": 1}) == "앞 1 뒤 ${b"


def test_multiple_placeholders_in_one_string():
    assert interpolate("${a}-${b}-${a}", {"a": "x", "b": "y"}) == "x-y-x"


def test_unknown_variable_raises():
    with pytest.raises(ExpressionError):
        safe_eval("nope + 1")


def test_interpolation_replaces_and_survives_bad_expressions():
    assert interpolate("안녕 ${name}님", {"name": "홍길동"}) == "안녕 홍길동님"
    assert interpolate("남은 ${count - 1}개", {"count": 5}) == "남은 4개"
    # 편집 중인 깨진 식은 원문을 유지한다 (에디터에서 죽지 않게)
    assert interpolate("${없는변수}") == "${없는변수}"
    assert interpolate("변수 없음") == "변수 없음"


def test_referenced_names_finds_variables():
    assert referenced_names("${a + b}") == ["a", "b"]
    assert referenced_names("count * 2") == ["count"]
    assert "upper" not in referenced_names('upper(name)')


def test_variable_store_scopes():
    store = VariableStore()
    store.set("shared", 1, scope="global")
    store.set("local", 2)
    assert store.get("shared") == 1
    assert store.snapshot() == {"shared": 1, "local": 2}

    store.set("shared", 99)  # 같은 이름의 플로우 변수가 전역을 가린다
    assert store.get("shared") == 99
    assert store.globals["shared"] == 1
    assert store.eval("shared + local") == 101
    assert store.format("값=${shared}") == "값=99"


@pytest.mark.parametrize(
    "raw,type_name,expected",
    [
        ("12", "int", 12),
        ("12.5", "float", 12.5),
        ("참", "bool", True),
        ("false", "bool", False),
        ("", "int", 0),
        ("이상한값", "int", 0),
        ("글자", "str", "글자"),
    ],
)
def test_cast_value(raw, type_name, expected):
    assert cast_value(raw, type_name) == expected
