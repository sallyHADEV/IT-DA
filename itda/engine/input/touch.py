"""터치 주입 (Windows ``InjectTouchInput``).

마우스 이벤트와 달리 터치는 **접점(pointer)마다 상태를 유지**해야 한다. 누르고 있는 접점은
움직이지 않아도 매 프레임 UPDATE 를 보내야 손을 뗀 것으로 취급되지 않는다. 그래서 접점 상태를
:class:`TouchInjector` 가 들고 있다가 한 번에 주입한다.

멀티터치 제스처(핀치/회전)는 :func:`plan_gesture` 가 접점들의 좌표 궤적을 만들고, 주입기는
그 좌표를 순서대로 보내기만 한다.
"""

from __future__ import annotations

import ctypes
import math
import sys
from ctypes import wintypes
from dataclasses import dataclass, field

from itda.engine.input.steps import TOUCH, Step

MAX_CONTACTS = 10

# POINTER_INPUT_TYPE
PT_TOUCH = 0x00000002

# POINTER_FLAGS
POINTER_FLAG_NONE = 0x00000000
POINTER_FLAG_NEW = 0x00000001
POINTER_FLAG_INRANGE = 0x00000002
POINTER_FLAG_INCONTACT = 0x00000004
POINTER_FLAG_DOWN = 0x00010000
POINTER_FLAG_UPDATE = 0x00020000
POINTER_FLAG_UP = 0x00040000

TOUCH_FLAG_NONE = 0x00000000
TOUCH_MASK_CONTACTAREA = 0x00000001
TOUCH_MASK_ORIENTATION = 0x00000002
TOUCH_MASK_PRESSURE = 0x00000004

TOUCH_FEEDBACK_DEFAULT = 0x1


class _POINTER_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerType", ctypes.c_uint32),
        ("pointerId", ctypes.c_uint32),
        ("frameId", ctypes.c_uint32),
        ("pointerFlags", ctypes.c_uint32),
        ("sourceDevice", wintypes.HANDLE),
        ("hwndTarget", wintypes.HWND),
        ("ptPixelLocation", wintypes.POINT),
        ("ptHimetricLocation", wintypes.POINT),
        ("ptPixelLocationRaw", wintypes.POINT),
        ("ptHimetricLocationRaw", wintypes.POINT),
        ("dwTime", wintypes.DWORD),
        ("historyCount", ctypes.c_uint32),
        ("InputData", ctypes.c_int32),
        ("dwKeyStates", wintypes.DWORD),
        ("PerformanceCount", ctypes.c_uint64),
        ("ButtonChangeType", ctypes.c_int),
    ]


class _POINTER_TOUCH_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", _POINTER_INFO),
        ("touchFlags", ctypes.c_uint32),
        ("touchMask", ctypes.c_uint32),
        ("rcContact", wintypes.RECT),
        ("rcContactRaw", wintypes.RECT),
        ("orientation", ctypes.c_uint32),
        ("pressure", ctypes.c_uint32),
    ]


@dataclass
class Contact:
    """접점 하나의 현재 상태."""

    pointer: int
    x: int = 0
    y: int = 0
    down: bool = False
    #: 이번에 새로 눌렸는지 (DOWN 플래그를 한 번만 보내기 위해)
    just_pressed: bool = False
    radius: int = 4
    pressure: int = 32000


class TouchInjector:
    """접점 상태를 들고 있다가 ``InjectTouchInput`` 으로 한 번에 보낸다."""

    _shared: TouchInjector | None = None

    def __init__(self, max_contacts: int = MAX_CONTACTS) -> None:
        if sys.platform != "win32":  # pragma: no cover - 다른 OS
            raise RuntimeError("터치 주입은 Windows 에서만 동작합니다")
        self._user32 = ctypes.windll.user32
        if hasattr(self._user32, "InitializeTouchInjection"):
            self._user32.InitializeTouchInjection.argtypes = [wintypes.DWORD, wintypes.DWORD]
            self._user32.InitializeTouchInjection.restype = wintypes.BOOL
        if hasattr(self._user32, "InjectTouchInput"):
            self._user32.InjectTouchInput.argtypes = [wintypes.UINT, ctypes.POINTER(_POINTER_TOUCH_INFO)]
            self._user32.InjectTouchInput.restype = wintypes.BOOL
        self.contacts: dict[int, Contact] = {}
        self._initialized = False
        self._max_contacts = max_contacts

    @classmethod
    def shared(cls) -> TouchInjector:
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    # ------------------------------------------------------------

    def initialize(self) -> bool:
        """드라이버 초기화. 프로세스당 한 번만 하면 된다."""
        if self._initialized:
            return True
        ok = bool(
            self._user32.InitializeTouchInjection(self._max_contacts, TOUCH_FEEDBACK_DEFAULT)
        )
        self._initialized = ok
        return ok

    def apply(self, step: Step) -> None:
        """TOUCH 단계 하나를 반영하고 현재 접점 전체를 주입한다."""
        if step.kind != TOUCH:
            return
        contact = self.contacts.setdefault(step.pointer, Contact(pointer=step.pointer))
        was_down = contact.down
        contact.x, contact.y = step.x, step.y
        contact.down = step.down
        contact.just_pressed = step.down and not was_down
        self.flush()
        if not step.down:
            self.contacts.pop(step.pointer, None)

    def flush(self) -> bool:
        """현재 접점들을 한 프레임으로 주입한다.

        누르고 있는 접점은 움직이지 않아도 계속 보내야 한다 — 빠지면 시스템이 손을 뗀 것으로
        본다.
        """
        if not self.contacts:
            return True
        if not self.initialize():
            return False

        count = len(self.contacts)
        array = (_POINTER_TOUCH_INFO * count)()
        for index, contact in enumerate(self.contacts.values()):
            array[index] = _make_touch_info(contact)
        result = self._user32.InjectTouchInput(count, ctypes.byref(array))
        for contact in self.contacts.values():
            contact.just_pressed = False
        return bool(result)

    def release_all(self) -> None:
        """비정상 종료 대비 — 남아 있는 접점을 전부 뗀다."""
        for contact in self.contacts.values():
            contact.down = False
        self.flush()
        self.contacts.clear()


