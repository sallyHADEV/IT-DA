"""입력 계열 액션 — 마우스, 키보드, 터치.

좌표는 네 가지 방법으로 정한다:
* ``fixed``   : 지정한 절대 좌표
* ``object``  : 객체의 위치 — 아래 "객체 위치 얻는 방법" 참고
* ``var``     : 앞선 '이미지 찾기'가 변수에 담아둔 ``[x, y]``
* ``current`` : 지금 커서 자리

**객체 위치 얻는 방법(``object_lookup``)** — 같은 객체를 두 번 찾는 낭비를 막기 위한 규칙이다.
실행 중에는 객체별로 '최근 찾은 위치'가 기억된다(이미지 찾기가 채워 넣는다).

* ``cache_or_search`` (기본): 최근 찾은 위치가 있으면 그대로 쓰고, 없으면 그 자리에서 새로 찾는다.
  → 앞에 이미지 찾기를 두면 **다시 찾지 않는다.** 이미지 찾기 없이 클릭만 두어도 동작한다.
* ``always``: 항상 새로 찾는다. 화면이 흐르거나 목록이 움직이는 경우에 쓴다.
* ``cache_only``: 최근 위치만 쓰고 없으면 실패. 찾기 비용을 확실히 통제하고 싶을 때.

허용오차(click_offset_px)는 실행 시 프로파일에서 자동 적용되므로 여기서 따로 설정하지 않는다.
"""

from __future__ import annotations

from itda.core.registry import ActionType, register_action
from itda.core.schema import Field

_TARGET_FIELDS = [
    Field(
        "target_mode",
        "enum",
        "위치 지정",
        "fixed",
        options=[("fixed", "좌표 지정"), ("object", "객체 위치"), ("var", "변수의 좌표"), ("current", "현재 커서")],
        group="위치",
    ),
    Field("point", "point", "좌표", None, depends_on=("target_mode", "fixed"), group="위치"),
    Field("object", "object_ref", "객체", "", depends_on=("target_mode", "object"), group="위치"),
    Field(
        "object_lookup",
        "enum",
        "객체 위치",
        "cache_or_search",
        options=[
            ("cache_or_search", "최근 찾은 위치 사용 (없으면 새로 찾기)"),
            ("always", "항상 새로 찾기"),
            ("cache_only", "최근 찾은 위치만 사용 (없으면 실패)"),
        ],
        depends_on=("target_mode", "object"),
        group="위치",
        help="앞에서 '이미지 찾기'로 찾아 둔 위치를 재사용할지 정합니다. 화면이 움직이면 '항상 새로 찾기'.",
    ),
    Field("var", "var", "변수", "", depends_on=("target_mode", "var"), group="위치",
          help="'이미지 찾기'의 결과 변수([x, y])를 넣으세요."),
    Field("offset", "point", "추가 오프셋", None, group="위치"),
]

_BUTTON = Field(
    "button",
    "enum",
    "버튼",
    "left",
    options=[("left", "왼쪽"), ("right", "오른쪽"), ("middle", "가운데")],
)

#: 사람처럼 움직이기 — 프로젝트 프로파일을 따르거나, 이 동작만 켜고 끈다.
_HUMANIZE = Field(
    "humanize",
    "enum",
    "사람처럼 움직이기",
    "inherit",
    options=[("inherit", "프로파일 따름"), ("on", "이 동작만 켬"), ("off", "이 동작만 끔")],
    help="곡선 궤적·속도 변화 등을 적용할지. 정밀한 좌표가 중요한 동작만 끄면 됩니다.",
)


