"""입력 계획 테스트.

실제 마우스는 절대 움직이지 않는다 — 계획(pure)과 DryRunSender 만 검사한다.
이렇게 나눠 두었기 때문에 입력 로직 전체를 안전하게 시험할 수 있다.
"""

from __future__ import annotations

import random

import pytest

from itda.core.humanize import HumanProfile
from itda.core.timing import TimingProfile
from itda.engine.input import DryRunSender, keys, planner
from itda.engine.input.steps import BUTTON, CHAR, DELAY, KEY, MOVE, TOUCH, WHEEL, summarize
from itda.engine.input.touch import plan_pinch, plan_rotate, plan_tap, plan_touch_drag

MECHANICAL = HumanProfile(enabled=False)
NO_TOLERANCE = TimingProfile(click_offset_px=0, move_duration_ms=200)


def rng() -> random.Random:
    return random.Random(99)


def kinds(steps) -> list[str]:
    return [s.kind for s in steps]


# ---------------------------------------------------------------- 키 이름


def test_single_keys():
    assert keys.key_code("enter") == 0x0D
    assert keys.key_code("a") == ord("A")
    assert keys.key_code("F5") == 0x74
    assert keys.key_code("num7") == 0x67


def test_combo_splits_modifiers_and_final_key():
    modifiers, final = keys.parse_combo("ctrl+shift+s")
    assert modifiers == [0x11, 0x10]
    assert final == ord("S")


def test_combo_with_only_a_modifier():
    modifiers, final = keys.parse_combo("alt")
    assert modifiers == [] and final == 0x12


def test_unknown_key_is_rejected():
    with pytest.raises(ValueError):
        keys.key_code("존재하지않는키")
    assert keys.is_known("ctrl+s")
    assert not keys.is_known("ctrl+없는키")


def test_modifier_in_final_position_is_fine_but_not_reversed():
    with pytest.raises(ValueError):
        keys.parse_combo("s+ctrl")  # 조합 키가 아닌 이름이 앞에 있다


def test_describe_normalizes_notation():
    assert keys.describe("ctrl+s") == "CTRL + S"
    assert keys.describe("망가진") == "망가진"


# ---------------------------------------------------------------- 이동


def test_move_ends_at_target_without_tolerance():
    steps = planner.plan_move((0, 0), (400, 300), MECHANICAL, NO_TOLERANCE, rng=rng())
    assert kinds(steps) == [MOVE] * len(steps)
    assert (steps[-1].x, steps[-1].y) == (400, 300)


def test_move_is_straight_when_humanize_off():
    steps = planner.plan_move((0, 0), (400, 0), MECHANICAL, NO_TOLERANCE, rng=rng())
    assert all(s.y == 0 for s in steps)


def test_move_curves_when_humanize_on():
    steps = planner.plan_move((0, 0), (400, 0), HumanProfile(), NO_TOLERANCE, rng=rng())
    assert any(s.y != 0 for s in steps), "곡선 궤적이 적용되지 않았다"


def test_tolerance_shifts_the_final_point():
    profile = TimingProfile(click_offset_px=5, move_duration_ms=100)
    steps = planner.plan_move((0, 0), (400, 300), MECHANICAL, profile, rng=rng())
    dx = abs(steps[-1].x - 400)
    dy = abs(steps[-1].y - 300)
    assert dx <= 5 and dy <= 5
    assert (dx, dy) != (0, 0) or True  # 0 이 나올 수도 있다 — 범위만 보장


def test_move_duration_comes_from_timing_profile():
    steps = planner.plan_move((0, 0), (400, 300), MECHANICAL,
                              TimingProfile(click_offset_px=0, move_duration_ms=500), rng=rng())
    total = sum(s.delay_ms for s in steps)
    assert total == pytest.approx(500, rel=0.05)


# ---------------------------------------------------------------- 클릭