def _make_touch_info(contact: Contact) -> _POINTER_TOUCH_INFO:
    info = _POINTER_TOUCH_INFO()
    info.pointerInfo.pointerType = PT_TOUCH
    info.pointerInfo.pointerId = contact.pointer
    info.pointerInfo.ptPixelLocation.x = contact.x
    info.pointerInfo.ptPixelLocation.y = contact.y

    if contact.down:
        flags = POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT
        flags |= POINTER_FLAG_DOWN if contact.just_pressed else POINTER_FLAG_UPDATE
        if contact.just_pressed:
            flags |= POINTER_FLAG_NEW
    else:
        flags = POINTER_FLAG_UP
    info.pointerInfo.pointerFlags = flags

    info.touchFlags = TOUCH_FLAG_NONE
    info.touchMask = TOUCH_MASK_CONTACTAREA | TOUCH_MASK_PRESSURE
    info.pressure = contact.pressure
    info.rcContact.left = contact.x - contact.radius
    info.rcContact.right = contact.x + contact.radius
    info.rcContact.top = contact.y - contact.radius
    info.rcContact.bottom = contact.y + contact.radius
    return info


# ---------------------------------------------------------------- 제스처 계획 (순수 함수)


def plan_tap(points: list[tuple[int, int]], hold_ms: int = 80) -> list[Step]:
    """여러 점을 동시에 탭한다."""
    steps: list[Step] = []
    for index, (x, y) in enumerate(points):
        steps.append(Step(TOUCH, x=int(x), y=int(y), down=True, pointer=index))
    for index, (x, y) in enumerate(points):
        steps.append(
            Step(TOUCH, x=int(x), y=int(y), down=False, pointer=index,
                 delay_ms=float(hold_ms) if index == 0 else 0.0)
        )
    return steps


def plan_pinch(
    center: tuple[int, int],
    start_distance: int,
    end_distance: int,
    duration_ms: int = 400,
    steps_count: int = 12,
    angle_deg: float = 0.0,
) -> list[Step]:
    """두 손가락 오므리기/벌리기."""
    cx, cy = center
    radians = math.radians(angle_deg)
    ux, uy = math.cos(radians), math.sin(radians)
    steps: list[Step] = []

    def contact_points(distance: float) -> list[tuple[int, int]]:
        half = distance / 2
        return [
            (int(round(cx - ux * half)), int(round(cy - uy * half))),
            (int(round(cx + ux * half)), int(round(cy + uy * half))),
        ]

    for index, (x, y) in enumerate(contact_points(start_distance)):
        steps.append(Step(TOUCH, x=x, y=y, down=True, pointer=index))

    gap = duration_ms / max(1, steps_count)
    for i in range(1, steps_count + 1):
        ratio = i / steps_count
        distance = start_distance + (end_distance - start_distance) * ratio
        for index, (x, y) in enumerate(contact_points(distance)):
            steps.append(
                Step(TOUCH, x=x, y=y, down=True, pointer=index,
                     delay_ms=gap if index == 0 else 0.0)
            )

    for index, (x, y) in enumerate(contact_points(end_distance)):
        steps.append(Step(TOUCH, x=x, y=y, down=False, pointer=index))
    return steps


def plan_touch_drag(
    path: list[tuple[int, int]],
    duration_ms: int = 400,
    hold_start_ms: int = 80,
    pointer: int = 0,
) -> list[Step]:
    """한 손가락으로 경로를 따라 끈다."""
    if len(path) < 2:
        return []
    steps = [Step(TOUCH, x=int(path[0][0]), y=int(path[0][1]), down=True, pointer=pointer,
                  delay_ms=0.0)]
    gap = duration_ms / max(1, len(path) - 1)
    first = True
    for x, y in path[1:]:
        steps.append(
            Step(TOUCH, x=int(x), y=int(y), down=True, pointer=pointer,
                 delay_ms=hold_start_ms + gap if first else gap)
        )
        first = False
    last_x, last_y = path[-1]
    steps.append(Step(TOUCH, x=int(last_x), y=int(last_y), down=False, pointer=pointer))
    return steps


def plan_rotate(
    center: tuple[int, int],
    radius: int,
    angle_deg: float,
    duration_ms: int = 500,
    steps_count: int = 14,
) -> list[Step]:
    """두 손가락 회전."""
    cx, cy = center
    steps: list[Step] = []

    def contact_points(offset_deg: float) -> list[tuple[int, int]]:
        result = []
        for base in (0.0, 180.0):
            radians = math.radians(base + offset_deg)
            result.append(
                (int(round(cx + math.cos(radians) * radius)),
                 int(round(cy + math.sin(radians) * radius)))
            )
        return result

    for index, (x, y) in enumerate(contact_points(0)):
        steps.append(Step(TOUCH, x=x, y=y, down=True, pointer=index))

    gap = duration_ms / max(1, steps_count)
    for i in range(1, steps_count + 1):
        offset = angle_deg * i / steps_count
        for index, (x, y) in enumerate(contact_points(offset)):
            steps.append(
                Step(TOUCH, x=x, y=y, down=True, pointer=index,
                     delay_ms=gap if index == 0 else 0.0)
            )

    for index, (x, y) in enumerate(contact_points(angle_deg)):
        steps.append(Step(TOUCH, x=x, y=y, down=False, pointer=index))
    return steps
