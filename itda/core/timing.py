"""타이밍 프로파일과 허용오차 / 변동계수.

요구사항: "시간과 좌표에 허용오차, 변동계수 같은 개념이 적용되어야 함 (개별 제어 또는
원클릭 전체 적용)".

구현 방식은 **상속**이다. 노드와 액션의 타이밍은 기본적으로 ``inherit=True`` 이고 프로젝트
프로파일 값을 그대로 쓴다. 프로파일 대화상자에서 값 하나를 바꾸면 상속 중인 모든 항목이
동시에 바뀐다(= 원클릭 전체 적용). 개별 제어가 필요하면 그 항목만 ``inherit=False`` 로
바꿔 자기 값을 쓴다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class TimingProfile:
    """프로젝트 전역 타이밍/허용오차 기본값."""

    #: 모든 딜레이에 곱하는 배율. 느린 PC 대응용으로 한 번에 늘릴 때 쓴다.
    delay_scale: float = 1.0
    #: 딜레이 변동계수. 0.15 면 ±15% 안에서 매번 랜덤하게 흔든다.
    jitter_pct: float = 0.15
    #: 클릭 좌표 흔들기 반경(px). 매번 같은 픽셀을 찍지 않게 한다.
    click_offset_px: int = 2
    #: 마우스 이동에 쓰는 시간(ms). 0 이면 순간이동.
    move_duration_ms: int = 150
    #: 이미지 매칭 기본 임계값.
    match_threshold: float = 0.88
    #: 상속 중인 동작의 기본 선/후 딜레이(ms).
    default_pre_ms: int = 0
    default_post_ms: int = 120
    #: 이미지 대기 기본 제한시간(ms).
    default_timeout_ms: int = 3000


@dataclass
class Timing:
    """노드/액션 하나의 타이밍 설정.

    ``inherit`` 가 참이면 나머지 값은 무시하고 프로파일을 따른다.
    """

    inherit: bool = True
    pre_ms: int = 0
    post_ms: int = 0
    #: None 이면 프로파일의 jitter_pct 를 쓴다.
    jitter_pct: float | None = None


@dataclass(frozen=True)
class ResolvedTiming:
    """상속을 적용해 실제로 쓸 값."""

    pre_ms: int
    post_ms: int
    jitter_pct: float


def resolve(timing: Timing | None, profile: TimingProfile) -> ResolvedTiming:
    """상속 규칙을 적용해 실제 딜레이를 계산한다 (지터는 아직 적용 전)."""
    scale = max(0.0, profile.delay_scale)
    if timing is None or timing.inherit:
        return ResolvedTiming(
            pre_ms=int(profile.default_pre_ms * scale),
            post_ms=int(profile.default_post_ms * scale),
            jitter_pct=profile.jitter_pct,
        )
    jitter = profile.jitter_pct if timing.jitter_pct is None else timing.jitter_pct
    return ResolvedTiming(
        pre_ms=int(max(0, timing.pre_ms) * scale),
        post_ms=int(max(0, timing.post_ms) * scale),
        jitter_pct=jitter,
    )


def jitter_ms(ms: int, jitter_pct: float, rng: random.Random | None = None) -> int:
    """딜레이에 변동계수를 적용한다. 결과는 0 이상."""
    if ms <= 0 or jitter_pct <= 0:
        return max(0, ms)
    r = rng or random
    delta = ms * jitter_pct
    return max(0, int(round(r.uniform(ms - delta, ms + delta))))


def jitter_point(
    x: int, y: int, radius_px: int, rng: random.Random | None = None
) -> tuple[int, int]:
    """클릭 좌표에 허용오차를 적용한다. 반경 안에서 균등하게 흔든다."""
    if radius_px <= 0:
        return x, y
    r = rng or random
    return x + r.randint(-radius_px, radius_px), y + r.randint(-radius_px, radius_px)


def describe(timing: Timing | None, profile: TimingProfile) -> str:
    """속성 패널/노드 배지에 보여줄 한 줄 요약."""
    res = resolve(timing, profile)
    tag = "상속" if timing is None or timing.inherit else "개별"
    return f"{tag} · 전 {res.pre_ms}ms / 후 {res.post_ms}ms / ±{int(res.jitter_pct * 100)}%"