@register_action
class Click(ActionType):
    ID = "click"
    LABEL = "클릭"
    CATEGORY = "입력"
    COLOR = "#4a6fa5"
    ICON = "🖱"
    PARAMS = [
        *_TARGET_FIELDS,
        _BUTTON,
        Field(
            "click_type",
            "enum",
            "방식",
            "single",
            options=[("single", "한 번"), ("double", "더블클릭"), ("down", "누르기"), ("up", "떼기")],
        ),
        Field("move_first", "bool", "커서를 이동시킨 뒤 클릭", True),
        _HUMANIZE,
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        mode = params.get("target_mode")
        if mode == "object":
            how = {
                "always": " · 새로 찾기",
                "cache_only": " · 최근 위치만",
            }.get(params.get("object_lookup", "cache_or_search"), "")
            where = f"객체 '{params.get('object') or '?'}'{how}"
        elif mode == "var":
            where = f"변수 {params.get('var') or '?'}"
        elif mode == "current":
            where = "현재 위치"
        else:
            p = params.get("point") or [0, 0]
            where = f"({p[0]}, {p[1]})"
        kind = {"single": "클릭", "double": "더블클릭", "down": "누르기", "up": "떼기"}
        return f"{where} {kind.get(params.get('click_type', 'single'), '클릭')}"


@register_action
class MoveMouse(ActionType):
    ID = "move"
    LABEL = "마우스 이동"
    CATEGORY = "입력"
    COLOR = "#4a6fa5"
    ICON = "➤"
    PARAMS = [
        *_TARGET_FIELDS,
        Field("duration_ms", "int", "이동 시간(0=상속)", 0, minimum=0, maximum=10000, suffix=" ms"),
        _HUMANIZE,
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        if params.get("target_mode") == "object":
            return f"마우스 이동 → 객체 '{params.get('object') or '?'}'"
        p = params.get("point") or [0, 0]
        return f"마우스 이동 → ({p[0]}, {p[1]})"


@register_action
class Drag(ActionType):
    ID = "drag"
    LABEL = "드래그"
    CATEGORY = "입력"
    COLOR = "#4a6fa5"
    ICON = "⇢"
    PARAMS = [
        Field("from_point", "point", "시작 좌표", None),
        Field("to_point", "point", "끝 좌표", None),
        _BUTTON,
        Field("duration_ms", "int", "끄는 시간", 300, minimum=0, maximum=60000, suffix=" ms"),
        Field("steps", "int", "중간 단계 수", 20, minimum=1, maximum=500,
              help="많을수록 사람이 끄는 것처럼 부드럽습니다."),
        _HUMANIZE,
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        a = params.get("from_point") or [0, 0]
        b = params.get("to_point") or [0, 0]
        return f"드래그 ({a[0]},{a[1]}) → ({b[0]},{b[1]})"


@register_action
class Scroll(ActionType):
    ID = "scroll"
    LABEL = "휠 스크롤"
    CATEGORY = "입력"
    COLOR = "#4a6fa5"
    ICON = "↕"
    PARAMS = [
        *_TARGET_FIELDS,
        Field("amount", "int", "칸 수", 3, minimum=-100, maximum=100,
              help="양수는 위, 음수는 아래."),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        return f"휠 스크롤 {params.get('amount', 0)}칸"


@register_action
class KeyPress(ActionType):
    ID = "key_press"
    LABEL = "키 입력"
    CATEGORY = "입력"
    COLOR = "#4a6fa5"
    ICON = "⌨"
    PARAMS = [
        Field("keys", "key", "키 조합", "", help="예: enter, ctrl+s, alt+f4"),
        Field(
            "action",
            "enum",
            "방식",
            "tap",
            options=[("tap", "누르고 떼기"), ("down", "누르고 있기"), ("up", "떼기")],
        ),
        Field("repeat", "int", "반복", 1, minimum=1, maximum=1000),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        rep = params.get("repeat", 1)
        tail = f" ×{rep}" if rep and rep > 1 else ""
        return f"키 [{params.get('keys') or '?'}]{tail}"


@register_action
class TypeText(ActionType):
    ID = "type_text"
    LABEL = "문자 입력"
    CATEGORY = "입력"
    COLOR = "#4a6fa5"
    ICON = "T"
    PARAMS = [
        Field("text", "text", "입력할 내용", "", help="${변수} 로 변수를 끼워 넣을 수 있습니다."),
        Field(
            "method",
            "enum",
            "입력 방법",
            "unicode",
            options=[("unicode", "유니코드 직접 입력(한글 안전)"), ("keys", "키 이벤트"), ("clipboard", "클립보드 붙여넣기")],
        ),
        Field("interval_ms", "int", "글자 간격", 10, minimum=0, maximum=5000, suffix=" ms",
              depends_on=("method", "keys")),
        Field("clear_first", "bool", "기존 내용 지우고 입력", False),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        text = (params.get("text") or "").replace("\n", " ")
        if len(text) > 24:
            text = text[:24] + "…"
        return f"문자 입력 “{text}”"


# ---------------------------------------------------------------- 터치


@register_action
class TouchPoint(ActionType):
    ID = "touch_point"
    LABEL = "터치"
    CATEGORY = "입력"
    COLOR = "#5b7fa8"
    ICON = "☝"
    HELP = "Windows 터치 주입으로 한 점을 탭합니다."
    PARAMS = [
        *_TARGET_FIELDS,
        Field("hold_ms", "int", "누르는 시간", 60, minimum=0, maximum=60000, suffix=" ms"),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        p = params.get("point") or [0, 0]
        return f"터치 ({p[0]}, {p[1]}) {params.get('hold_ms', 0)}ms"


@register_action
class TouchMulti(ActionType):
    ID = "touch_multi"
    LABEL = "멀티 터치"
    CATEGORY = "입력"
    COLOR = "#5b7fa8"
    ICON = "✌"
    HELP = "여러 점을 동시에 누릅니다. 핀치/줌 같은 제스처에 사용합니다."
    PARAMS = [
        Field("points", "point_list", "접점 목록", None),
        Field("hold_ms", "int", "누르는 시간", 120, minimum=0, maximum=60000, suffix=" ms"),
        Field(
            "gesture",
            "enum",
            "제스처",
            "tap",
            options=[("tap", "동시 탭"), ("pinch_in", "오므리기"), ("pinch_out", "벌리기"), ("rotate", "회전")],
        ),
        Field("distance", "int", "이동 거리", 80, minimum=1, maximum=4000, suffix=" px",
              depends_on=("gesture", ("pinch_in", "pinch_out"))),
        Field("angle", "int", "회전 각도", 90, minimum=-360, maximum=360, suffix="°",
              depends_on=("gesture", "rotate")),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        n = len(params.get("points") or [])
        label = {"tap": "동시 탭", "pinch_in": "오므리기", "pinch_out": "벌리기", "rotate": "회전"}
        return f"멀티터치 {n}점 · {label.get(params.get('gesture', 'tap'), '')}"


@register_action
class TouchDrag(ActionType):
    ID = "touch_drag"
    LABEL = "터치 드래그"
    CATEGORY = "입력"
    COLOR = "#5b7fa8"
    ICON = "↝"
    PARAMS = [
        Field("path", "point_list", "경로 좌표", None, help="두 점 이상. 순서대로 끌립니다."),
        Field("duration_ms", "int", "끄는 시간", 400, minimum=0, maximum=60000, suffix=" ms"),
        Field("hold_start_ms", "int", "시작에서 누르고 대기", 80, minimum=0, maximum=10000, suffix=" ms"),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        n = len(params.get("path") or [])
        return f"터치 드래그 {n}점 경로 · {params.get('duration_ms', 0)}ms"
