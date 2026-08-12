"""창 제어 실행부.

:mod:`itda.core.window_spec` 이 "어디로 옮길지" 를 계산하고, 여기서 실제로 옮긴다.
입력 주입과 같은 방식으로 **계획(순수 계산)과 실행(부작용)을 나눈다.**

좌표는 물리 픽셀이다. DPI Aware 프로세스에서 ``GetWindowRect`` / ``SetWindowPos`` 가
물리 픽셀을 쓰기 때문에 별도 변환이 필요 없다.

**보이지 않는 테두리 보정** — Windows 10 부터 창 둘레에는 폭 7px 안팎의 투명한 리사이즈
테두리가 있다. ``GetWindowRect`` / ``SetWindowPos`` 는 이 테두리를 포함한 값을 다루므로,
x=100 으로 옮긴 창이 눈에는 107 에 보인다(실측: 요청 (100,200,800,600) → 보이는 창
(107,200,786,593)). 매크로에서 창을 맞추는 이유는 "화면에서 늘 같은 자리" 이고, 좌표 도구·
이미지 검색도 전부 화면 픽셀 기준이므로 **여기서는 보이는 창을 기준으로 다룬다.**
``DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`` 로 차이를 재서 넣고 뺀다.
"""

from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass

from itda.core.window_spec import Box, plan_geometry

SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

WM_CLOSE = 0x0010

#: DwmGetWindowAttribute — 눈에 보이는 창 사각형
DWMWA_EXTENDED_FRAME_BOUNDS = 9

#: 최소화된 창은 (-32000, -32000) 에 놓인다. 그 좌표로는 테두리를 잴 수 없다.
MINIMIZED_X = -30000


@dataclass(frozen=True)
class FramePad:
    """창 사각형(API)과 보이는 창의 차이.

    ``left``/``top`` 은 보이는 창이 오른쪽·아래로 밀린 양, ``width``/``height`` 는 보이는
    창이 좁아진 양이다. 전부 0 이면 보정할 것이 없다.
    """

    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0

    def to_visible(self, raw: Box) -> Box:
        """API 사각형 → 눈에 보이는 창."""
        return Box(raw.x + self.left, raw.y + self.top,
                   raw.width - self.width, raw.height - self.height)

    def to_raw(self, visible: Box) -> Box:
        """원하는 '보이는 창' → SetWindowPos 에 넣을 값."""
        return Box(visible.x - self.left, visible.y - self.top,
                   visible.width + self.width, visible.height + self.height)


@dataclass(frozen=True)
class WindowRef:
    """찾은 창 하나. ``box`` 는 **눈에 보이는** 사각형이다."""

    handle: int
    title: str
    box: Box
    pad: FramePad = FramePad()
    #: 창을 가진 프로세스. 잇다 자신의 창을 걸러낼 때 쓴다(창 선택 도구).
    pid: int = 0


def current_process_id() -> int:
    """지금 프로세스의 id. 우리 창을 골라내는 기준."""
    if sys.platform != "win32":  # pragma: no cover - 다른 OS
        return 0
    return int(ctypes.windll.kernel32.GetCurrentProcessId())


def match_title(title: str, pattern: str, mode: str = "contains") -> bool:
    """창 제목 일치 검사. 계산부라 테스트가 쉽다."""
    if not pattern:
        return True
    match mode:
        case "exact":
            return title == pattern
        case "regex":
            try:
                return re.search(pattern, title) is not None
            except re.error:
                return False
        case _:
            return pattern.lower() in title.lower()


def _configure_prototypes(user32, dwm) -> None:
    """Win32/DWM API의 64비트 프로토타입(restype/argtypes)을 설정한다."""
    if hasattr(user32, "_configured_window_proto"):
        return
    user32._configured_window_proto = True

    # User32 APIs
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetForegroundWindow.argtypes = []

    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]

    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]

    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]

    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]

    user32.ShowWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

    user32.PostMessageW.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]

    # DWM API
    if hasattr(dwm, "DwmGetWindowAttribute"):
        dwm.DwmGetWindowAttribute.restype = ctypes.c_long
        dwm.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]


