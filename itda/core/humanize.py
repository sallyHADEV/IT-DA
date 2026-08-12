"""사람처럼 움직이는 입력.

기계가 만든 입력은 티가 난다 — 마우스가 자로 잰 직선으로 가고, 속도가 일정하고, 클릭 간격이
정확히 같다. 안티매크로 탐지는 대부분 이 규칙성을 본다.

여기서는 궤적과 시간을 사람처럼 흐트러뜨린다. 각 항목은 켜고 끌 수 있고, 개별 액션에서
프로파일을 따르거나 무시할 수 있다.

이 모듈은 Qt 를 모른다. 2차 실행 엔진이 실제 마우스를 움직일 때 쓰고, 편집기의 미리보기가
같은 함수를 호출해 **화면에 보이는 궤적이 실제로 실행될 궤적** 이 되게 한다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class HumanProfile:
    """사람 동작 모사 설정. 프로젝트마다 하나."""

    #: 전체 스위치. 끄면 모든 항목이 무시되고 기계처럼 곧게 움직인다.
    enabled: bool = True
    #: 베지에 곡선 궤적 — 직선 대신 완만하게 휘어 간다.
    curve: bool = True
    #: 휘는 정도(0=직선, 1=매우 크게)
    curvature: float = 0.22
    #: 가속·감속 무작위화 — 출발과 도착에서 느려지고 중간에 빨라진다.
    speed_variation: bool = True
    #: 목표를 살짝 지나쳤다가 되돌아온다.
    overshoot: bool = False
    #: 이동 도중 짧게 멈칫한다.
    micro_pause: bool = False
    #: 타이핑 간격을 글자마다 다르게 한다.
    typing_rhythm: bool = True
    #: 클릭을 누르고 있는 시간을 매번 다르게 한다.
    click_hold_variation: bool = True
    #: 대기 중 커서가 아주 조금씩 흔들린다.
    idle_drift: bool = False
    #: 궤적을 몇 점으로 쪼갤지 (100px 당)
    steps_per_100px: int = 14


@dataclass(frozen=True)
class PathPoint:
    """궤적의 한 점. ``delay_ms`` 는 이전 점에서 이 점까지 걸리는 시간."""

    x: float
    y: float
    delay_ms: float


def mouse_path(
    start: tuple[float, float],
    end: tuple[float, float],
    profile: HumanProfile | None = None,
    duration_ms: int = 300,
    rng: random.Random | None = None,
) -> list[PathPoint]:
    """``start`` 에서 ``end`` 까지의 마우스 궤적을 만든다.

    설정을 전부 끄면 균일한 속도의 직선이 된다(= 기존 동작).
    """
    profile = profile or HumanProfile()
    r = rng or random
    x0, y0 = float(start[0]), float(start[1])
    x1, y1 = float(end[0]), float(end[1])
    distance = math.hypot(x1 - x0, y1 - y0)

    if distance < 1 or duration_ms <= 0:
        return [PathPoint(x1, y1, float(max(0, duration_ms)))]

    steps = max(2, min(240, int(distance / 100 * max(1, profile.steps_per_100px))))
    humanized = profile.enabled

    # 목표점 — 오버슈트를 켜면 살짝 지나친 지점을 먼저 찍는다
    aim_x, aim_y = x1, y1
    overshoot_back: tuple[float, float] | None = None
    if humanized and profile.overshoot and distance > 40:
        amount = min(18.0, distance * 0.06) * r.uniform(0.6, 1.4)
        ux, uy = (x1 - x0) / distance, (y1 - y0) / distance
        aim_x, aim_y = x1 + ux * amount, y1 + uy * amount
        overshoot_back = (x1, y1)

    if humanized and profile.curve:
        c1, c2 = _control_points((x0, y0), (aim_x, aim_y), profile.curvature, r)
        sample = lambda t: _bezier(t, (x0, y0), c1, c2, (aim_x, aim_y))  # noqa: E731
    else:
        sample = lambda t: (x0 + (aim_x - x0) * t, y0 + (aim_y - y0) * t)  # noqa: E731

    # 속도 곡선의 세기는 궤적마다 한 번만 뽑는다. 스텝마다 새로 뽑으면 곡선이 단조롭지
    # 않게 되어 시간이 뒤로 갔다 앞으로 갔다 하고, 총 이동 시간이 엉킨다.
    power = 1.6 + r.uniform(-0.25, 0.45) if humanized and profile.speed_variation else None

    points: list[PathPoint] = []
    previous_t = 0.0
    for i in range(1, steps + 1):
        linear = i / steps
        eased = _ease(linear, power) if power is not None else linear
        x, y = sample(eased)
        delay = (eased - previous_t) * duration_ms
        previous_t = eased
        points.append(PathPoint(x, y, max(0.0, delay)))

    if humanized and profile.micro_pause and len(points) > 6:
        for _ in range(r.randint(1, 2)):
            index = r.randrange(2, len(points) - 2)
            paused = points[index]
            points[index] = PathPoint(paused.x, paused.y, paused.delay_ms + r.uniform(40, 110))

    if overshoot_back is not None:
        back_x, back_y = overshoot_back
        points.append(PathPoint(back_x, back_y, duration_ms * 0.18))

    return points


def typing_delays(
    length: int,
    base_ms: int,
    profile: HumanProfile | None = None,
    rng: random.Random | None = None,
) -> list[float]:
    """글자 수만큼의 입력 간격. 리듬을 끄면 전부 같은 값이다."""
    profile = profile or HumanProfile()
    r = rng or random
    if not (profile.enabled and profile.typing_rhythm):
        return [float(base_ms)] * max(0, length)

    delays = []
    for i in range(max(0, length)):
        delay = base_ms * r.uniform(0.55, 1.75)
        if i and r.random() < 0.07:  # 가끔 생각하느라 멈칫
            delay += base_ms * r.uniform(2.0, 5.0)
        delays.append(delay)
    return delays


def click_hold_ms(
    base_ms: int, profile: HumanProfile | None = None, rng: random.Random | None = None
) -> float:
    """클릭을 누르고 있는 시간."""
    profile = profile or HumanProfile()
    r = rng or random
    if not (profile.enabled and profile.click_hold_variation):
        return float(base_ms)
    return max(8.0, base_ms * r.uniform(0.6, 1.9))


def idle_drift_offset(
    radius_px: int = 2, profile: HumanProfile | None = None, rng: random.Random | None = None
) -> tuple[int, int]:
    """대기 중 커서를 아주 조금 흔든다. 꺼져 있으면 (0, 0)."""
    profile = profile or HumanProfile()
    r = rng or random
    if not (profile.enabled and profile.idle_drift):
        return (0, 0)
    return (r.randint(-radius_px, radius_px), r.randint(-radius_px, radius_px))


def describe(profile: HumanProfile) -> str:
    """현재 설정을 한 줄로."""
    if not profile.enabled:
        return "꺼짐 — 직선·일정 속도로 움직입니다"
    on = [
        name
        for flag, name in (
            (profile.curve, "곡선 궤적"),
            (profile.speed_variation, "속도 변화"),
            (profile.overshoot, "오버슈트"),
            (profile.micro_pause, "미세 정지"),
            (profile.typing_rhythm, "타이핑 리듬"),
            (profile.click_hold_variation, "클릭 시간 변화"),
            (profile.idle_drift, "커서 드리프트"),
        )
        if flag
    ]
    return " · ".join(on) if on else "모든 항목이 꺼져 있습니다"


# ---------------------------------------------------------------- 내부


def _control_points(
    start: tuple[float, float],
    end: tuple[float, float],
    curvature: float,
    r: random.Random,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """진행 방향에 수직으로 밀어낸 제어점 두 개."""
    x0, y0 = start
    x1, y1 = end
    dx, dy = x1 - x0, y1 - y0
    distance = math.hypot(dx, dy) or 1.0
    # 수직 단위벡터
    nx, ny = -dy / distance, dx / distance
    reach = distance * max(0.0, curvature)
    side = 1 if r.random() < 0.5 else -1

    first = (
        x0 + dx * 0.3 + nx * reach * side * r.uniform(0.6, 1.2),
        y0 + dy * 0.3 + ny * reach * side * r.uniform(0.6, 1.2),
    )
    second = (
        x0 + dx * 0.7 + nx * reach * side * r.uniform(0.3, 0.9),
        y0 + dy * 0.7 + ny * reach * side * r.uniform(0.3, 0.9),
    )
    return first, second


def _bezier(
    t: float,
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> tuple[float, float]:
    u = 1 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def _ease(t: float, power: float) -> float:
    """가속·감속(ease-in-out). ``power`` 는 궤적마다 다르게 주어 매번 다른 속도로 움직인다."""
    if t < 0.5:
        eased = 0.5 * ((2 * t) ** power)
    else:
        eased = 1 - 0.5 * ((2 * (1 - t)) ** power)
    return min(1.0, max(0.0, eased))
