"""창 제어 — 파라미터 스키마와 위치·크기 계산.

매크로에서 창 제어가 중요한 이유는 **재현성** 때문이다. 창 크기가 실행할 때마다 다르면 안에
있는 버튼 위치도 달라져서, 좌표는 물론이고 이미지 검색 범위까지 어긋난다. 그래서 보통 플로우
맨 앞에 "창을 정해진 자리·크기로 맞추기" 를 둔다.

노드(`window`)와 액션(`window`)이 같은 파라미터를 쓰도록 스키마를 여기 한 번만 정의한다.
계산부는 순수 함수라 Qt·win32 없이 테스트한다.

**창 제어에는 허용오차·변동계수를 걸지 않는다.** 사람처럼 흔드는 것은 클릭·타이핑처럼
사람이 하는 동작에만 의미가 있고, 창 맞추기는 그 반대 목적(매번 똑같은 화면 만들기)이다.
좌표·크기는 요청한 값 그대로, 적용 후 대기도 변동 없이 그대로 쓴다. 여기서 다루는 좌표는
전부 **눈에 보이는 창** 기준이다(투명 테두리 보정은 :mod:`itda.engine.window` 참고).
"""

from __future__ import annotations

from dataclasses import dataclass

from itda.core.schema import Field

# ---------------------------------------------------------------- 동작 목록

OPS = [
    ("activate", "앞으로 가져오기"),
    ("move_resize", "위치·크기 지정"),
    ("move", "위치만 이동"),
    ("resize", "크기만 변경"),
    ("preset", "화면에 맞춰 배치"),
    ("maximize", "최대화"),
    ("minimize", "최소화"),
    ("restore", "복원"),
    ("topmost", "항상 위 지정"),
    ("close", "닫기"),
    ("exists", "존재 확인만"),
]

#: 위치/크기를 계산해야 하는 동작들
GEOMETRY_OPS = ("move_resize", "move", "resize", "preset")

PRESETS = [
    ("center", "화면 가운데"),
    ("fill", "모니터 채우기 (작업표시줄 제외)"),
    ("left_half", "왼쪽 절반"),
    ("right_half", "오른쪽 절반"),
    ("top_half", "위쪽 절반"),
    ("bottom_half", "아래쪽 절반"),
    ("top_left", "왼쪽 위 1/4"),
    ("top_right", "오른쪽 위 1/4"),
    ("bottom_left", "왼쪽 아래 1/4"),
    ("bottom_right", "오른쪽 아래 1/4"),
]

MONITORS = [
    ("current", "창이 있는 모니터"),
    ("primary", "주 모니터"),
    ("1", "1번 모니터"),
    ("2", "2번 모니터"),
    ("3", "3번 모니터"),
]


def window_params(include_target: bool = True) -> list[Field]:
    """창 제어 파라미터. 노드와 액션이 함께 쓴다."""
    fields: list[Field] = []
    if include_target:
        fields += [
            Field("title", "str", "창 제목", "",
                  help="부분 일치. 비우면 프로젝트 설정의 대상 창을 씁니다."),
            Field(
                "match",
                "enum",
                "제목 일치 방식",
                "contains",
                options=[("contains", "포함"), ("exact", "정확히"), ("regex", "정규식")],
            ),
        ]
    fields += [
        Field("op", "enum", "동작", "move_resize", options=OPS),
        Field("point", "point", "위치", None, depends_on=("op", ("move", "move_resize")),
              help="화면에서 보이는 창의 왼쪽 위 모서리입니다. 허용오차 없이 그대로 맞춥니다."),
        Field("size", "point", "크기 (가로, 세로)", None,
              depends_on=("op", ("resize", "move_resize")),
              help="화면에서 보이는 창의 크기입니다. 0 을 넣으면 그 축은 현재 크기를 유지합니다."),
        Field("preset", "enum", "배치", "center", options=PRESETS,
              depends_on=("op", "preset")),
        Field("monitor", "enum", "기준 모니터", "current", options=MONITORS,
              depends_on=("op", ("preset", "move", "move_resize"))),
        Field("topmost", "bool", "항상 위로 두기", True, depends_on=("op", "topmost")),
        Field("activate_first", "bool", "먼저 앞으로 가져오기", True),
        Field("settle_ms", "int", "적용 후 대기", 200, minimum=0, maximum=60000, suffix=" ms",
              help="창 크기가 바뀐 뒤 다시 그려질 시간을 줍니다."),
        Field("required", "bool", "창을 못 찾으면 실패 처리", True),
    ]
    return fields


def summarize(params: dict) -> str:
    """노드 카드와 액션 목록에 한 줄로."""
    labels = dict(OPS)
    presets = dict(PRESETS)
    title = params.get("title") or "대상 창"
    op = params.get("op", "activate")

    match op:
        case "move_resize":
            point = params.get("point") or [0, 0]
            size = params.get("size") or [0, 0]
            return f"창 '{title}' → ({point[0]},{point[1]}) {size[0]}×{size[1]}"
        case "move":
            point = params.get("point") or [0, 0]
            return f"창 '{title}' 위치 → ({point[0]},{point[1]})"
        case "resize":
            size = params.get("size") or [0, 0]
            return f"창 '{title}' 크기 → {size[0]}×{size[1]}"
        case "preset":
            return f"창 '{title}' {presets.get(params.get('preset', ''), '배치')}"
        case "topmost":
            return f"창 '{title}' 항상 위 {'켜기' if params.get('topmost', True) else '끄기'}"
        case _:
            return f"창 '{title}' {labels.get(op, op)}"


