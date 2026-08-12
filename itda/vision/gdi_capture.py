"""GDI 화면 캡처 (Windows).

Qt 의 ``QScreen.grabWindow`` 는 GUI 스레드에서만 안전하다. 여러 플로우를 동시에 돌리려면
작업 스레드에서도 화면을 찍어야 하므로, Qt 를 거치지 않는 BitBlt 경로를 둔다.
덤으로 더 빠르다.

좌표는 물리 픽셀이다(:mod:`itda.vision.coords` 규칙). 프로세스가 Per-Monitor DPI Aware 로
선언돼 있어야 화면 크기가 실제 픽셀과 일치한다 — 앱 시작 첫 줄에서 선언한다.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

import numpy as np

# GetSystemMetrics 인덱스 — 가상 화면(모든 모니터를 합친 영역)
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000  # 레이어드 창(반투명 창)까지 포함
DIB_RGB_COLORS = 0
BI_RGB = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


_prototypes_configured = False


user32 = ctypes.windll.user32 if sys.platform == "win32" else None
gdi32 = ctypes.windll.gdi32 if sys.platform == "win32" else None


def _configure_prototypes() -> None:
    """GDI/User32 함수의 ``argtypes``/``restype`` 을 명시한다 (한 번만).

    ``ctypes`` 는 이걸 안 정하면 반환값을 ``c_int``(32비트)를 가정한다. 64비트 Windows 의
    HDC/HBITMAP 핸들은 상위 비트가 그대로 잘려 나가고, 잘린 핸들로 다음 GDI 호출을 하면
    실패하거나(대개 조용히 실패) 최악의 경우 Access Violation 으로 죽는다. 매번 새 DC/비트맵을
    만드는 이 모듈에서는 캡처를 반복할수록 발동 확률이 올라간다.
    """
    global _prototypes_configured
    if _prototypes_configured or not user32 or not gdi32:
        return

    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
    ]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.POINTER(_BITMAPINFO), wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL

    _prototypes_configured = True


def is_available() -> bool:
    if sys.platform != "win32":  # pragma: no cover - 다른 OS
        return False
    _configure_prototypes()
    return True


def virtual_rect() -> tuple[int, int, int, int]:
    """가상 화면 (x, y, w, h) — 물리 픽셀."""
    if not is_available():  # pragma: no cover - 다른 OS
        return (0, 0, 0, 0)
    user32 = ctypes.windll.user32
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def grab(x: int | None = None, y: int | None = None,
         width: int | None = None, height: int | None = None) -> np.ndarray:
    """화면을 BGR 배열로 찍는다. 인자를 비우면 가상 화면 전체.

    실패하면 빈 배열을 돌려준다 — 호출부가 Qt 경로로 되돌아갈 수 있게.
    """
    if not is_available():  # pragma: no cover - 다른 OS
        return _empty()

    vx, vy, vw, vh = virtual_rect()
    x = vx if x is None else x
    y = vy if y is None else y
    width = vw if width is None else width
    height = vh if height is None else height
    if width <= 0 or height <= 0:
        return _empty()

    if not user32 or not gdi32:
        return _empty()

    screen_dc = user32.GetDC(None)
    if not screen_dc:
        return _empty()

    memory_dc = bitmap = old_bitmap = None
    try:
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        if not memory_dc or not bitmap:
            return _empty()
        old_bitmap = gdi32.SelectObject(memory_dc, bitmap)
        raw_old = old_bitmap.value if isinstance(old_bitmap, ctypes.c_void_p) else old_bitmap
        ptr_mask = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1
        if raw_old is None or raw_old in (0, -1, ptr_mask, 0xFFFFFFFF) or (isinstance(raw_old, int) and (raw_old & ptr_mask) == ptr_mask):
            restore_bitmap = None
        else:
            restore_bitmap = raw_old

        if not gdi32.BitBlt(memory_dc, 0, 0, width, height,
                            screen_dc, x, y, SRCCOPY | CAPTUREBLT):
            return _empty()

        info = _BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # 음수 = 위에서 아래로 (뒤집힘 방지)
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB

        buffer = ctypes.create_string_buffer(width * height * 4)
        copied = gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer,
                                 ctypes.byref(info), DIB_RGB_COLORS)
        if copied == 0:
            return _empty()

        array = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)
        return array[:, :, :3].copy()  # BGRA → BGR
    finally:
        if memory_dc and restore_bitmap is not None:
            gdi32.SelectObject(memory_dc, restore_bitmap)  # 지우기 전에 반드시 빼낸다
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)


def _empty() -> np.ndarray:
    return np.zeros((0, 0, 3), dtype=np.uint8)
