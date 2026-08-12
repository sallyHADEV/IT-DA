"""사람처럼 움직이기 — 궤적 생성과 스위치 UI 테스트."""

from __future__ import annotations

import math
import random

import pytest

from itda.core.humanize import (
    HumanProfile,
    click_hold_ms,
    describe,
    idle_drift_offset,
    mouse_path,
    typing_delays,
)

START = (100.0, 400.0)
END = (700.0, 120.0)


def _rng() -> random.Random:
    return random.Random(1234)


def _max_deviation(points) -> float:
    """직선에서 가장 많이 벗어난 거리."""
    x0, y0 = START
    x1, y1 = END
    length = math.hypot(x1 - x0, y1 - y0)
    worst = 0.0
    for p in points:
        # 점과 직선 사이 거리
        distance = abs((x1 - x0) * (y0 - p.y) - (x0 - p.x) * (y1 - y0)) / length
        worst = max(worst, distance)
    return worst


# ---------------------------------------------------------------- 궤적


def test_path_starts_near_start_and_ends_at_target():
    points = mouse_path(START, END, HumanProfile(), rng=_rng())
    assert points[-1].x == pytest.approx(END[0], abs=1.5)
    assert points[-1].y == pytest.approx(END[1], abs=1.5)


def test_disabled_profile_is_a_straight_line():
    points = mouse_path(START, END, HumanProfile(enabled=False), rng=_rng())
    assert _max_deviation(points) < 0.01


def test_curve_bends_away_from_the_straight_line():
    curved = mouse_path(START, END, HumanProfile(curve=True, curvature=0.3), rng=_rng())
    assert _max_deviation(curved) > 20


def test_curvature_controls_how_far_it_bends():
    gentle = _max_deviation(mouse_path(START, END, HumanProfile(curvature=0.05), rng=_rng()))
    strong = _max_deviation(mouse_path(START, END, HumanProfile(curvature=0.5), rng=_rng()))
    assert strong > gentle * 2


def test_curve_off_keeps_the_line_straight_even_when_enabled():
    profile = HumanProfile(enabled=True, curve=False, speed_variation=True)
    assert _max_deviation(mouse_path(START, END, profile, rng=_rng())) < 0.01


def test_speed_variation_makes_step_distances_uneven():
    even = mouse_path(START, END, HumanProfile(enabled=False), rng=_rng())
    varied = mouse_path(
        START, END, HumanProfile(curve=False, speed_variation=True), rng=_rng()
    )

    def spread(points):
        gaps = [
            math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(points, points[1:])
        ]
        return max(gaps) / max(1e-9, min(gaps))

    assert spread(even) == pytest.approx(1.0, abs=0.05)
    assert spread(varied) > 2.0


def test_total_duration_is_preserved():
    points = mouse_path(START, END, HumanProfile(micro_pause=False), duration_ms=500, rng=_rng())
    total = sum(p.delay_ms for p in points)
    assert total == pytest.approx(500, rel=0.02)


def test_micro_pause_adds_time():
    base = sum(p.delay_ms for p in mouse_path(START, END, HumanProfile(micro_pause=False),
                                              duration_ms=500, rng=_rng()))
    paused = sum(p.delay_ms for p in mouse_path(START, END, HumanProfile(micro_pause=True),
                                                duration_ms=500, rng=_rng()))
    assert paused > base


def test_overshoot_goes_past_the_target_and_comes_back():
    points = mouse_path(START, END, HumanProfile(overshoot=True, curve=False), rng=_rng())
    x1, y1 = END
    distance_from_start = [math.hypot(p.x - START[0], p.y - START[1]) for p in points]
    target_distance = math.hypot(x1 - START[0], y1 - START[1])

    assert max(distance_from_start) > target_distance + 3  # 지나쳤다
    assert points[-1].x == pytest.approx(x1, abs=0.5)      # 되돌아왔다
    assert points[-1].y == pytest.approx(y1, abs=0.5)


def test_same_seed_gives_the_same_path():
    first = mouse_path(START, END, HumanProfile(), rng=random.Random(7))
    second = mouse_path(START, END, HumanProfile(), rng=random.Random(7))
    assert [(p.x, p.y) for p in first] == [(p.x, p.y) for p in second]


def test_different_seeds_give_different_paths():
    first = mouse_path(START, END, HumanProfile(), rng=random.Random(1))
    second = mouse_path(START, END, HumanProfile(), rng=random.Random(2))
    assert [(p.x, p.y) for p in first] != [(p.x, p.y) for p in second]


def test_zero_distance_is_handled():
    points = mouse_path((10, 10), (10, 10), HumanProfile(), rng=_rng())
    assert len(points) == 1


def test_step_count_scales_with_distance():
    short = mouse_path((0, 0), (60, 0), HumanProfile(), rng=_rng())
    long = mouse_path((0, 0), (1200, 0), HumanProfile(), rng=_rng())
    assert len(long) > len(short)


