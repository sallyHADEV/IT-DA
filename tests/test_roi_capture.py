"""검색 범위(ROI)를 줬을 때 그만큼만 찍는지 — 그리고 좌표가 어긋나지 않는지.

예전에는 ROI 가 있어도 가상 데스크톱 전체를 찍어 놓고 매처가 잘라 썼다. 모니터 두 대
(3440x2640 = 9.1M 픽셀)에서 전체 캡처가 131ms, 300x200 만 찍으면 8ms 였다(실측).
폴링 루프가 이걸 반복하므로 차이가 그대로 매크로 속도가 된다.

**좌표가 이 최적화의 위험 지점이다.** 조각 기준으로 찾은 위치를 화면 좌표로 되돌리지
않으면 클릭이 엉뚱한 데로 간다.
"""

from __future__ import annotations

import numpy as np
import pytest

from itda.core.model import TargetObject
from itda.engine.context import ExecutionContext
from itda.vision import capture

MARK_AT = (700, 500)
MARK_SIZE = (60, 40)  # w, h


@pytest.fixture
def fake_screen(monkeypatch, tmp_path, project):
    """질감 있는 가짜 화면과, 그 안에 심어 둔 표식을 객체로 등록한다.

    단색 표식은 쓸 수 없다 — 정규화 상관계수는 분산이 0 이면 정의되지 않아 아무 데나
    맞았다고 나온다(실제로 그렇게 헛짚었다).
    """
    import cv2

    rng = np.random.default_rng(7)
    screen = rng.integers(0, 90, (1200, 2000, 3), dtype=np.uint8)
    mark = rng.integers(120, 255, (MARK_SIZE[1], MARK_SIZE[0], 3), dtype=np.uint8)
    x, y = MARK_AT
    screen[y : y + MARK_SIZE[1], x : x + MARK_SIZE[0]] = mark

    grabbed: list[tuple | None] = []

    def fake_grab(rect=None):
        grabbed.append(rect)
        if rect is None:
            return screen.copy()
        gx, gy, gw, gh = rect
        return screen[gy : gy + gh, gx : gx + gw].copy()

    monkeypatch.setattr(capture, "grab_array", fake_grab)

    project.save(tmp_path / "proj")
    path = tmp_path / "mark.png"
    cv2.imwrite(str(path), mark)
    project.add_object(TargetObject(name="표식", images=[project.import_image(path, "표식")]))
    return project, grabbed


@pytest.mark.parametrize(
    "roi",
    [None, (650, 450, 400, 300), (0, 0, 1200, 800)],
    ids=["범위 없음", "범위 지정", "범위가 원점에서 시작"],
)
def test_match_comes_back_in_screen_coordinates(fake_screen, roi):
    project, _ = fake_screen
    ctx = ExecutionContext(project=project)

    match = ctx.find_object(["표식"], roi=roi, use_hint=False)

    assert match is not None
    assert (match.x, match.y) == MARK_AT


def test_only_the_region_is_captured(fake_screen):
    project, grabbed = fake_screen
    ctx = ExecutionContext(project=project)

    ctx.find_object(["표식"], roi=(650, 450, 400, 300), use_hint=False)

    assert grabbed == [(650, 450, 400, 300)], "전체 화면을 찍으면 안 된다"


def test_no_region_still_captures_everything(fake_screen):
    project, grabbed = fake_screen
    ctx = ExecutionContext(project=project)

    ctx.find_object(["표식"], use_hint=False)

    assert grabbed == [None]


def test_region_is_captured_once_for_several_objects(fake_screen):
    """객체가 여럿이어도 캡처는 한 번이어야 한다 — 이름마다 찍으면 오히려 느려진다."""
    project, grabbed = fake_screen
    project.add_object(TargetObject(name="다른것", images=[]))
    ctx = ExecutionContext(project=project)

    ctx.find_object(["다른것", "표식"], mode="all", roi=(650, 450, 400, 300), use_hint=False)

    assert len(grabbed) == 1


def test_remembered_position_is_reusable_after_a_region_search(fake_screen):
    """조각 기준 좌표를 그대로 기억해 버리면 다음 클릭이 엉뚱한 데로 간다."""
    project, _ = fake_screen
    ctx = ExecutionContext(project=project)

    ctx.find_object(["표식"], roi=(650, 450, 400, 300), use_hint=False)

    centre = ctx.cache.center("표식")
    assert centre == (MARK_AT[0] + MARK_SIZE[0] // 2, MARK_AT[1] + MARK_SIZE[1] // 2)


def test_hint_is_translated_into_the_cropped_frame(fake_screen):
    """기억해 둔 위치는 **화면 좌표**다. 조각 기준으로 바꿔 주지 않으면 힌트 단계가 늘
    빗나가, 최근 위치 재사용이라는 최적화가 통째로 죽는다(결과는 맞게 나와서 티가 안 난다).
    """
    from itda.vision.matcher import SearchStats

    project, _ = fake_screen
    ctx = ExecutionContext(project=project)
    roi = (650, 450, 400, 300)

    ctx.find_object(["표식"], roi=roi, use_hint=False)  # 위치를 기억시킨다

    stats = SearchStats()
    again = ctx.find_object(["표식"], roi=roi, use_hint=True, stats=stats)

    assert again is not None
    assert (again.x, again.y) == MARK_AT
    assert stats.stages[0] == "최근 위치 주변", stats.stages
    assert "전체 탐색" not in stats.stages