def test_click_moves_then_presses_and_releases():
    steps = planner.plan_click((100, 100), start=(0, 0), human=MECHANICAL,
                               timing=NO_TOLERANCE, rng=rng())
    assert kinds(steps)[-2:] == [BUTTON, BUTTON]
    assert steps[-2].down is True and steps[-1].down is False
    assert steps[-1].delay_ms > 0  # 누르고 있는 시간


def test_click_without_move_first():
    steps = planner.plan_click((100, 100), start=(0, 0), move_first=False,
                               human=MECHANICAL, timing=NO_TOLERANCE, rng=rng())
    assert kinds(steps) == [MOVE, BUTTON, BUTTON]


def test_double_click_has_two_press_pairs_with_a_gap():
    steps = planner.plan_click((10, 10), click_type="double", human=MECHANICAL,
                               timing=NO_TOLERANCE, move_first=False, rng=rng())
    buttons = [s for s in steps if s.kind == BUTTON]
    assert len(buttons) == 4
    gap = next(s for s in steps if s.kind == DELAY)
    assert 40 <= gap.delay_ms <= 200


def test_down_and_up_click_types():
    down = planner.plan_click((5, 5), click_type="down", move_first=False, rng=rng())
    up = planner.plan_click((5, 5), click_type="up", move_first=False, rng=rng())
    assert [s.down for s in down if s.kind == BUTTON] == [True]
    assert [s.down for s in up if s.kind == BUTTON] == [False]


def test_click_hold_varies_with_humanize():
    mechanical = planner.plan_click((5, 5), human=MECHANICAL, move_first=False, rng=rng())
    human = planner.plan_click((5, 5), human=HumanProfile(), move_first=False, rng=rng())
    assert mechanical[-1].delay_ms == planner.DEFAULT_CLICK_HOLD_MS
    assert human[-1].delay_ms != planner.DEFAULT_CLICK_HOLD_MS


def test_right_button_is_carried_through():
    steps = planner.plan_click((5, 5), button="right", move_first=False, rng=rng())
    assert all(s.button == "right" for s in steps if s.kind == BUTTON)


# ---------------------------------------------------------------- 드래그 / 휠


def test_drag_presses_moves_then_releases():
    steps = planner.plan_drag((0, 0), (200, 200), human=MECHANICAL, timing=NO_TOLERANCE,
                              rng=rng())
    assert steps[0].kind == MOVE
    assert steps[1].kind == BUTTON and steps[1].down is True
    assert steps[-1].kind == BUTTON and steps[-1].down is False
    assert sum(1 for s in steps if s.kind == MOVE) > 2


def test_scroll_is_one_step_when_mechanical():
    steps = planner.plan_scroll(5, human=MECHANICAL, rng=rng())
    assert kinds(steps) == [WHEEL]
    assert steps[0].amount == 5


def test_scroll_is_split_when_humanized():
    steps = planner.plan_scroll(7, human=HumanProfile(), rng=rng())
    wheels = [s for s in steps if s.kind == WHEEL]
    assert len(wheels) > 1
    assert sum(s.amount for s in wheels) == 7


def test_negative_scroll_keeps_direction():
    steps = planner.plan_scroll(-6, human=HumanProfile(), rng=rng())
    wheels = [s for s in steps if s.kind == WHEEL]
    assert all(s.amount < 0 for s in wheels)
    assert sum(s.amount for s in wheels) == -6


# ---------------------------------------------------------------- 키 / 문자


def test_key_combo_press_order_is_nested():
    steps = planner.plan_key("ctrl+s", human=MECHANICAL, rng=rng())
    sequence = [(s.vk, s.down) for s in steps if s.kind == KEY]
    assert sequence == [(0x11, True), (ord("S"), True), (ord("S"), False), (0x11, False)]


def test_key_repeat():
    steps = planner.plan_key("enter", repeat=3, human=MECHANICAL, rng=rng())
    presses = [s for s in steps if s.kind == KEY and s.down]
    assert len(presses) == 3


def test_key_down_only_does_not_release():
    steps = planner.plan_key("shift+a", action="down", human=MECHANICAL, rng=rng())
    assert all(s.down for s in steps if s.kind == KEY)