# ---------------------------------------------------------------- 그 외 모사


def test_typing_delays_are_uniform_when_disabled():
    assert typing_delays(5, 40, HumanProfile(typing_rhythm=False)) == [40.0] * 5


def test_typing_delays_vary_when_enabled():
    delays = typing_delays(40, 40, HumanProfile(), rng=_rng())
    assert len(set(delays)) > 30
    assert min(delays) > 0


def test_click_hold_varies_only_when_enabled():
    assert click_hold_ms(60, HumanProfile(click_hold_variation=False)) == 60.0
    assert click_hold_ms(60, HumanProfile(), rng=_rng()) != 60.0


def test_idle_drift_is_zero_when_off():
    assert idle_drift_offset(3, HumanProfile(idle_drift=False)) == (0, 0)
    dx, dy = idle_drift_offset(3, HumanProfile(idle_drift=True), rng=_rng())
    assert abs(dx) <= 3 and abs(dy) <= 3


def test_master_switch_overrides_everything():
    profile = HumanProfile(enabled=False, curve=True, typing_rhythm=True,
                           click_hold_variation=True, idle_drift=True)
    assert _max_deviation(mouse_path(START, END, profile, rng=_rng())) < 0.01
    assert typing_delays(4, 30, profile) == [30.0] * 4
    assert click_hold_ms(50, profile) == 50.0
    assert idle_drift_offset(4, profile) == (0, 0)


def test_describe_lists_enabled_items():
    assert "꺼짐" in describe(HumanProfile(enabled=False))
    text = describe(HumanProfile(curve=True, speed_variation=True, overshoot=False))
    assert "곡선 궤적" in text and "속도 변화" in text and "오버슈트" not in text


# ---------------------------------------------------------------- 저장


def test_human_profile_is_saved_with_project(tmp_path, project):
    from itda.core.project import Project

    project.settings.human.overshoot = True
    project.settings.human.curvature = 0.42
    project.settings.human.typing_rhythm = False
    project.save(tmp_path / "p")

    loaded = Project.load(tmp_path / "p")

    assert loaded.settings.human.overshoot is True
    assert loaded.settings.human.curvature == 0.42
    assert loaded.settings.human.typing_rhythm is False


def test_old_project_without_human_section_still_loads(tmp_path, project):
    """1차에서 저장한 프로젝트에는 human 항목이 없다."""
    import json

    from itda.core.project import Project

    project.save(tmp_path / "p")
    settings_file = tmp_path / "p" / "project.json"
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    del data["human"]
    settings_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    loaded = Project.load(tmp_path / "p")
    assert loaded.settings.human == HumanProfile()


# ---------------------------------------------------------------- 스위치 UI


def test_switch_row_reflects_state(qapp):
    from itda.gui.widgets.toggle_switch import SwitchRow

    row = SwitchRow("curve", "곡선 궤적", "설명", checked=False)
    assert row.isChecked() is False

    row.setChecked(True)
    assert row.isChecked() is True


def test_timing_dialog_switches_write_to_profile(qapp, project):
    from itda.gui.dialogs.timing_dialog import TimingProfileDialog

    dialog = TimingProfileDialog(project)
    dialog.switch_rows["overshoot"].setChecked(True)
    dialog.switch_rows["typing_rhythm"].setChecked(False)
    dialog.curvature.setValue(45)

    dialog.accept()

    human = project.settings.human
    assert human.overshoot is True
    assert human.typing_rhythm is False
    assert human.curvature == pytest.approx(0.45)


def test_master_switch_disables_sub_switches(qapp, project):
    from itda.gui.dialogs.timing_dialog import TimingProfileDialog

    dialog = TimingProfileDialog(project)
    dialog.master.setChecked(False)
    dialog._on_master_toggled(False)

    assert all(not row.isEnabled() for row in dialog.switch_rows.values())
    assert dialog.human.enabled is False


def test_preview_uses_the_real_path_generator(qapp, project):
    from itda.gui.dialogs.timing_dialog import TimingProfileDialog

    dialog = TimingProfileDialog(project)
    dialog.preview.resize(300, 140)
    dialog.preview.regenerate()
    straight_points = len(dialog.preview._points)

    dialog.switch_rows["overshoot"].setChecked(True)
    dialog._on_switch("overshoot", True)

    assert dialog.preview.profile.overshoot is True
    assert len(dialog.preview._points) >= straight_points


def test_timing_dialog_keeps_timing_tab_working(qapp, project):
    from itda.gui.dialogs.timing_dialog import TimingProfileDialog

    dialog = TimingProfileDialog(project)
    dialog.jitter.setValue(0.35)
    dialog.accept()

    assert project.settings.timing.jitter_pct == 0.35