class WindowController:
    """Windows 창 제어. 실제 시스템을 건드리는 유일한 지점."""

    def __init__(self) -> None:
        if sys.platform != "win32":  # pragma: no cover - 다른 OS
            raise RuntimeError("창 제어는 Windows 에서만 동작합니다")
        self._user32 = ctypes.windll.user32
        self._dwm = ctypes.windll.dwmapi
        _configure_prototypes(self._user32, self._dwm)

    # ------------------------------------------------------------ 조회

    def windows(self) -> list[WindowRef]:
        """보이는 최상위 창 목록."""
        found: list[WindowRef] = []
        enum_proc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
        )

        def callback(hwnd, _lparam):
            if not self._user32.IsWindowVisible(hwnd):
                return True
            length = self._user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            self._user32.GetWindowTextW(hwnd, buffer, length + 1)
            raw = self.raw_box_of(hwnd)
            pad = self.pad_of(hwnd, raw)
            found.append(
                WindowRef(int(hwnd), buffer.value, pad.to_visible(raw), pad, self.pid_of(hwnd))
            )
            return True

        self._user32.EnumWindows(enum_proc(callback), 0)
        return found

    def find(self, pattern: str, mode: str = "contains") -> WindowRef | None:
        """제목으로 창 하나를 찾는다. 여러 개면 가장 먼저 나온 것."""
        for window in self.windows():
            if match_title(window.title, pattern, mode):
                return window
        return None

    def foreground(self) -> WindowRef | None:
        """지금 활성화된 창. 상황 판정의 기본 단서다."""
        handle = self._user32.GetForegroundWindow()
        if not handle:
            return None
        length = self._user32.GetWindowTextLengthW(handle)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(handle, buffer, length + 1)
        raw = self.raw_box_of(handle)
        pad = self.pad_of(handle, raw)
        return WindowRef(int(handle), buffer.value, pad.to_visible(raw), pad, self.pid_of(handle))

    def pid_of(self, handle: int) -> int:
        """창을 가진 프로세스 id. 못 얻으면 0."""
        pid = wintypes.DWORD(0)
        self._user32.GetWindowThreadProcessId(wintypes.HWND(handle), ctypes.byref(pid))
        return int(pid.value)

    def raw_box_of(self, handle: int) -> Box:
        """``GetWindowRect`` 그대로 — 투명한 테두리를 포함한다."""
        rect = wintypes.RECT()
        self._user32.GetWindowRect(wintypes.HWND(handle), ctypes.byref(rect))
        return Box(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)

    def box_of(self, handle: int) -> Box:
        """눈에 보이는 창. 창 제어는 전부 이 기준으로 한다."""
        raw = self.raw_box_of(handle)
        return self.pad_of(handle, raw).to_visible(raw)

    def pad_of(self, handle: int, raw: Box | None = None) -> FramePad:
        """투명한 리사이즈 테두리의 두께를 잰다. 못 재면 보정하지 않는다."""
        raw = self.raw_box_of(handle) if raw is None else raw
        if raw.x <= MINIMIZED_X or raw.width <= 0 or raw.height <= 0:
            return FramePad()  # 최소화된 창

        rect = wintypes.RECT()
        result = self._dwm.DwmGetWindowAttribute(
            wintypes.HWND(handle),
            ctypes.c_uint(DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if result != 0:  # S_OK 가 아니면 (구형 창 등) 보정 없이 간다
            return FramePad()

        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return FramePad()
        return FramePad(rect.left - raw.x, rect.top - raw.y, raw.width - width, raw.height - height)

    def monitors(self) -> list[Box]:
        """모니터 작업 영역 목록 (작업표시줄 제외). 주 모니터가 앞에 온다."""
        from itda.vision.coords import current_screens

        boxes = []
        for screen in current_screens():
            area = screen.physical
            boxes.append(Box(area.x, area.y, area.width, area.height))
        return boxes

    # ------------------------------------------------------------ 실행

    def apply(self, params: dict, window: WindowRef) -> bool:
        """계산된 목표대로 창을 옮긴다."""
        op = params.get("op", "activate")
        handle = wintypes.HWND(window.handle)

        if params.get("activate_first", True) and op not in ("exists",):
            self._user32.SetForegroundWindow(handle)

        match op:
            case "minimize":
                return bool(self._user32.ShowWindow(handle, SW_MINIMIZE))
            case "maximize":
                return bool(self._user32.ShowWindow(handle, SW_MAXIMIZE))
            case "restore":
                return bool(self._user32.ShowWindow(handle, SW_RESTORE))
            case "close":
                return bool(self._user32.PostMessageW(handle, WM_CLOSE, 0, 0))
            case "topmost":
                after = HWND_TOPMOST if params.get("topmost", True) else HWND_NOTOPMOST
                ptr_mask = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1
                return bool(
                    self._user32.SetWindowPos(
                        handle, ctypes.c_void_p(after & ptr_mask), 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
                    )
                )
            case "activate" | "exists":
                return True

        target = self.plan(params, window)
        if target is None:
            return True
        # 최대화 상태면 먼저 복원해야 크기가 먹는다
        self._user32.ShowWindow(handle, SW_RESTORE)
        # 테두리 두께는 복원 뒤에 다시 잰다 (최대화 상태와 다르다)
        raw = self.pad_of(window.handle).to_raw(target)
        return bool(
            self._user32.SetWindowPos(
                handle, None, raw.x, raw.y, raw.width, raw.height,
                SWP_NOZORDER | SWP_SHOWWINDOW,
            )
        )

    def plan(self, params: dict, window: WindowRef) -> Box | None:
        """실제로 옮기지 않고 목표 사각형만 계산한다 (보이는 창 기준)."""
        return plan_geometry(params, window.box, self.monitors())
