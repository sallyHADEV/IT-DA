"""GDI 캡처 — 핸들 정리 순서와 64비트 프로토타입.

실측으로 먼저 확인한 것: 이 머신(Windows 11 x64)에서는 `SelectObject` 로 되돌리지 않고
바로 `DeleteObject` 해도 곧이어 `DeleteDC` 가 미뤄진 삭제를 마무리해 버려서, 핸들 카운트
(`GetGuiResources`)로는 새는 것도 안 새는 것도 구분이 안 됐다 — DC 가 죽으면서 "선택된
채 지워졌던" 비트맵을 같이 정리하기 때문이다. 이건 문서화된 동작이 아니라 이 빌드의
구현 세부사항이라 다른 Windows 버전·드라이버(특히 원격 데스크톱)에서는 그대로 새는 사례가
보고돼 있다. 그래서 여기서는 핸들 카운트 대신 **호출 순서 자체**를 검증한다:
새 비트맵을 지우기 전에 반드시 예전 비트맵으로 되돌려 선택해야 한다.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows GDI 전용")

from itda.vision import gdi_capture  # noqa: E402


@pytest.fixture(autouse=True)
def _ensure_prototypes():
    gdi_capture.is_available()  # argtypes/restype 설정을 강제로 실행해 둔다


def test_prototypes_are_pointer_sized_not_c_int():
    """restype 이 없으면 ctypes 는 c_int(32비트)를 가정해 64비트 핸들을 자른다."""
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32

    # HDC/HBITMAP/HGDIOBJ 는 전부 포인터 크기여야 한다 — c_int/c_long 이면 안 된다
    for func, name in (
        (user32.GetDC, "GetDC"),
        (gdi32.CreateCompatibleDC, "CreateCompatibleDC"),
        (gdi32.CreateCompatibleBitmap, "CreateCompatibleBitmap"),
        (gdi32.SelectObject, "SelectObject"),
    ):
        assert ctypes.sizeof(func.restype) == ctypes.sizeof(ctypes.c_void_p), name


def test_bitmap_is_unselected_before_it_is_deleted():
    """DeleteObject(bitmap) 시점에 그 비트맵이 이미 DC 에서 빠져 있어야 한다.

    Win32 문서는 "선택된 객체를 지우지 말라" 고만 말하고 실패 여부는 구현에 맡긴다 — 이
    머신은 조용히 지연 삭제로 넘어가지만, 그 사실에 기대면 안 된다. 실제 GDI 함수를 감싸서
    호출 순서를 기록한다.
    """
    gdi32 = gdi_capture.gdi32
    calls: list[tuple[str, int, int]] = []  # (함수, dc, obj)

    real_select = gdi32.SelectObject
    real_delete = gdi32.DeleteObject
    selected_in: dict[int, int] = {}  # dc -> 지금 선택된 객체

    def _val(x):
        return getattr(x, "value", x)

    def fake_select(dc, obj):
        v_dc = _val(dc)
        v_obj = _val(obj)
        result = real_select(dc, obj)
        selected_in[v_dc] = v_obj
        calls.append(("select", v_dc, v_obj))
        return _val(result)

    def fake_delete(obj):
        h_obj = _val(obj)
        still_selected = [dc for dc, o in selected_in.items() if _val(o) == h_obj]
        calls.append(("delete", 0, h_obj))
        assert not still_selected, f"{h_obj} 가 여전히 DC {still_selected} 에 선택된 채 삭제됨"
        return real_delete(obj)

    proto_select = ctypes.WINFUNCTYPE(wintypes.HGDIOBJ, wintypes.HDC, wintypes.HGDIOBJ)
    proto_delete = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HGDIOBJ)

    c_fake_select = proto_select(fake_select)
    c_fake_delete = proto_delete(fake_delete)

    gdi32.SelectObject = c_fake_select
    gdi32.DeleteObject = c_fake_delete
    try:
        image = gdi_capture.grab(0, 0, 40, 40)
    finally:
        gdi32.SelectObject = real_select
        gdi32.DeleteObject = real_delete

    assert image.ndim == 3
    kinds = [c[0] for c in calls]
    assert kinds.count("select") == 2  # 새 비트맵 선택 + 원래 비트맵으로 복원
    assert kinds.count("delete") == 1


def test_repeated_capture_does_not_grow_the_gdi_object_table():
    """반복 캡처가 끝날 때마다 프로세스 GDI 객체 수가 원상태로 돌아오는지.

    DeleteDC 의 지연 정리에 기대지 않는다는 걸 보여 주려고, DeleteDC 를 부르기 **전에**
    스냅샷을 뜬다 — SelectObject 복원 자체가 즉시 자원을 돌려주는지 확인하기 위해서다.
    """
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    user32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    user32.GetGuiResources.restype = wintypes.DWORD
    proc = kernel32.GetCurrentProcess()

    def count() -> int:
        return user32.GetGuiResources(proc, 0)  # GR_GDIOBJECTS

    before = count()
    for _ in range(50):
        gdi_capture.grab(0, 0, 60, 60)
    after = count()

    assert after <= before + 2  # 여유를 조금 두되, 반복 횟수만큼 늘면 안 된다
