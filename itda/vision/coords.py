"""좌표계 — DPI 배율 문제를 한 곳에서 흡수한다.

Windows 에서 디스플레이 배율(125%, 150%, 200%)을 쓰면 두 개의 좌표계가 생긴다.

* **물리 픽셀** — 화면 캡처 이미지의 픽셀. 이미지 매칭이 찾아내는 좌표.
* **논리 픽셀** — Qt 위젯과 창 좌표. 배율이 150%면 물리의 2/3.

둘을 섞으면 "이미지는 찾았는데 클릭이 빗나가는" 증상이 난다. 그래서 규칙을 하나로 못박는다.

    **프로젝트에 저장되는 좌표는 전부 물리 픽셀이다.**

캡처도 물리 픽셀로 하고, 입력 주입도 물리 픽셀로 한다. 논리 좌표는 Qt 위젯을 다룰 때만
쓰고, 경계에서 :func:`to_physical` / :func:`to_logical` 로 변환한다.

이 모듈의 계산부는 Qt 없이 동작한다(:class:`ScreenInfo` 목록만 받는다). 그래서 여러 모니터가
서로 다른 배율을 갖는 상황도 테스트로 재현할 수 있다.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

#: SendInput 의 절대 좌표는 가상 화면을 0..65535 로 정규화해 받는다.
ABSOLUTE_RANGE = 65535


@dataclass(frozen=True)
class Rect:
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

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom

    def united(self, other: Rect) -> Rect:
        left = min(self.x, other.x)
        top = min(self.y, other.y)
        return Rect(left, top, max(self.right, other.right) - left,
                    max(self.bottom, other.bottom) - top)


@dataclass(frozen=True)
class ScreenInfo:
    """모니터 하나. ``logical`` 은 Qt 가 보고하는 좌표, ``scale`` 은 배율(1.5 = 150%)."""

    name: str
    logical: Rect
    scale: float = 1.0

    @property
    def physical(self) -> Rect:
        """물리 픽셀 기준 위치와 크기.

        Qt 는 모니터 배치도 논리 좌표로 보고한다. 원점 역시 배율을 곱해야 물리 좌표가 된다.
        """
        return Rect(
            int(round(self.logical.x * self.scale)),
            int(round(self.logical.y * self.scale)),
            int(round(self.logical.width * self.scale)),
            int(round(self.logical.height * self.scale)),
        )


# ---------------------------------------------------------------- 변환 (순수 함수)


def virtual_rect(screens: list[ScreenInfo], physical: bool = True) -> Rect:
    """모든 모니터를 합친 영역."""
    if not screens:
        return Rect(0, 0, 0, 0)
    rects = [s.physical if physical else s.logical for s in screens]
    result = rects[0]
    for rect in rects[1:]:
        result = result.united(rect)
    return result


def screen_at_logical(screens: list[ScreenInfo], x: float, y: float) -> ScreenInfo | None:
    for screen in screens:
        if screen.logical.contains(x, y):
            return screen
    return screens[0] if screens else None


def screen_at_physical(screens: list[ScreenInfo], x: float, y: float) -> ScreenInfo | None:
    for screen in screens:
        if screen.physical.contains(x, y):
            return screen
    return screens[0] if screens else None


def to_physical(screens: list[ScreenInfo], x: float, y: float) -> tuple[int, int]:
    """논리 좌표 → 물리 픽셀. 점이 속한 모니터의 배율을 쓴다."""
    screen = screen_at_logical(screens, x, y)
    if screen is None:
        return int(round(x)), int(round(y))
    offset_x = x - screen.logical.x
    offset_y = y - screen.logical.y
    return (
        int(round(screen.physical.x + offset_x * screen.scale)),
        int(round(screen.physical.y + offset_y * screen.scale)),
    )


def to_logical(screens: list[ScreenInfo], x: float, y: float) -> tuple[int, int]:
    """물리 픽셀 → 논리 좌표."""
    screen = screen_at_physical(screens, x, y)
    if screen is None:
        return int(round(x)), int(round(y))
    offset_x = x - screen.physical.x
    offset_y = y - screen.physical.y
    return (
        int(round(screen.logical.x + offset_x / screen.scale)),
        int(round(screen.logical.y + offset_y / screen.scale)),
    )


def to_absolute(screens: list[ScreenInfo], x: float, y: float) -> tuple[int, int]:
    """물리 좌표 → SendInput 절대 좌표(0..65535).

    가상 화면 전체를 기준으로 정규화한다. 모니터가 여러 개면 원점이 음수일 수 있으므로
    가상 화면의 좌상단을 빼고 계산해야 한다.
    """
    area = virtual_rect(screens, physical=True)
    width = max(1, area.width)
    height = max(1, area.height)
    nx = (x - area.x) / width * ABSOLUTE_RANGE
    ny = (y - area.y) / height * ABSOLUTE_RANGE
    return (
        int(round(max(0, min(ABSOLUTE_RANGE, nx)))),
        int(round(max(0, min(ABSOLUTE_RANGE, ny)))),
    )


def clamp_to_screens(screens: list[ScreenInfo], x: float, y: float) -> tuple[int, int]:
    """물리 좌표를 화면 밖으로 나가지 않게 자른다."""
    area = virtual_rect(screens, physical=True)
    if area.width <= 0:
        return int(round(x)), int(round(y))
    return (
        int(round(max(area.x, min(area.right - 1, x)))),
        int(round(max(area.y, min(area.bottom - 1, y)))),
    )


# ---------------------------------------------------------------- 실제 환경


def enable_dpi_awareness() -> str:
    """프로세스를 Per-Monitor DPI Aware 로 선언한다.

    **QApplication 을 만들기 전에** 불러야 한다. 선언하지 않으면 Windows 가 화면을 가상화해서
    캡처 해상도와 실제 픽셀이 어긋난다(150% 배율에서 클릭이 전부 빗나가는 원인).

    Returns:
        적용된 모드 이름. Windows 가 아니거나 실패하면 이유를 담은 문자열.
    """
    if sys.platform != "win32":
        return "not-windows"
    try:
        import ctypes

        from ctypes import wintypes

        user32 = ctypes.windll.user32
        # -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (Windows 10 1703+)
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
            ptr_mask = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4 & ptr_mask)):
                return "per-monitor-v2"
        shcore = ctypes.windll.shcore
        if hasattr(shcore, "SetProcessDpiAwareness"):
            shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
            shcore.SetProcessDpiAwareness.restype = ctypes.c_long
            shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            return "per-monitor"
        if hasattr(user32, "SetProcessDPIAware"):
            user32.SetProcessDPIAware.argtypes = []
            user32.SetProcessDPIAware.restype = wintypes.BOOL
            user32.SetProcessDPIAware()
        return "system"
    except Exception as e:  # 이미 설정돼 있으면 실패한다 — 치명적이지 않다
        return f"unchanged ({type(e).__name__})"


def current_screens() -> list[ScreenInfo]:
    """지금 연결된 모니터 목록. QGuiApplication 이 있어야 한다."""
    from PyQt6.QtGui import QGuiApplication

    screens: list[ScreenInfo] = []
    for screen in QGuiApplication.screens():
        geometry = screen.geometry()
        screens.append(
            ScreenInfo(
                name=screen.name(),
                logical=Rect(geometry.x(), geometry.y(), geometry.width(), geometry.height()),
                scale=float(screen.devicePixelRatio()),
            )
        )
    return screens


def describe(screens: list[ScreenInfo]) -> str:
    """로그에 남길 한 줄 요약."""
    if not screens:
        return "모니터를 찾지 못했습니다"
    parts = [
        f"{s.name or '화면'} {s.physical.width}×{s.physical.height}"
        f"@{int(s.scale * 100)}%"
        for s in screens
    ]
    area = virtual_rect(screens)
    return f"{' / '.join(parts)} · 가상 화면 {area.width}×{area.height}"
