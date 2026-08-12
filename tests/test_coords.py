"""DPI 좌표 파이프라인 테스트.

배율이 섞인 다중 모니터는 실제로 재현하기 어려우므로, 순수 계산부를 ScreenInfo 목록으로
직접 구성해 검증한다. 여기가 틀리면 모든 클릭이 빗나간다.
"""

from __future__ import annotations

import pytest

from itda.vision.coords import (
    ABSOLUTE_RANGE,
    Rect,
    ScreenInfo,
    clamp_to_screens,
    current_screens,
    describe,
    enable_dpi_awareness,
    screen_at_logical,
    screen_at_physical,
    to_absolute,
    to_logical,
    to_physical,
    virtual_rect,
)

#: 100% 한 대
SINGLE = [ScreenInfo("주", Rect(0, 0, 1920, 1080), 1.0)]

#: 150% 한 대 — Qt 는 논리 1280×720 으로 보고한다
SCALED = [ScreenInfo("주", Rect(0, 0, 1280, 720), 1.5)]

#: 주 모니터 100% + 오른쪽에 150% 보조 (Qt 논리 좌표 기준으로 이어 붙는다)
MIXED = [
    ScreenInfo("주", Rect(0, 0, 1920, 1080), 1.0),
    ScreenInfo("보조", Rect(1920, 0, 1280, 720), 1.5),
]


# ---------------------------------------------------------------- 기본 도형


def test_rect_basics():
    rect = Rect(10, 20, 100, 50)
    assert (rect.right, rect.bottom) == (110, 70)
    assert rect.contains(10, 20)
    assert not rect.contains(110, 70)
    assert rect.united(Rect(200, 0, 10, 10)) == Rect(10, 0, 200, 70)


def test_physical_applies_scale_to_origin_and_size():
    info = MIXED[1]
    assert info.physical == Rect(2880, 0, 1920, 1080)


# ---------------------------------------------------------------- 변환


def test_no_scaling_is_identity():
    assert to_physical(SINGLE, 640, 480) == (640, 480)
    assert to_logical(SINGLE, 640, 480) == (640, 480)


def test_scaled_screen_converts_both_ways():
    assert to_physical(SCALED, 640, 360) == (960, 540)
    assert to_logical(SCALED, 960, 540) == (640, 360)


def test_roundtrip_is_stable_on_every_screen():
    for screens in (SINGLE, SCALED, MIXED):
        for x, y in ((0, 0), (100, 100), (640, 360)):
            px, py = to_physical(screens, x, y)
            assert to_logical(screens, px, py) == (x, y)


def test_secondary_scaled_monitor_keeps_screens_separate():
    """보조 모니터의 좌상단은 논리 (1920,0) 이지만 물리로는 (2880,0) 이다."""
    assert to_physical(MIXED, 1920, 0) == (2880, 0)
    assert to_physical(MIXED, 1920 + 640, 360) == (2880 + 960, 540)
    # 주 모니터 쪽은 배율이 없다
    assert to_physical(MIXED, 100, 100) == (100, 100)


def test_point_outside_all_screens_falls_back_to_first():
    assert screen_at_logical(MIXED, -50, -50) is MIXED[0]
    assert screen_at_physical(MIXED, 99999, 99999) is MIXED[0]
    # 화면 밖이어도 첫 모니터의 배율로 계산해 값을 돌려준다 (예외로 죽지 않는다)
    assert to_physical(SCALED, -100, -100) == (-150, -150)


def test_empty_screen_list_is_identity():
    assert to_physical([], 12, 34) == (12, 34)
    assert to_logical([], 12, 34) == (12, 34)
    assert virtual_rect([]) == Rect(0, 0, 0, 0)


# ---------------------------------------------------------------- 가상 화면


def test_virtual_rect_covers_all_monitors():
    assert virtual_rect(MIXED, physical=True) == Rect(0, 0, 4800, 1080)
    assert virtual_rect(MIXED, physical=False) == Rect(0, 0, 3200, 1080)


def test_virtual_rect_handles_monitor_left_of_primary():
    screens = [
        ScreenInfo("주", Rect(0, 0, 1920, 1080), 1.0),
        ScreenInfo("왼쪽", Rect(-1280, 0, 1280, 1024), 1.0),
    ]
    assert virtual_rect(screens) == Rect(-1280, 0, 3200, 1080)


# ---------------------------------------------------------------- SendInput 절대 좌표


def test_absolute_maps_corners_to_full_range():
    assert to_absolute(SINGLE, 0, 0) == (0, 0)
    assert to_absolute(SINGLE, 1920, 1080) == (ABSOLUTE_RANGE, ABSOLUTE_RANGE)


def test_absolute_center_is_half_range():
    x, y = to_absolute(SINGLE, 960, 540)
    assert x == pytest.approx(ABSOLUTE_RANGE // 2, abs=2)
    assert y == pytest.approx(ABSOLUTE_RANGE // 2, abs=2)


def test_absolute_accounts_for_negative_virtual_origin():
    """왼쪽에 모니터가 있으면 가상 원점이 음수다. 이걸 빼지 않으면 좌표가 통째로 밀린다."""
    screens = [
        ScreenInfo("주", Rect(0, 0, 1920, 1080), 1.0),
        ScreenInfo("왼쪽", Rect(-1920, 0, 1920, 1080), 1.0),
    ]
    assert to_absolute(screens, -1920, 0) == (0, 0)
    assert to_absolute(screens, 1920, 1080) == (ABSOLUTE_RANGE, ABSOLUTE_RANGE)


def test_absolute_is_clamped():
    assert to_absolute(SINGLE, -500, -500) == (0, 0)
    assert to_absolute(SINGLE, 99999, 99999) == (ABSOLUTE_RANGE, ABSOLUTE_RANGE)


def test_clamp_keeps_points_on_screen():
    assert clamp_to_screens(SINGLE, -10, 5000) == (0, 1079)
    assert clamp_to_screens(SINGLE, 300, 300) == (300, 300)


# ---------------------------------------------------------------- 실제 환경


def test_enable_dpi_awareness_reports_a_mode():
    mode = enable_dpi_awareness()
    assert isinstance(mode, str) and mode


def test_current_screens_are_readable(qapp):
    screens = current_screens()
    assert isinstance(screens, list)
    for info in screens:
        assert info.scale > 0
        assert info.physical.width > 0
    assert isinstance(describe(screens), str)


def test_describe_handles_no_screens():
    assert "찾지 못" in describe([])
