"""입력 계획 — 순수 함수.

좌표와 시간을 :mod:`itda.core.humanize` 로 만들고, 허용오차는
:mod:`itda.core.timing` 에서 가져온다. 실제 주입은 하지 않는다.

여기서 만들어진 계획은 그대로 데모 재생기에서 그려 볼 수도 있고, 테스트에서 검사할 수도 있다.
"""

from __future__ import annotations

import random

from itda.core.humanize import (
    HumanProfile,
    click_hold_ms,
    idle_drift_offset,
    mouse_path,
    typing_delays,
)
from itda.core.timing import TimingProfile, jitter_point
from itda.engine.input import keys
from itda.engine.input.steps import BUTTON, CHAR, DELAY, KEY, MOVE, WHEEL, Step

DEFAULT_CLICK_HOLD_MS = 55


def resolve_human(profile: HumanProfile, action_setting: str = "inherit") -> HumanProfile:
    """액션의 ``humanize`` 설정(상속/켬/끔)을 프로파일에 적용한다."""
    from dataclasses import replace

    if action_setting == "off":
        return replace(profile, enabled=False)
    if action_setting == "on":
        return replace(profile, enabled=True)
    return profile


def plan_move(
    start: tuple[int, int],
    end: tuple[int, int],
    human: HumanProfile | None = None,
    timing: TimingProfile | None = None,
    duration_ms: int | None = None,
    rng: random.Random | None = None,
    apply_tolerance: bool = True,
) -> list[Step]:
    """``start`` → ``end`` 커서 이동 계획.

    좌표 허용오차(``click_offset_px``)는 목표점에 한 번만 적용한다. 궤적 중간에 흔들면
    떨리는 것처럼 보이지 실제 사람 손과는 다르다.
    """
    human = human or HumanProfile()
    timing = timing or TimingProfile()
    r = rng or random
    target = end
    if apply_tolerance and timing.click_offset_px > 0:
        target = jitter_point(end[0], end[1], timing.click_offset_px, r)

    duration = timing.move_duration_ms if duration_ms is None else duration_ms
    path = mouse_path(start, target, human, duration_ms=max(0, duration), rng=r)
    return [Step(MOVE, delay_ms=p.delay_ms, x=int(round(p.x)), y=int(round(p.y))) for p in path]


def plan_click(
    position: tuple[int, int],
    start: tuple[int, int] | None = None,
    button: str = "left",
    click_type: str = "single",
    human: HumanProfile | None = None,
    timing: TimingProfile | None = None,
    rng: random.Random | None = None,
    move_first: bool = True,
) -> list[Step]:
    """클릭 계획. 필요하면 커서 이동부터 포함한다."""
    human = human or HumanProfile()
    timing = timing or TimingProfile()
    r = rng or random

    steps: list[Step] = []
    if move_first and start is not None:
        steps += plan_move(start, position, human, timing, rng=r)
        target = (steps[-1].x, steps[-1].y) if steps else position
    else:
        target = position
        if timing.click_offset_px > 0:
            target = jitter_point(position[0], position[1], timing.click_offset_px, r)
        steps.append(Step(MOVE, x=target[0], y=target[1]))

    hold = click_hold_ms(DEFAULT_CLICK_HOLD_MS, human, r)

    def press() -> None:
        steps.append(Step(BUTTON, button=button, down=True))
        steps.append(Step(BUTTON, button=button, down=False, delay_ms=hold))

    match click_type:
        case "down":
            steps.append(Step(BUTTON, button=button, down=True))
        case "up":
            steps.append(Step(BUTTON, button=button, down=False))
        case "double":
            press()
            # 더블클릭 간격도 사람마다 다르다. 시스템 한계(500ms)보다 넉넉히 짧게.
            gap = r.uniform(60, 140) if human.enabled else 90
            steps.append(Step(DELAY, delay_ms=gap))
            press()
        case _:
            press()

    return steps


def plan_drag(
    start: tuple[int, int],
    end: tuple[int, int],
    button: str = "left",
    duration_ms: int = 300,
    human: HumanProfile | None = None,
    timing: TimingProfile | None = None,
    rng: random.Random | None = None,
    cursor: tuple[int, int] | None = None,
) -> list[Step]:
    """누르고 → 끌고 → 떼기.

    ``cursor`` 는 지금 커서 자리다. 주면 **거기서 시작점까지도 사람처럼 움직인다** —
    예전에는 시작점으로 순간이동한 뒤 끌기만 사람처럼 해서, 드래그 첫 동작이 늘 튀었다.
    """
    human = human or HumanProfile()
    timing = timing or TimingProfile()
    r = rng or random

    steps: list[Step] = []
    if cursor is not None and tuple(cursor) != tuple(start):
        # 시작점까지 가는 길에는 좌표 허용오차를 걸지 않는다 — 흔들면 엉뚱한 데를 잡는다.
        steps += plan_move(cursor, start, human, timing, rng=r, apply_tolerance=False)
    else:
        steps.append(Step(MOVE, x=start[0], y=start[1]))
    steps.append(Step(BUTTON, button=button, down=True, delay_ms=click_hold_ms(40, human, r)))
    steps += plan_move(start, end, human, timing, duration_ms=duration_ms, rng=r)
    steps.append(Step(BUTTON, button=button, down=False, delay_ms=click_hold_ms(60, human, r)))
    return steps


