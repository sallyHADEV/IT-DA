"""창 위치·크기 제어 테스트.

계산부만 검증한다 — 실제 창은 건드리지 않는다(conftest 의 안전장치가 막는다).
"""

from __future__ import annotations

import pytest

from itda.core import registry
from itda.core.window_spec import (
    Box,
    clamp_to_monitor,
    pick_monitor,
    plan_geometry,
    resolve_geometry,
    summarize,
    window_params,
)
from itda.engine.window import FramePad, match_title

MONITOR = Box(0, 0, 1920, 1080)
SECOND = Box(1920, 0, 1280, 1024)
WINDOW = Box(300, 200, 800, 600)


def params(**overrides) -> dict:
    base = {f.name: f.default for f in window_params()}
    base.update(overrides)
    return base


# ---------------------------------------------------------------- 위치 / 크기


def test_move_keeps_the_size():
    box = resolve_geometry(params(op="move", point=[100, 50]), WINDOW, MONITOR)
    assert box == Box(100, 50, 800, 600)


def test_resize_keeps_the_position():
    box = resolve_geometry(params(op="resize", size=[1024, 768]), WINDOW, MONITOR)
    assert box == Box(300, 200, 1024, 768)


def test_move_resize_sets_both():
    box = resolve_geometry(
        params(op="move_resize", point=[0, 0], size=[1280, 720]), WINDOW, MONITOR
    )
    assert box == Box(0, 0, 1280, 720)


def test_zero_size_keeps_that_axis():
    """가로만 고정하고 세로는 그대로 두고 싶을 때."""
    box = resolve_geometry(params(op="resize", size=[1000, 0]), WINDOW, MONITOR)
    assert box == Box(300, 200, 1000, 600)


def test_non_geometry_ops_return_nothing():
    for op in ("activate", "minimize", "maximize", "restore", "close", "exists", "topmost"):
        assert resolve_geometry(params(op=op), WINDOW, MONITOR) is None


# ---------------------------------------------------------------- 프리셋


@pytest.mark.parametrize(
    "preset,expected",
    [
        ("fill", Box(0, 0, 1920, 1080)),
        ("left_half", Box(0, 0, 960, 1080)),
        ("right_half", Box(960, 0, 960, 1080)),
        ("top_half", Box(0, 0, 1920, 540)),
        ("bottom_half", Box(0, 540, 1920, 540)),
        ("top_left", Box(0, 0, 960, 540)),
        ("top_right", Box(960, 0, 960, 540)),
        ("bottom_left", Box(0, 540, 960, 540)),
        ("bottom_right", Box(960, 540, 960, 540)),
    ],
)
def test_presets(preset, expected):
    assert resolve_geometry(params(op="preset", preset=preset), WINDOW, MONITOR) == expected


def test_center_keeps_size_and_centers():
    box = resolve_geometry(params(op="preset", preset="center"), WINDOW, MONITOR)
    assert box == Box(560, 240, 800, 600)
    assert box.center == MONITOR.center


def test_presets_follow_the_monitor_origin():
    box = resolve_geometry(params(op="preset", preset="left_half"), WINDOW, SECOND)
    assert box == Box(1920, 0, 640, 1024)


def test_odd_sizes_do_not_leave_a_gap():
    """절반으로 나눌 때 홀수 픽셀이 사라지면 안 된다."""
    monitor = Box(0, 0, 1921, 1081)
    left = resolve_geometry(params(op="preset", preset="left_half"), WINDOW, monitor)
    right = resolve_geometry(params(op="preset", preset="right_half"), WINDOW, monitor)
    assert left.right == right.x
    assert right.right == monitor.right


# ---------------------------------------------------------------- 화면 밖 방지


def test_clamp_pulls_the_window_back_on_screen():
    assert clamp_to_monitor(Box(1800, 1000, 800, 600), MONITOR) == Box(1120, 480, 800, 600)
    assert clamp_to_monitor(Box(-300, -200, 400, 300), MONITOR) == Box(0, 0, 400, 300)


def test_clamp_shrinks_windows_bigger_than_the_monitor():
    assert clamp_to_monitor(Box(0, 0, 3000, 2000), MONITOR) == Box(0, 0, 1920, 1080)


def test_clamp_leaves_a_fitting_window_alone():
    box = Box(100, 100, 800, 600)
    assert clamp_to_monitor(box, MONITOR) == box


# ---------------------------------------------------------------- 보이지 않는 테두리

# 실측값 (Windows 11): 요청 (100,200,800,600) → 보이는 창 (107,200,786,593)
REAL_PAD = FramePad(left=7, top=0, width=14, height=7)


def test_visible_box_is_smaller_than_the_api_rectangle():
    """창 사각형에는 폭 7px 안팎의 투명한 리사이즈 테두리가 들어 있다."""
    assert REAL_PAD.to_visible(Box(100, 200, 800, 600)) == Box(107, 200, 786, 593)


