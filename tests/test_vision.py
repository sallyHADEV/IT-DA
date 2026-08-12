"""영역 자동 분할 / 캡처 변환 테스트.

실제 화면을 잡을 수는 없으므로 합성 이미지로 검증한다.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from itda.vision.segmenter import (
    Region,
    SegmentOptions,
    crop,
    iou,
    propose_regions,
)


def make_ui_image() -> np.ndarray:
    """버튼 세 개와 아이콘 하나가 있는 가짜 UI 를 그린다."""
    image = np.full((320, 520, 3), 240, dtype=np.uint8)
    # 버튼 3개
    for i, x in enumerate((30, 200, 370)):
        cv2.rectangle(image, (x, 40), (x + 120, 82), (60, 60, 60), 2)
        cv2.putText(image, f"BTN{i}", (x + 20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 2)
    # 아이콘(작은 사각형)
    cv2.rectangle(image, (40, 150), (72, 182), (20, 90, 160), -1)
    # 글자 한 줄
    cv2.putText(image, "Settings menu", (120, 175), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 40, 40), 2)
    return image


def test_propose_regions_finds_ui_elements():
    regions = propose_regions(make_ui_image())

    assert regions, "후보를 하나도 못 찾으면 도구가 쓸모없다"
    # 버튼 세 개 근처(y 40~82)에 후보가 있어야 한다
    near_buttons = [r for r in regions if 30 <= r.y <= 90]
    assert len(near_buttons) >= 3
    # 아이콘 자리에도 후보가 있어야 한다
    assert any(35 <= r.x <= 80 and 140 <= r.y <= 190 for r in regions)


def test_regions_are_inside_image():
    image = make_ui_image()
    height, width = image.shape[:2]
    for r in propose_regions(image):
        assert 0 <= r.x and 0 <= r.y
        assert r.x + r.w <= width and r.y + r.h <= height
        assert r.w > 0 and r.h > 0


def test_regions_have_known_kinds():
    for r in propose_regions(make_ui_image()):
        assert r.kind in ("icon", "text", "button")


def test_min_size_option_filters_small_boxes():
    image = make_ui_image()
    big = propose_regions(image, SegmentOptions(min_width=60, min_height=30))
    assert all(r.w >= 60 and r.h >= 30 for r in big)
    assert len(big) < len(propose_regions(image))


def test_blank_image_yields_few_regions():
    blank = np.full((200, 200, 3), 255, dtype=np.uint8)
    assert len(propose_regions(blank)) <= 2


def test_empty_image_is_handled():
    assert propose_regions(np.zeros((0, 0, 3), dtype=np.uint8)) == []
    assert propose_regions(None) == []


def test_overlapping_duplicates_are_merged():
    image = make_ui_image()
    regions = propose_regions(image)
    for i, a in enumerate(regions):
        for b in regions[i + 1:]:
            assert iou(a, b) < 0.9, "거의 같은 상자가 중복으로 남아 있다"


def test_iou_basics():
    a = Region(0, 0, 10, 10)
    assert iou(a, a) == pytest.approx(1.0)
    assert iou(a, Region(20, 20, 5, 5)) == 0.0
    assert 0 < iou(a, Region(5, 5, 10, 10)) < 1


def test_crop_respects_bounds():
    image = make_ui_image()
    patch = crop(image, Region(500, 300, 40, 40), padding=5)
    assert patch.shape[0] > 0 and patch.shape[1] > 0
    assert patch.shape[0] <= 45 and patch.shape[1] <= 45

    assert crop(image, Region(-100, -100, 10, 10)).size == 0


def test_crop_padding_expands():
    image = make_ui_image()
    tight = crop(image, Region(100, 100, 20, 20))
    padded = crop(image, Region(100, 100, 20, 20), padding=4)
    assert padded.shape[0] == tight.shape[0] + 8
    assert padded.shape[1] == tight.shape[1] + 8


# ---------------------------------------------------------------- 캡처 변환


def test_pixmap_bgr_roundtrip(qapp):
    from itda.vision import capture

    source = make_ui_image()
    pixmap = capture.bgr_to_pixmap(source)
    assert pixmap.width() == source.shape[1]

    restored = capture.pixmap_to_bgr(pixmap)
    assert restored.shape == source.shape
    # PNG 무손실 경로가 아니므로 완전 일치는 요구하지 않되, 색이 뒤집히면 안 된다
    assert np.abs(restored.astype(int) - source.astype(int)).mean() < 2


def test_save_and_load_bgr_with_korean_path(tmp_path):
    from itda.vision import capture

    source = make_ui_image()
    path = tmp_path / "한글폴더" / "이미지.png"
    assert capture.save_bgr(source, path)

    loaded = capture.load_bgr(path)
    assert loaded.shape == source.shape
    assert np.array_equal(loaded, source)


def test_load_missing_file_returns_empty(tmp_path):
    from itda.vision import capture

    assert capture.load_bgr(tmp_path / "없음.png").size == 0