def plan_scroll(
    amount: int,
    position: tuple[int, int] | None = None,
    human: HumanProfile | None = None,
    rng: random.Random | None = None,
    timing: TimingProfile | None = None,
    cursor: tuple[int, int] | None = None,
) -> list[Step]:
    """휠 스크롤. 사람처럼 여러 번 나눠 돌린다.

    돌릴 자리로 **가는 길**도 사람처럼 움직인다(``cursor`` 를 주면). 휠만 흉내 내고 이동은
    순간이동이면 티가 난다.
    """
    human = human or HumanProfile()
    timing = timing or TimingProfile()
    r = rng or random
    steps: list[Step] = []
    if position is not None:
        if cursor is not None and tuple(cursor) != tuple(position):
            steps += plan_move(cursor, position, human, timing, rng=r, apply_tolerance=False)
        else:
            steps.append(Step(MOVE, x=position[0], y=position[1]))

    if not human.enabled or abs(amount) <= 1:
        steps.append(Step(WHEEL, amount=amount))
        return steps

    remaining = amount
    direction = 1 if amount > 0 else -1
    while remaining != 0:
        chunk = direction * min(abs(remaining), r.randint(1, 3))
        steps.append(Step(WHEEL, amount=chunk, delay_ms=r.uniform(25, 90)))
        remaining -= chunk
    return steps


def plan_key(
    combo: str,
    action: str = "tap",
    repeat: int = 1,
    human: HumanProfile | None = None,
    rng: random.Random | None = None,
) -> list[Step]:
    """키 조합 계획. ``ctrl+s`` 는 ctrl 누름 → s 누름 → s 뗌 → ctrl 뗌."""
    human = human or HumanProfile()
    r = rng or random
    modifiers, final = keys.parse_combo(combo)

    steps: list[Step] = []
    for index in range(max(1, repeat)):
        if index:
            steps.append(Step(DELAY, delay_ms=r.uniform(30, 90) if human.enabled else 40))
        if action in ("tap", "down"):
            for vk in modifiers:
                steps.append(Step(KEY, vk=vk, down=True, delay_ms=_key_gap(human, r)))
            steps.append(Step(KEY, vk=final, down=True, delay_ms=_key_gap(human, r)))
        if action in ("tap", "up"):
            if action == "up":
                for vk in modifiers:
                    steps.append(Step(KEY, vk=vk, down=False))
            steps.append(Step(KEY, vk=final, down=False,
                              delay_ms=click_hold_ms(45, human, r)))
            if action == "tap":
                for vk in reversed(modifiers):
                    steps.append(Step(KEY, vk=vk, down=False, delay_ms=_key_gap(human, r)))
    return steps


def plan_text(
    text: str,
    interval_ms: int = 30,
    human: HumanProfile | None = None,
    rng: random.Random | None = None,
) -> list[Step]:
    """문자열 입력. 유니코드로 직접 넣어 한글도 입력기 상태와 무관하게 들어간다."""
    human = human or HumanProfile()
    r = rng or random
    delays = typing_delays(len(text or ""), interval_ms, human, r)
    return [
        Step(CHAR, char=ch, delay_ms=delay)
        for ch, delay in zip(text or "", delays)
    ]


def plan_idle(
    position: tuple[int, int],
    duration_ms: int,
    human: HumanProfile | None = None,
    rng: random.Random | None = None,
) -> list[Step]:
    """대기. 드리프트가 켜져 있으면 커서를 아주 조금 움직인다."""
    human = human or HumanProfile()
    r = rng or random
    if not (human.enabled and human.idle_drift) or duration_ms < 400:
        return [Step(DELAY, delay_ms=float(duration_ms))]

    steps: list[Step] = []
    remaining = float(duration_ms)
    while remaining > 0:
        slice_ms = min(remaining, r.uniform(250, 600))
        dx, dy = idle_drift_offset(2, human, r)
        steps.append(Step(MOVE, x=position[0] + dx, y=position[1] + dy, delay_ms=slice_ms))
        remaining -= slice_ms
    return steps


def _key_gap(human: HumanProfile, r: random.Random) -> float:
    return r.uniform(12, 45) if human.enabled else 8.0
