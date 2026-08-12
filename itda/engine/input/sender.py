"""입력 주입 — 계획을 실제로 실행한다.

두 가지 구현이 있다.

* :class:`DryRunSender` — 아무것도 건드리지 않고 기록만 한다. 테스트와 데모 재생용.
* :class:`Win32Sender` — ``SendInput`` 으로 실제 마우스/키보드를 움직인다.

좌표는 물리 픽셀로 받아 :func:`itda.vision.coords.to_absolute` 로 정규화한다. 그래서 배율이
다른 모니터가 섞여 있어도 목표 지점에 정확히 간다.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from itda.engine.input.steps import BUTTON, CHAR, DELAY, KEY, MOVE, TOUCH, WHEEL, Step
from itda.vision.coords import ScreenInfo, to_absolute

StepHook = Callable[[Step], None]


class Sender:
    """입력 주입기 인터페이스."""

    def run(self, steps: list[Step], on_step: StepHook | None = None) -> None:
        for step in steps:
            self.wait(step.delay_ms)
            self.apply(step)
            if on_step is not None:
                on_step(step)

    def wait(self, ms: float) -> None:
        if ms > 0:
            time.sleep(ms / 1000.0)

    def apply(self, step: Step) -> None:  # pragma: no cover - 하위 클래스가 구현
        raise NotImplementedError


@dataclass
class DryRunSender(Sender):
    """실제로는 아무것도 하지 않고 단계를 기록한다.

    실행 엔진을 실제 입력 없이 시험하거나, 테스트에서 "어떤 좌표를 어떤 순서로 찍는지" 를
    확인할 때 쓴다.
    """

    performed: list[Step] = field(default_factory=list)
    #: 대기 시간을 실제로 자지 않고 합계만 센다 (테스트가 느려지지 않게)
    simulate_time: bool = False
    elapsed_ms: float = 0.0

    def wait(self, ms: float) -> None:
        self.elapsed_ms += max(0.0, ms)
        if self.simulate_time:
            super().wait(ms)

    def apply(self, step: Step) -> None:
        self.performed.append(step)

    def positions(self) -> list[tuple[int, int]]:
        return [(s.x, s.y) for s in self.performed if s.kind == MOVE]

    def text(self) -> str:
        return "".join(s.char for s in self.performed if s.kind == CHAR)

    def clear(self) -> None:
        self.performed.clear()
        self.elapsed_ms = 0.0


# ---------------------------------------------------------------- Win32

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

WHEEL_DELTA = 120

_BUTTON_FLAGS = {
    ("left", True): MOUSEEVENTF_LEFTDOWN,
    ("left", False): MOUSEEVENTF_LEFTUP,
    ("right", True): MOUSEEVENTF_RIGHTDOWN,
    ("right", False): MOUSEEVENTF_RIGHTUP,
    ("middle", True): MOUSEEVENTF_MIDDLEDOWN,
    ("middle", False): MOUSEEVENTF_MIDDLEUP,
}


ULONG_PTR = ctypes.c_size_t


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTUNION)]


class Win32Sender(Sender):
    """``SendInput`` 기반 실제 주입기.

    Args:
        screens: 좌표 정규화에 쓸 모니터 목록. 비우면 그때그때 조회한다.
    """

    def __init__(self, screens: list[ScreenInfo] | None = None) -> None:
        if sys.platform != "win32":  # pragma: no cover - 다른 OS
            raise RuntimeError("Win32Sender 는 Windows 에서만 동작합니다")
        self._screens = screens
        self._user32 = ctypes.windll.user32
        if hasattr(self._user32, "SendInput"):
            self._user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
            self._user32.SendInput.restype = wintypes.UINT

    @property
    def screens(self) -> list[ScreenInfo]:
        if self._screens is not None:
            return self._screens
        from itda.vision.coords import current_screens

        return current_screens()

    def set_screens(self, screens: list[ScreenInfo]) -> None:
        """모니터 구성이 바뀌었을 때 갱신한다."""
        self._screens = screens

    # ------------------------------------------------------------

    def apply(self, step: Step) -> None:
        match step.kind:
            case "move":
                self._send_mouse(step.x, step.y, MOUSEEVENTF_MOVE)
            case "button":
                flag = _BUTTON_FLAGS.get((step.button, step.down))
                if flag is not None:
                    self._send_mouse(step.x, step.y, flag, absolute=False)
            case "wheel":
                self._send_mouse(0, 0, MOUSEEVENTF_WHEEL, absolute=False,
                                 data=step.amount * WHEEL_DELTA)
            case "key":
                self._send_key(step.vk, 0, 0 if step.down else KEYEVENTF_KEYUP)
            case "char":
                self._send_char(step.char)
            case "delay":
                pass  # wait() 가 이미 기다렸다
            case "touch":  # pragma: no cover - 터치 장치 필요
                from itda.engine.input.touch import TouchInjector

                TouchInjector.shared().apply(step)

    # ------------------------------------------------------------

    def _send_mouse(self, x: int, y: int, flags: int, absolute: bool = True,
                    data: int = 0) -> None:
        dx = dy = 0
        if absolute:
            ax, ay = to_absolute(self.screens, x, y)
            dx, dy = ax, ay
            flags |= MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        event = _INPUT(
            type=INPUT_MOUSE,
            union=_INPUTUNION(
                # dwExtraInfo 는 ULONG_PTR(정수)다. None 을 넣으면 ctypes 가
                # "'NoneType' object cannot be interpreted as an integer" 로 거절한다.
                mi=_MOUSEINPUT(dx, dy, ctypes.c_ulong(data & 0xFFFFFFFF), flags, 0, 0)
            ),
        )
        sent = int(self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT)))
        if sent != 1:
            raise OSError(ctypes.get_last_error() or "SendInput failed")

    def _send_key(self, vk: int, scan: int, flags: int) -> None:
        event = _INPUT(
            type=INPUT_KEYBOARD,
            union=_INPUTUNION(ki=_KEYBDINPUT(vk, scan, flags, 0, 0)),  # dwExtraInfo 는 정수
        )
        sent = int(self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT)))
        if sent != 1:
            raise OSError(ctypes.get_last_error() or "SendInput failed")

    def _send_char(self, char: str) -> None:
        """유니코드로 직접 넣는다 — 한글도 입력기 상태와 무관하게 들어간다."""
        for code in _utf16_units(char):
            self._send_key(0, code, KEYEVENTF_UNICODE)
            self._send_key(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)


def _utf16_units(char: str) -> list[int]:
    """BMP 밖 문자(이모지 등)는 서로게이트 쌍으로 나눠 보내야 한다."""
    encoded = char.encode("utf-16-le")
    return [
        int.from_bytes(encoded[i:i + 2], "little") for i in range(0, len(encoded), 2)
    ]
