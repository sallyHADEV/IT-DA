"""도구 계열 액션 — 경고음, 스크린샷, 창 제어, 외부 실행."""

from __future__ import annotations

from itda.core.registry import ActionType, register_action
from itda.core.schema import Field
from itda.core.window_spec import summarize as window_summary
from itda.core.window_spec import window_params


@register_action
class Beep(ActionType):
    ID = "beep"
    LABEL = "경고음"
    CATEGORY = "도구"
    COLOR = "#b57b45"
    ICON = "🔔"
    HELP = "소리로 알립니다. 사용자가 자리를 비웠을 때 예외 상황을 알리는 용도."
    PARAMS = [
        Field(
            "sound",
            "enum",
            "소리",
            "beep",
            options=[("beep", "기본 비프"), ("asterisk", "알림"), ("exclamation", "경고"), ("critical", "오류"), ("file", "음원 파일")],
        ),
        Field("path", "file", "음원 파일", "", depends_on=("sound", "file")),
        Field("freq", "int", "주파수", 880, minimum=37, maximum=20000, suffix=" Hz",
              depends_on=("sound", "beep")),
        Field("duration_ms", "int", "길이", 300, minimum=10, maximum=10000, suffix=" ms",
              depends_on=("sound", "beep")),
        Field("repeat", "int", "반복", 1, minimum=1, maximum=100),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        if params.get("sound") == "file":
            return f"음원 재생: {params.get('path') or '(미지정)'}"
        return f"경고음 {params.get('freq', 0)}Hz {params.get('duration_ms', 0)}ms"


@register_action
class Screenshot(ActionType):
    ID = "screenshot"
    LABEL = "스크린샷 저장"
    CATEGORY = "도구"
    COLOR = "#b57b45"
    ICON = "📷"
    HAS_OUTPUT = True
    PARAMS = [
        Field(
            "region_mode",
            "enum",
            "범위",
            "full",
            options=[("full", "전체 화면"), ("rect", "지정 영역"), ("window", "지정 창")],
        ),
        Field("region", "rect", "영역", None, depends_on=("region_mode", "rect")),
        Field("window_title", "str", "창 제목", "", depends_on=("region_mode", "window")),
        Field("path", "str", "저장 경로", "captures/${timestamp}.png",
              help="${timestamp} 를 쓰면 시각이 들어갑니다."),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        return f"스크린샷 → {params.get('path') or ''}"


@register_action
class WindowControl(ActionType):
    ID = "window"
    LABEL = "창 제어"
    CATEGORY = "도구"
    COLOR = "#b57b45"
    ICON = "▭"
    HELP = (
        "대상 창을 앞으로 가져오거나 위치·크기를 지정합니다.<br>"
        "창 크기가 실행할 때마다 다르면 안의 버튼 위치도 달라져 좌표와 이미지 검색이 어긋납니다. "
        "그래서 보통 <b>플로우 맨 앞에 창을 정해진 자리·크기로 맞추는 단계</b>를 둡니다."
    )
    HAS_OUTPUT = True
    PARAMS = window_params()

    @classmethod
    def summary(cls, params: dict) -> str:
        return window_summary(params)


@register_action
class RunProgram(ActionType):
    ID = "run_program"
    LABEL = "프로그램 실행"
    CATEGORY = "도구"
    COLOR = "#b57b45"
    ICON = "▶"
    HAS_OUTPUT = True
    PARAMS = [
        Field("path", "file", "실행 파일", ""),
        Field("args", "str", "인자", ""),
        Field("workdir", "str", "작업 폴더", ""),
        Field("wait", "bool", "끝날 때까지 대기", False),
        Field("timeout_ms", "int", "제한시간", 0, minimum=0, maximum=3600000, suffix=" ms",
              depends_on=("wait", True)),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        import os

        path = params.get("path") or ""
        return f"실행: {os.path.basename(path) or '(미지정)'}"