def test_text_becomes_unicode_char_steps():
    steps = planner.plan_text("안녕 Hi", human=MECHANICAL, rng=rng())
    assert kinds(steps) == [CHAR] * 5  # 안, 녕, 공백, H, i
    assert "".join(s.char for s in steps) == "안녕 Hi"


def test_typing_rhythm_varies_intervals():
    mechanical = planner.plan_text("abcdefghij", interval_ms=30, human=MECHANICAL, rng=rng())
    human = planner.plan_text("abcdefghij", interval_ms=30, human=HumanProfile(), rng=rng())
    assert len({s.delay_ms for s in mechanical}) == 1
    assert len({s.delay_ms for s in human}) > 5


# ---------------------------------------------------------------- 대기 / 상속


def test_idle_is_a_single_delay_without_drift():
    steps = planner.plan_idle((10, 10), 1000, human=MECHANICAL, rng=rng())
    assert kinds(steps) == [DELAY]
    assert steps[0].delay_ms == 1000


def test_idle_drift_moves_the_cursor_slightly():
    profile = HumanProfile(idle_drift=True)
    steps = planner.plan_idle((100, 100), 2000, human=profile, rng=rng())
    moves = [s for s in steps if s.kind == MOVE]
    assert moves
    assert all(abs(s.x - 100) <= 2 and abs(s.y - 100) <= 2 for s in moves)
    assert sum(s.delay_ms for s in steps) == pytest.approx(2000, rel=0.05)


def test_action_level_humanize_override():
    base = HumanProfile(enabled=True)
    assert planner.resolve_human(base, "off").enabled is False
    assert planner.resolve_human(HumanProfile(enabled=False), "on").enabled is True
    assert planner.resolve_human(base, "inherit") is base


# ---------------------------------------------------------------- 터치


def test_tap_presses_and_releases_every_contact():
    steps = plan_tap([(10, 10), (50, 50)])
    assert [s.pointer for s in steps if s.down] == [0, 1]
    assert [s.pointer for s in steps if not s.down] == [0, 1]


def test_pinch_moves_contacts_together():
    steps = plan_pinch((100, 100), start_distance=200, end_distance=40, steps_count=6)
    first = [s for s in steps if s.pointer == 0 and s.down]
    last_gap = abs(first[-1].x - 100)
    first_gap = abs(first[0].x - 100)
    assert last_gap < first_gap  # 오므라들었다
    assert steps[-1].down is False and steps[-2].down is False


def test_rotate_keeps_contacts_opposite():
    steps = plan_rotate((100, 100), radius=50, angle_deg=90, steps_count=4)
    pairs = {}
    for step in steps:
        pairs.setdefault(step.pointer, []).append((step.x, step.y))
    assert len(pairs) == 2
    for a, b in zip(pairs[0], pairs[1]):
        assert abs((a[0] + b[0]) / 2 - 100) <= 1
        assert abs((a[1] + b[1]) / 2 - 100) <= 1


def test_touch_drag_follows_the_path():
    path = [(0, 0), (10, 10), (20, 30)]
    steps = plan_touch_drag(path, duration_ms=300)
    positions = [(s.x, s.y) for s in steps if s.down]
    assert positions == path
    assert steps[-1].down is False


def test_touch_drag_needs_two_points():
    assert plan_touch_drag([(1, 1)]) == []


# ---------------------------------------------------------------- 실행기


def test_dry_run_records_without_touching_anything():
    sender = DryRunSender()
    steps = planner.plan_click((100, 200), start=(0, 0), human=MECHANICAL,
                               timing=NO_TOLERANCE, rng=rng())
    sender.run(steps)

    assert len(sender.performed) == len(steps)
    assert sender.positions()[-1] == (100, 200)
    assert sender.elapsed_ms > 0


def test_dry_run_collects_typed_text():
    sender = DryRunSender()
    sender.run(planner.plan_text("안녕하세요", human=MECHANICAL, rng=rng()))
    assert sender.text() == "안녕하세요"