# ---------------------------------------------------------------- 기하 계산


@dataclass(frozen=True)
class Box:
    """창/모니터 사각형 (물리 픽셀)."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


def resolve_geometry(params: dict, window: Box, monitor: Box) -> Box | None:
    """동작에 맞는 목표 사각형을 계산한다.

    Args:
        params: 창 제어 파라미터.
        window: 지금 창의 위치·크기.
        monitor: 기준 모니터의 작업 영역.

    Returns:
        옮길 사각형. 위치/크기를 건드리지 않는 동작이면 None.
    """
    op = params.get("op", "activate")
    if op not in GEOMETRY_OPS:
        return None

    if op == "preset":
        return _preset_box(params.get("preset", "center"), window, monitor)

    point = params.get("point") or [window.x, window.y]
    size = params.get("size") or [window.width, window.height]

    if op == "move":
        return Box(int(point[0]), int(point[1]), window.width, window.height)

    # 0 은 "그 축은 그대로"
    width = int(size[0]) or window.width
    height = int(size[1]) or window.height
    if op == "resize":
        return Box(window.x, window.y, width, height)
    return Box(int(point[0]), int(point[1]), width, height)


def _preset_box(preset: str, window: Box, monitor: Box) -> Box:
    half_w = monitor.width // 2
    half_h = monitor.height // 2
    match preset:
        case "fill":
            return Box(monitor.x, monitor.y, monitor.width, monitor.height)
        case "left_half":
            return Box(monitor.x, monitor.y, half_w, monitor.height)
        case "right_half":
            return Box(monitor.x + half_w, monitor.y, monitor.width - half_w, monitor.height)
        case "top_half":
            return Box(monitor.x, monitor.y, monitor.width, half_h)
        case "bottom_half":
            return Box(monitor.x, monitor.y + half_h, monitor.width, monitor.height - half_h)
        case "top_left":
            return Box(monitor.x, monitor.y, half_w, half_h)
        case "top_right":
            return Box(monitor.x + half_w, monitor.y, monitor.width - half_w, half_h)
        case "bottom_left":
            return Box(monitor.x, monitor.y + half_h, half_w, monitor.height - half_h)
        case "bottom_right":
            return Box(monitor.x + half_w, monitor.y + half_h,
                       monitor.width - half_w, monitor.height - half_h)
        case _:  # center — 크기는 유지하고 가운데로
            width = min(window.width, monitor.width)
            height = min(window.height, monitor.height)
            return Box(
                monitor.x + (monitor.width - width) // 2,
                monitor.y + (monitor.height - height) // 2,
                width,
                height,
            )


def clamp_to_monitor(box: Box, monitor: Box) -> Box:
    """창이 화면 밖으로 나가지 않게 민다. 제목 표시줄을 잃지 않게 하는 안전장치."""
    width = min(box.width, monitor.width)
    height = min(box.height, monitor.height)
    x = max(monitor.x, min(monitor.right - width, box.x))
    y = max(monitor.y, min(monitor.bottom - height, box.y))
    return Box(x, y, width, height)


def plan_geometry(params: dict, window: Box, monitors: list[Box]) -> Box | None:
    """목표 사각형 전체 계산 — 기준 모니터 선택부터 화면 밖 방지까지.

    **절대 좌표를 준 경우(위치 이동·위치·크기 지정)에는 그 좌표가 있는 모니터를 기준으로
    삼는다.** 창이 지금 있는 모니터로 가둬 버리면, 2번 모니터에 있는 창을 (100, 200) 으로
    옮기라고 했을 때 2번 모니터 구석으로 밀려서 엉뚱한 자리에 놓인다. 좌표는 가상 데스크톱
    전체 기준이므로 모니터를 넘어 옮길 수 있어야 한다.
    """
    setting = params.get("monitor", "current")
    monitor = pick_monitor(setting, window, monitors)
    target = resolve_geometry(params, window, monitor)
    if target is None:
        return None

    if setting == "current" and params.get("op") in ("move", "move_resize"):
        monitor = pick_monitor("current", target, monitors)
    return clamp_to_monitor(target, monitor)


def pick_monitor(setting: str, window: Box, monitors: list[Box]) -> Box:
    """``monitor`` 설정에 맞는 모니터를 고른다."""
    if not monitors:
        return Box(0, 0, 1920, 1080)
    if setting.isdigit():
        index = int(setting) - 1
        if 0 <= index < len(monitors):
            return monitors[index]
        return monitors[0]
    if setting == "primary":
        return monitors[0]
    # current — 창 중심이 들어 있는 모니터
    cx, cy = window.center
    for monitor in monitors:
        if monitor.x <= cx < monitor.right and monitor.y <= cy < monitor.bottom:
            return monitor
    return monitors[0]
