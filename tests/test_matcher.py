"""템플릿 매칭 테스트 — 합성 화면으로 검증한다."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from itda.vision.matcher import (
    Match,
    MatchCache,
    SearchOptions,
    SearchStats,
    find,
    find_all,
)

rng = np.random.default_rng(4242)


def make_scene(width: int = 1280, height: int = 720) -> np.ndarray:
    """노이즈가 있는 배경. 단색이면 매칭이 비현실적으로 쉬워진다."""
    return rng.integers(60, 90, size=(height, width, 3), dtype=np.uint8)


def make_button(text: str = "OK", w: int = 90, h: int = 40) -> np.ndarray:
    button = np.full((h, w, 3), 220, dtype=np.uint8)
    cv2.rectangle(button, (1, 1), (w - 2, h - 2), (40, 40, 40), 2)
    cv2.putText(button, text, (10, h - 13), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1)
    return button


def place(scene: np.ndarray, patch: np.ndarray, x: int, y: int) -> np.ndarray:
    scene = scene.copy()
    h, w = patch.shape[:2]
    scene[y:y + h, x:x + w] = patch
    return scene


# ---------------------------------------------------------------- 기본


def test_finds_a_placed_template():
    button = make_button()
    scene = place(make_scene(), button, 400, 300)

    matches = find(scene, [button], SearchOptions(threshold=0.9))

    assert len(matches) == 1
    assert (matches[0].x, matches[0].y) == (400, 300)
    assert matches[0].score > 0.95
    assert matches[0].center == (400 + 45, 300 + 20)


def test_returns_nothing_when_absent():
    scene = make_scene()
    assert find(scene, [make_button()], SearchOptions(threshold=0.9)) == []


def make_icon(size: int = 40) -> np.ndarray:
    """버튼과 확실히 다른 모양 — 원형 아이콘."""
    icon = np.full((size, size, 3), 200, dtype=np.uint8)
    cv2.circle(icon, (size // 2, size // 2), size // 3, (30, 120, 200), -1)
    return icon


def test_threshold_rejects_a_different_image():
    scene = place(make_scene(), make_icon(), 100, 100)
    assert find(scene, [make_button()], SearchOptions(threshold=0.9)) == []


def test_brightness_change_still_matches():
    """TM_CCOEFF_NORMED 는 밝기·대비 변화에 둔감하다.

    테마가 조금 어두워져도 같은 버튼으로 인식된다 — 매크로에는 이 성질이 유리하다.
    반대로 "색만 다른 버튼"은 구분하지 못하므로, 그럴 때는 색 판정(픽셀 색 확인)을 함께 쓴다.
    """
    button = make_button()
    faded = (button * 0.45).astype(np.uint8)
    scene = place(make_scene(), faded, 100, 100)

    matches = find(scene, [button], SearchOptions(threshold=0.95))
    assert matches and (matches[0].x, matches[0].y) == (100, 100)


def test_template_larger_than_scene_is_safe():
    small = make_scene(80, 60)
    assert find(small, [make_button(w=200, h=200)], SearchOptions()) == []


def test_empty_inputs_are_safe():
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    assert find(empty, [make_button()]) == []
    assert find(make_scene(), []) == []
    assert find(make_scene(), [empty]) == []


# ---------------------------------------------------------------- 다중 이미지


def test_any_mode_stops_at_the_first_hit():
    button = make_button("OK")
    icon = make_icon()
    scene = place(make_scene(), icon, 500, 200)

    matches = find(scene, [button, icon], SearchOptions(mode="any", threshold=0.9))

    assert len(matches) == 1
    assert (matches[0].x, matches[0].y) == (500, 200)


def test_best_mode_picks_the_highest_score():
    ok = make_button("OK")
    blurred = cv2.GaussianBlur(ok, (5, 5), 0)
    scene = place(make_scene(), ok, 300, 100)
    scene = place(scene, blurred, 700, 400)

    matches = find(scene, [blurred, ok], SearchOptions(mode="best", threshold=0.7))

    assert len(matches) == 1
    assert matches[0].score > 0.95


def test_all_mode_requires_every_template():
    button = make_button("OK")
    icon = make_icon()
    scene = place(make_scene(), button, 200, 200)

    assert find(scene, [button, icon], SearchOptions(mode="all", threshold=0.9)) == []

    scene = place(scene, icon, 600, 500)
    matches = find(scene, [button, icon], SearchOptions(mode="all", threshold=0.9))
    assert len(matches) == 2
    assert {(m.x, m.y) for m in matches} == {(200, 200), (600, 500)}


def test_similar_templates_are_not_distinguished():
    """글자만 다른 같은 크기 버튼은 구분되지 않는다.

    템플릿 매칭의 한계다. 이런 경우는 이미지 대신 OCR 이나 더 좁은 영역을 써야 한다.
    """
    ok = make_button("OK")
    no = make_button("NO")
    scene = place(make_scene(), ok, 200, 200)

    assert find(scene, [no], SearchOptions(threshold=0.85))


# ---------------------------------------------------------------- ROI / 힌트


def test_roi_limits_the_search_area():
    button = make_button()
    scene = place(make_scene(), button, 900, 500)

    assert find(scene, [button], SearchOptions(roi=(0, 0, 400, 400), threshold=0.9)) == []

    matches = find(scene, [button], SearchOptions(roi=(850, 450, 300, 200), threshold=0.9))
    assert (matches[0].x, matches[0].y) == (900, 500)  # 좌표는 원본 기준으로 복원된다


def test_roi_outside_the_image_is_safe():
    scene = make_scene()
    assert find(scene, [make_button()], SearchOptions(roi=(5000, 5000, 100, 100))) == []


def test_hint_finds_it_near_the_last_position():
    button = make_button()
    scene = place(make_scene(), button, 620, 330)
    stats = SearchStats()

    matches = find(scene, [button], SearchOptions(hint=(618, 328), threshold=0.9), stats)

    assert (matches[0].x, matches[0].y) == (620, 330)
    assert stats.stages[0] == "최근 위치 주변"


def test_hint_scans_far_fewer_pixels():
    button = make_button()
    scene = place(make_scene(1920, 1080), button, 1500, 800)

    hinted = SearchStats()
    find(scene, [button], SearchOptions(hint=(1498, 798), threshold=0.9), hinted)

    full = SearchStats()
    find(scene, [button], SearchOptions(threshold=0.9), full)

    assert hinted.pixels_scanned < full.pixels_scanned / 10


def test_wrong_hint_falls_back_to_full_search():
    button = make_button()
    scene = place(make_scene(), button, 900, 500)
    stats = SearchStats()

    matches = find(scene, [button], SearchOptions(hint=(50, 50), threshold=0.9), stats)

    assert (matches[0].x, matches[0].y) == (900, 500)
    assert stats.stages[0] == "최근 위치 주변"
    assert len(stats.stages) > 1  # 전체 탐색으로 넘어갔다


# ---------------------------------------------------------------- 피라미드


def test_pyramid_finds_the_same_position_as_direct():
    button = make_button(w=120, h=60)
    scene = place(make_scene(1920, 1080), button, 1200, 700)

    with_pyramid = find(scene, [button], SearchOptions(threshold=0.9, use_pyramid=True))
    without = find(scene, [button], SearchOptions(threshold=0.9, use_pyramid=False))

    assert (with_pyramid[0].x, with_pyramid[0].y) == (1200, 700)
    assert (with_pyramid[0].x, with_pyramid[0].y) == (without[0].x, without[0].y)


def test_pyramid_scans_fewer_pixels_than_direct():
    button = make_button(w=120, h=60)
    scene = place(make_scene(1920, 1080), button, 1200, 700)

    pyramid = SearchStats()
    find(scene, [button], SearchOptions(threshold=0.9, use_pyramid=True), pyramid)
    direct = SearchStats()
    find(scene, [button], SearchOptions(threshold=0.9, use_pyramid=False), direct)

    assert pyramid.pixels_scanned < direct.pixels_scanned * 0.5
    assert "축소 탐색" in pyramid.stages and "정밀 검증" in pyramid.stages


def test_pyramid_is_skipped_for_small_scenes():
    button = make_button()
    scene = place(make_scene(400, 300), button, 100, 100)
    stats = SearchStats()

    find(scene, [button], SearchOptions(threshold=0.9), stats)

    assert "축소 탐색" not in stats.stages  # 작은 화면은 그냥 원본으로


def test_pyramid_is_skipped_for_tiny_templates():
    tiny = make_button(w=14, h=14)
    scene = place(make_scene(1600, 900), tiny, 800, 400)
    stats = SearchStats()

    find(scene, [tiny], SearchOptions(threshold=0.9), stats)

    assert "축소 탐색" not in stats.stages


# ---------------------------------------------------------------- 배율 / 다중


def test_scales_handle_a_resized_target():
    button = make_button(w=100, h=50)
    smaller = cv2.resize(button, (75, 38), interpolation=cv2.INTER_AREA)
    scene = place(make_scene(), smaller, 300, 300)

    assert find(scene, [button], SearchOptions(threshold=0.9, scales=(1.0,))) == []

    matches = find(scene, [button], SearchOptions(threshold=0.85, scales=(1.0, 0.75)))
    assert matches and abs(matches[0].x - 300) <= 3


def test_find_all_locates_every_instance():
    item = make_button("A", w=60, h=30)
    scene = make_scene()
    for i in range(4):
        scene = place(scene, item, 100 + i * 200, 400)

    matches = find_all(scene, item, SearchOptions(threshold=0.9))

    assert len(matches) == 4
    xs = sorted(m.x for m in matches)
    assert xs == [100, 300, 500, 700]


def test_find_all_respects_the_limit():
    item = make_button("A", w=60, h=30)
    scene = make_scene()
    for i in range(4):
        scene = place(scene, item, 100 + i * 200, 400)

    assert len(find_all(scene, item, SearchOptions(threshold=0.9, limit=2))) == 2


# ---------------------------------------------------------------- 통계 / 캐시


def test_stats_are_reported():
    button = make_button()
    scene = place(make_scene(), button, 100, 100)
    stats = SearchStats()

    find(scene, [button], SearchOptions(threshold=0.9), stats)

    assert stats.pixels_scanned > 0
    assert stats.elapsed_ms >= 0
    assert "px" in stats.describe()


def test_cache_remembers_and_forgets():
    cache = MatchCache()
    cache.remember("로그인_버튼", Match(100, 200, 40, 20, 0.99))

    assert cache.has("로그인_버튼")
    assert cache.hint("로그인_버튼") == (100, 200)
    assert cache.center("로그인_버튼") == (120, 210)

    cache.forget("로그인_버튼")
    assert not cache.has("로그인_버튼")
    assert cache.hint("없는것") is None


def test_cache_is_cleared_when_the_state_changes():
    cache = MatchCache()
    cache.on_state_changed("메인화면")
    cache.remember("버튼", Match(10, 10, 5, 5, 0.9))

    cache.on_state_changed("설정창")

    assert not cache.has("버튼")


def test_cache_survives_the_same_state():
    cache = MatchCache()
    cache.on_state_changed("메인화면")
    cache.remember("버튼", Match(10, 10, 5, 5, 0.9))

    cache.on_state_changed("메인화면")

    assert cache.has("버튼")


# ---------------------------------------------------------------- 캐시 + 탐색 연동


def test_cache_hint_speeds_up_the_second_search():
    button = make_button()
    scene = place(make_scene(1920, 1080), button, 1300, 600)
    cache = MatchCache()

    first = SearchStats()
    found = find(scene, [button], SearchOptions(threshold=0.9), first)
    cache.remember("버튼", found[0])

    second = SearchStats()
    again = find(
        scene, [button], SearchOptions(threshold=0.9, hint=cache.hint("버튼")), second
    )

    assert (again[0].x, again[0].y) == (1300, 600)
    assert second.pixels_scanned < first.pixels_scanned / 5