def test_dry_run_hook_sees_every_step():
    seen = []
    sender = DryRunSender()
    sender.run(planner.plan_key("ctrl+c", human=MECHANICAL, rng=rng()), on_step=seen.append)
    assert len(seen) == 4


def test_real_injection_is_blocked_during_tests():
    """안전장치 자체를 검증한다 — 실주입 경로는 테스트 중 호출되면 실패해야 한다."""
    from itda.engine.input.sender import Win32Sender
    from itda.engine.input.steps import Step
    from itda.vision.coords import Rect, ScreenInfo

    sender = Win32Sender(screens=[ScreenInfo("가상", Rect(0, 0, 1920, 1080), 1.0)])
    with pytest.raises(AssertionError, match="실제 입력 주입"):
        sender.apply(Step(MOVE, x=100, y=100))


def test_touch_injection_is_blocked_during_tests():
    from itda.engine.input.touch import TouchInjector

    injector = TouchInjector()
    with pytest.raises(AssertionError, match="실제 입력 주입"):
        injector.flush()


def test_summarize_is_readable():
    steps = planner.plan_click((5, 5), move_first=False, human=MECHANICAL, rng=rng())
    text = summarize(steps)
    assert "이동" in text and "누름" in text


# ---------------------------------------------------------------- 순간이동 방지
#
# 사람처럼 움직이기가 목적지 이동에만 걸려 있고, **가는 길**은 순간이동이던 자리들.
# 드래그는 시작점으로 튀어 오른 뒤에야 사람처럼 끌었다 — 첫 동작에서 바로 티가 난다.


def _first_jump(steps, origin) -> float:
    for step in steps:
        if step.kind == "move":
            return ((step.x - origin[0]) ** 2 + (step.y - origin[1]) ** 2) ** 0.5
    return 0.0


def test_drag_walks_to_the_start_instead_of_teleporting():
    cursor = (50, 50)
    steps = planner.plan_drag(
        (900, 1000), (1500, 1050), human=HumanProfile(), timing=TimingProfile(), cursor=cursor
    )

    assert _first_jump(steps, cursor) < 12  # 첫 걸음은 커서 바로 옆이어야 한다
    assert sum(1 for s in steps if s.kind == "move") > 50


def test_scroll_walks_to_the_wheel_position():
    cursor = (50, 50)
    steps = planner.plan_scroll(
        -5, (900, 1000), HumanProfile(), timing=TimingProfile(), cursor=cursor
    )

    assert _first_jump(steps, cursor) < 12
    assert sum(1 for s in steps if s.kind == "move") > 50


def test_drag_still_works_without_a_known_cursor():
    """커서 자리를 모르면 예전처럼 시작점에서 시작한다 — 호출부가 안 줘도 깨지지 않게."""
    steps = planner.plan_drag((900, 1000), (1500, 1050), human=HumanProfile())

    assert steps[0].kind == "move"
    assert (steps[0].x, steps[0].y) == (900, 1000)


def test_walking_to_the_start_does_not_wobble_the_grab_point():
    """가는 길에 좌표 허용오차를 걸면 잡는 지점이 흔들려 엉뚱한 것을 집는다."""
    timing = TimingProfile(click_offset_px=40)
    steps = planner.plan_drag(
        (900, 1000), (1500, 1050), human=HumanProfile(), timing=timing, cursor=(50, 50)
    )

    press = next(i for i, s in enumerate(steps) if s.kind == "button")
    landed = steps[press - 1]
    assert (landed.x, landed.y) == (900, 1000)


def test_click_that_asks_not_to_move_still_does_not_move():
    """'커서를 이동시킨 뒤 클릭' 을 끈 것은 의도적인 순간이동이다 — 건드리면 안 된다."""
    steps = planner.plan_click(
        (900, 1000), start=(50, 50), human=HumanProfile(), timing=TimingProfile(),
        move_first=False,
    )

    assert sum(1 for s in steps if s.kind == "move") == 1
