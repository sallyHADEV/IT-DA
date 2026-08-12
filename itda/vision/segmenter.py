"""객체화 도구용 자동 영역 분할.

스크린샷 한 장을 넣으면 아이콘·버튼·글자 후보 영역을 잘라 준다. 완벽할 필요는 없다 —
사용자가 화면에서 눈으로 보고 고르며, 필요하면 직접 박스를 그린다. 목표는 "버튼 30개를
일일이 드래그하지 않게" 하는 것이다.

방법:
1. 명암 대비를 키운 뒤 두 갈래로 후보를 만든다.
   * MSER — 아이콘과 글자 덩어리에 강하다.
   * 적응형 이진화 + 모폴로지 닫기 → 윤곽선 — 버튼처럼 테두리가 있는 것에 강하다.
2. 크기·비율로 걸러 낸다.
3. 겹치거나 거의 같은 상자를 합친다.
4. 가로로 가까운 글자 덩어리는 한 줄로 묶는다.
5. 모양으로 icon / text / button 을 추정한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Region:
    """분할 결과 상자 하나. 좌표는 입력 이미지 기준."""

    x: int
    y: int
    w: int
    h: int
    kind: str = "icon"  # icon | text | button

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    def contains(self, other: Region) -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.x + self.w >= other.x + other.w
            and self.y + self.h >= other.y + other.h
        )


@dataclass
class SegmentOptions:
    min_width: int = 8
    min_height: int = 8
    max_width_ratio: float = 0.9   # 이미지 폭 대비
    max_height_ratio: float = 0.6
    merge_iou: float = 0.55        # 이 이상 겹치면 같은 것으로 본다
    line_gap: int = 12             # 글자 덩어리를 한 줄로 묶을 가로 간격
    use_mser: bool = True
    use_contours: bool = True
    max_regions: int = 400


def propose_regions(image: np.ndarray, options: SegmentOptions | None = None) -> list[Region]:
    """스크린샷에서 잘라 쓸 만한 영역 후보를 찾는다."""
    opt = options or SegmentOptions()
    if image is None or image.size == 0:
        return []

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape[:2]

    boxes: list[tuple[int, int, int, int]] = []
    if opt.use_mser:
        boxes += _mser_boxes(gray)
    if opt.use_contours:
        boxes += _contour_boxes(gray)

    regions = [
        Region(x, y, w, h)
        for (x, y, w, h) in boxes
        if _keep(x, y, w, h, width, height, opt)
    ]
    regions = _merge_overlaps(regions, opt.merge_iou)
    regions += _group_lines(regions, opt.line_gap)
    regions = _merge_overlaps(regions, 0.9)
    regions = [_classify(r) for r in regions]
    regions.sort(key=lambda r: (r.y, r.x))
    return regions[: opt.max_regions]


# ---------------------------------------------------------------- 후보 생성


def _mser_boxes(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    try:
        mser = cv2.MSER.create()
        mser.setMinArea(40)
        mser.setMaxArea(int(gray.shape[0] * gray.shape[1] * 0.25))
        regions, _ = mser.detectRegions(gray)
    except cv2.error:  # 환경에 따라 MSER 이 없을 수 있다
        return []
    return [tuple(int(v) for v in cv2.boundingRect(r.reshape(-1, 1, 2))) for r in regions]


def _contour_boxes(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 21, 8
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    # 테두리가 뚜렷한 버튼을 잡기 위해 에지 기반도 한 번 더
    edges = cv2.Canny(gray, 60, 160)
    edges = cv2.dilate(edges, kernel, iterations=1)
    contours2, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    return [tuple(int(v) for v in cv2.boundingRect(c)) for c in (*contours, *contours2)]


def _keep(x: int, y: int, w: int, h: int, width: int, height: int, opt: SegmentOptions) -> bool:
    if w < opt.min_width or h < opt.min_height:
        return False
    if w > width * opt.max_width_ratio and h > height * opt.max_height_ratio:
        return False  # 화면 전체에 가까운 상자는 쓸모없다
    if w / max(1, h) > 40 or h / max(1, w) > 40:
        return False
    return True


# ---------------------------------------------------------------- 병합


def iou(a: Region, b: Region) -> float:
    ax2, ay2 = a.x + a.w, a.y + a.h
    bx2, by2 = b.x + b.w, b.y + b.h
    inter_w = max(0, min(ax2, bx2) - max(a.x, b.x))
    inter_h = max(0, min(ay2, by2) - max(a.y, b.y))
    inter = inter_w * inter_h
    if inter == 0:
        return 0.0
    return inter / float(a.area + b.area - inter)


def _merge_overlaps(regions: list[Region], threshold: float) -> list[Region]:
    """겹치는 상자를 합친다. 큰 것이 작은 것을 완전히 품으면 큰 것만 남긴다."""
    ordered = sorted(regions, key=lambda r: r.area, reverse=True)
    kept: list[Region] = []
    for region in ordered:
        duplicate = False
        for i, other in enumerate(kept):
            if iou(region, other) >= threshold or other.contains(region):
                duplicate = True
                break
            if region.contains(other):
                kept[i] = region
                duplicate = True
                break
        if not duplicate:
            kept.append(region)
    return kept


def _group_lines(regions: list[Region], gap: int) -> list[Region]:
    """같은 줄에서 가로로 붙어 있는 작은 상자들을 한 덩어리로 묶는다 (글자 → 단어/문장)."""
    smalls = [r for r in regions if r.h <= 34]
    smalls.sort(key=lambda r: (round(r.y / 8), r.x))

    merged: list[Region] = []
    current: list[Region] = []

    def flush() -> None:
        if len(current) < 2:
            current.clear()
            return
        x1 = min(r.x for r in current)
        y1 = min(r.y for r in current)
        x2 = max(r.x + r.w for r in current)
        y2 = max(r.y + r.h for r in current)
        merged.append(Region(x1, y1, x2 - x1, y2 - y1, "text"))
        current.clear()

    for region in smalls:
        if not current:
            current.append(region)
            continue
        last = current[-1]
        same_line = abs(region.y - last.y) <= max(6, last.h // 2)
        close = region.x - (last.x + last.w) <= gap
        if same_line and close:
            current.append(region)
        else:
            flush()
            current.append(region)
    flush()
    return merged


def _classify(region: Region) -> Region:
    if region.kind == "text":
        return region
    ratio = region.w / max(1, region.h)
    if 0.7 <= ratio <= 1.4 and region.h <= 64:
        kind = "icon"
    elif ratio > 2.2 and region.h <= 60:
        kind = "button"
    else:
        kind = "icon" if region.area < 6000 else "button"
    return Region(region.x, region.y, region.w, region.h, kind)


def crop(image: np.ndarray, region: Region, padding: int = 0) -> np.ndarray:
    """영역을 잘라 낸다. 이미지 밖으로 나가지 않게 자른다."""
    height, width = image.shape[:2]
    x1 = max(0, region.x - padding)
    y1 = max(0, region.y - padding)
    x2 = min(width, region.x + region.w + padding)
    y2 = min(height, region.y + region.h + padding)
    if x2 <= x1 or y2 <= y1:
        return np.zeros((0, 0, 3), dtype=image.dtype)
    return image[y1:y2, x1:x2].copy()
