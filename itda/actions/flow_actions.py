"""흐름 계열 액션 — 대기, 조건, 플로우 호출, 상태 이동, 중단."""

from __future__ import annotations

from itda.core.registry import ActionType, register_action
from itda.core.schema import Field


@register_action
class Sleep(ActionType):
    ID = "sleep"
    LABEL = "대기"
    CATEGORY = "흐름"
    COLOR = "#6b7383"
    ICON = "⏸"
    PARAMS = [
        Field("ms", "int", "대기 시간", 500, minimum=0, maximum=3600000, suffix=" ms"),
        Field("jitter_pct", "float", "변동계수(-1=상속)", -1.0, minimum=-1.0, maximum=1.0, step=0.05),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        j = params.get("jitter_pct", -1.0)
        tail = "" if j is None or j < 0 else f" ±{int(j * 100)}%"
        return f"{params.get('ms', 0)}ms 대기{tail}"


@register_action
class IfAction(ActionType):
    ID = "if"
    LABEL = "조건 (내부 중단)"
    CATEGORY = "흐름"
    COLOR = "#6b7383"
    ICON = "◇"
    HELP = "식이 거짓이면 이 노드의 남은 액션을 건너뜁니다. 그래프 분기는 분기 노드를 쓰세요."
    PARAMS = [
        Field("expr", "expr", "조건식", ""),
        Field(
            "on_false",
            "enum",
            "거짓일 때",
            "skip_rest",
            options=[("skip_rest", "남은 액션 건너뛰기"), ("fail", "노드를 실패 처리"), ("continue", "그냥 진행")],
        ),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        return f"조건: {params.get('expr') or '(비어 있음)'}"


@register_action
class RunFlow(ActionType):
    ID = "run_flow"
    LABEL = "플로우 실행"
    CATEGORY = "흐름"
    COLOR = "#3f8f8f"
    ICON = "⧉"
    HELP = "파일로 만들어진 매크로를 모듈처럼 불러 실행합니다."
    HAS_OUTPUT = True
    PARAMS = [
        Field("flow", "flow_ref", "대상 플로우", ""),
        Field("args", "text", "인자 (name=value 줄단위)", ""),
        Field("wait", "bool", "끝날 때까지 대기", True),
        Field("priority", "int", "우선순위(비동기일 때)", 0, minimum=-10, maximum=10,
              depends_on=("wait", False)),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        mode = "동기" if params.get("wait", True) else "비동기"
        return f"플로우 '{params.get('flow') or '?'}' 실행 ({mode})"


@register_action
class GoToState(ActionType):
    ID = "goto_state"
    LABEL = "상황으로 이동"
    CATEGORY = "흐름"
    COLOR = "#ee7f63"
    ICON = "⚑"
    HELP = "전이 그래프를 따라 타겟 프로그램을 지정한 상황으로 옮깁니다."
    HAS_OUTPUT = True
    PARAMS = [
        Field("target_state", "state_ref", "목표 상황", ""),
        Field("timeout_ms", "int", "제한시간", 10000, minimum=0, maximum=600000, suffix=" ms"),
        Field("required", "bool", "실패하면 노드 실패 처리", True),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        return f"'{params.get('target_state') or '?'}' 상황으로 이동"


@register_action
class WaitState(ActionType):
    ID = "wait_state"
    LABEL = "상황 대기"
    CATEGORY = "흐름"
    COLOR = "#ee7f63"
    ICON = "⌛"
    HAS_OUTPUT = True
    PARAMS = [
        Field("target_state", "state_ref", "기다릴 상황", ""),
        Field("timeout_ms", "int", "제한시간", 10000, minimum=0, maximum=600000, suffix=" ms"),
        Field("poll_ms", "int", "확인 간격", 300, minimum=10, maximum=60000, suffix=" ms"),
        Field("required", "bool", "시간 초과 시 실패 처리", True),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        return f"'{params.get('target_state') or '?'}' 상황이 될 때까지 대기"


@register_action
class StopFlow(ActionType):
    ID = "stop"
    LABEL = "중단"
    CATEGORY = "흐름"
    COLOR = "#e05a54"
    ICON = "■"
    PARAMS = [
        Field(
            "scope",
            "enum",
            "범위",
            "flow",
            options=[("flow", "이 플로우만"), ("all", "실행 중인 전부")],
        ),
        Field("reason", "str", "사유", ""),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        return "전체 중단" if params.get("scope") == "all" else "이 플로우 중단"