def test_asked_position_is_what_the_eye_sees():
    """(100,200) 을 요청하면 **보이는 창**이 (100,200) 이어야 한다."""
    raw = REAL_PAD.to_raw(Box(100, 200, 800, 600))

    assert raw == Box(93, 200, 814, 607)  # SetWindowPos 에 넣을 값
    assert REAL_PAD.to_visible(raw) == Box(100, 200, 800, 600)  # 되돌리면 요청한 값


def test_no_padding_changes_nothing():
    """테두리를 못 재는 창(구형 창 등)은 그대로 둔다."""
    box = Box(10, 20, 300, 400)
    assert FramePad().to_raw(box) == box
    assert FramePad().to_visible(box) == box


# ---------------------------------------------------------------- 모니터 선택


def test_current_monitor_is_where_the_window_sits():
    on_second = Box(2000, 100, 400, 300)
    assert pick_monitor("current", on_second, [MONITOR, SECOND]) == SECOND
    assert pick_monitor("current", WINDOW, [MONITOR, SECOND]) == MONITOR


def test_primary_and_numbered_monitors():
    assert pick_monitor("primary", Box(2000, 0, 10, 10), [MONITOR, SECOND]) == MONITOR
    assert pick_monitor("2", WINDOW, [MONITOR, SECOND]) == SECOND
    assert pick_monitor("9", WINDOW, [MONITOR, SECOND]) == MONITOR  # 없는 번호는 주 모니터


def test_no_monitors_falls_back():
    assert pick_monitor("current", WINDOW, []).width == 1920


# ---------------------------------------------------------------- 전체 계산


def test_absolute_move_can_cross_to_another_monitor():
    """2번 모니터에 있는 창을 (100,50) 으로 옮기라고 하면 정말 거기로 가야 한다.

    지금 있는 모니터로 가둬 버리면 2번 모니터 구석으로 밀려 엉뚱한 자리에 놓인다.
    """
    on_second = Box(2000, 100, 800, 600)
    box = plan_geometry(params(op="move", point=[100, 50]), on_second, [MONITOR, SECOND])
    assert box == Box(100, 50, 800, 600)


def test_absolute_move_still_keeps_the_window_on_screen():
    """넘어갈 수 있다고 화면 밖까지 나가도 된다는 뜻은 아니다."""
    box = plan_geometry(params(op="move", point=[1800, 1000]), WINDOW, [MONITOR, SECOND])
    assert box == Box(1120, 480, 800, 600)


def test_preset_stays_on_the_monitor_the_window_is_on():
    """배치는 '지금 있는 화면' 기준이 맞다 — 절대 좌표가 아니니까."""
    on_second = Box(2000, 100, 400, 300)
    box = plan_geometry(params(op="preset", preset="fill"), on_second, [MONITOR, SECOND])
    assert box == SECOND


def test_explicit_monitor_setting_wins():
    box = plan_geometry(params(op="move", point=[100, 50], monitor="2"), WINDOW,
                        [MONITOR, SECOND])
    assert box == Box(1920, 50, 800, 600)  # x 는 2번 모니터 안으로 당겨진다


def test_non_geometry_ops_plan_nothing():
    assert plan_geometry(params(op="activate"), WINDOW, [MONITOR]) is None


# ---------------------------------------------------------------- 제목 일치


def test_title_matching_modes():
    assert match_title("제목 없음 - Windows 메모장", "메모장")
    assert not match_title("메모장", "계산기")
    assert match_title("메모장", "메모장", "exact")
    assert not match_title("메모장 - 새 파일", "메모장", "exact")
    assert match_title("문서1 - Word", r"문서\d+", "regex")
    assert not match_title("문서 - Word", r"문서\d+", "regex")


def test_empty_pattern_matches_anything():
    assert match_title("아무 창", "")


def test_broken_regex_does_not_raise():
    assert match_title("창", "[미완성", "regex") is False


# ---------------------------------------------------------------- 등록 / 표시


def test_window_node_and_action_share_the_same_schema():
    registry.load_builtins()
    node = registry.node_type("window")
    action = registry.action_type("window")

    assert node is not None and action is not None
    node_fields = {f.name for f in node.params}
    action_fields = {f.name for f in action.PARAMS}
    assert node_fields == action_fields


def test_summaries_are_readable():
    assert "1280×720" in summarize(params(op="move_resize", title="메모장",
                                          point=[0, 0], size=[1280, 720]))
    assert "가운데" in summarize(params(op="preset", preset="center"))
    assert "최대화" in summarize(params(op="maximize"))
    assert "왼쪽 절반" in summarize(params(op="preset", preset="left_half"))


def test_summary_without_title_says_target_window():
    assert "대상 창" in summarize(params(op="activate"))
