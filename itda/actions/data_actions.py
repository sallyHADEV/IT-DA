"""데이터 계열 액션 — 변수와 연산, 클립보드."""

from __future__ import annotations

from itda.core.registry import ActionType, register_action
from itda.core.schema import Field


@register_action
class SetVar(ActionType):
    ID = "set_var"
    LABEL = "변수 지정"
    CATEGORY = "데이터"
    COLOR = "#7a6ba8"
    ICON = "="
    PARAMS = [
        Field("name", "var", "변수 이름", ""),
        Field(
            "scope",
            "enum",
            "범위",
            "flow",
            options=[("flow", "이 플로우"), ("global", "전역(플로우 간 공유)")],
        ),
        Field("value", "expr", "값 / 식", "", help="숫자, \"글자\", ${다른변수}, count + 1 모두 가능"),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        return f"{params.get('name') or '?'} = {params.get('value') or ''}"


@register_action
class Calc(ActionType):
    ID = "calc"
    LABEL = "연산"
    CATEGORY = "데이터"
    COLOR = "#7a6ba8"
    ICON = "±"
    HAS_OUTPUT = True
    PARAMS = [
        Field("name", "var", "대상 변수", ""),
        Field(
            "op",
            "enum",
            "연산",
            "add",
            options=[("add", "+"), ("sub", "−"), ("mul", "×"), ("div", "÷"), ("mod", "나머지"), ("set", "대입")],
        ),
        Field("operand", "expr", "피연산자", "1"),
        Field("clamp", "bool", "범위 제한 사용", False),
        Field("min", "float", "최소", 0.0, depends_on=("clamp", True)),
        Field("max", "float", "최대", 100.0, depends_on=("clamp", True)),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        sym = {"add": "+=", "sub": "-=", "mul": "*=", "div": "/=", "mod": "%=", "set": "="}
        return f"{params.get('name') or '?'} {sym.get(params.get('op', 'add'), '?')} {params.get('operand', '')}"


@register_action
class Clipboard(ActionType):
    ID = "clipboard"
    LABEL = "클립보드"
    CATEGORY = "데이터"
    COLOR = "#7a6ba8"
    ICON = "📋"
    HAS_OUTPUT = True
    PARAMS = [
        Field(
            "mode",
            "enum",
            "동작",
            "read",
            options=[("read", "읽어서 변수에 담기"), ("write", "값을 클립보드에 넣기")],
        ),
        Field("value", "expr", "넣을 값", "", depends_on=("mode", "write")),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        return "클립보드 읽기" if params.get("mode") == "read" else "클립보드에 쓰기"


@register_action
class Log(ActionType):
    ID = "log"
    LABEL = "로그"
    CATEGORY = "데이터"
    COLOR = "#6b7383"
    ICON = "✎"
    PARAMS = [
        Field("message", "str", "메시지", "", help="${변수} 사용 가능"),
        Field(
            "level",
            "enum",
            "수준",
            "info",
            options=[("debug", "디버그"), ("info", "정보"), ("warn", "경고"), ("error", "오류")],
        ),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        return f"로그: {params.get('message') or ''}"
