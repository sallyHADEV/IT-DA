"""템플릿 매칭.

4K 화면에서 전체 탐색을 매번 돌리면 느리다. 세 가지로 줄인다.

1. **ROI 우선** — 같은 객체를 방금 찾은 자리 주변을 먼저 본다. 화면이 그대로면 여기서 끝난다.
2. **피라미드 2단계** — 0.5배로 줄여 후보를 찾고, 후보 주변만 원본 해상도로 정밀 검증한다.
   축소본은 픽셀 수가 1/4 이라 1차 탐색 비용이 크게 준다.
3. **조기 종료** — 여러 이미지를 `any` 로 찾을 때는 첫 성공에서 멈춘다.

좌표는 전부 물리 픽셀이다(:mod:`itda.vision.coords` 규칙).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

#: 축소 단계에서는 임계값을 조금 낮춰 후보를 놓치지 않는다. 정밀 검증이 걸러 준다.
COARSE_SLACK = 0.12
#: 이 픽셀 수보다 작으면 축소해 봐야 이득이 없다
PYRAMID_MIN_PIXELS = 640 * 480
#: 축소 배율
PYRAMID_SCALE = 0.5
#: 최근 위치 주변을 볼 때 넓히는 여백
HINT_MARGIN = 48


@dataclass(frozen=True)
class Match:
    """찾은 위치. 좌표는 원본(화면) 기준."""

    x: int
    y: int
    width: int
    height: int
    score: float
    #: 어느 템플릿이 맞았는지 (객체가 이미지를 여러 장 가질 때)
    index: int = 0

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    def offset(self, dx: int, dy: int) -> Match:
        return Match(self.x + dx, self.y + dy, self.width, self.height, self.score, self.index)


@dataclass
class SearchStats:
    """어디서 어떻게 찾았는지. 로그와 성능 확인에 쓴다."""

    stages: list[str] = field(default_factory=list)
    pixels_scanned: int = 0
    elapsed_ms: float = 0.0

    def note(self, stage: str, pixels: int = 0) -> None:
        self.stages.append(stage)
        self.pixels_scanned += pixels

    def describe(self) -> str:
        return f"{' → '.join(self.stages) or '없음'} · {self.pixels_scanned:,}px · {self.elapsed_ms:.1f}ms"


@dataclass
class SearchOptions:
    threshold: float = 0.88
    #: any=하나라도 / best=가장 높은 점수 / all=전부
    mode: str = "any"
    scales: tuple[float, ...] = (1.0,)
    grayscale: bool = True
    #: 검색 범위 (x, y, w, h). None 이면 전체
    roi: tuple[int, int, int, int] | None = None
    #: 최근 찾은 위치 (x, y). 주변을 먼저 본다
    hint: tuple[int, int] | None = None
    hint_margin: int = HINT_MARGIN
    use_pyramid: bool = True
    #: 같은 것을 여러 번 잡지 않도록 겹침 제한
    overlap: float = 0.4
    #: find_all 에서 최대 몇 개까지
    limit: int = 32


# ---------------------------------------------------------------- 공개 API


def find(
    haystack: np.ndarray,
    templates: list[np.ndarray],
    options: SearchOptions | None = None,
    stats: SearchStats | None = None,
) -> list[Match]:
    """화면에서 템플릿을 찾는다.

    Returns:
        ``mode`` 에 따른 결과. any/best 는 0~1개, all 은 템플릿마다 하나씩.
        ``all`` 인데 하나라도 못 찾으면 빈 목록.
    """
    options = options or SearchOptions()
    stats = stats if stats is not None else SearchStats()
    started = time.perf_counter()
    try:
        return _find(haystack, templates, options, stats)
    finally:
        stats.elapsed_ms = (time.perf_counter() - started) * 1000


def find_all(
    haystack: np.ndarray,
    template: np.ndarray,
    options: SearchOptions | None = None,
    stats: SearchStats | None = None,
) -> list[Match]:
    """같은 이미지가 여러 개 있을 때 전부 찾는다 (목록의 항목 등)."""
    options = options or SearchOptions()
    stats = stats if stats is not None else SearchStats()
    started = time.perf_counter()
    try:
        region, dx, dy = _apply_roi(haystack, options.roi)
        if not _usable(region, template):
            return []
        scene = _prepare(region, options.grayscale)
        needle = _prepare(template, options.grayscale)
        stats.note("전체 탐색", _pixels(scene))
        result = cv2.matchTemplate(scene, needle, cv2.TM_CCOEFF_NORMED)
        matches = _peaks(result, needle.shape[1], needle.shape[0], options, index=0)
        return [m.offset(dx, dy) for m in matches][: options.limit]
    finally:
        stats.elapsed_ms = (time.perf_counter() - started) * 1000


def _find(
    haystack: np.ndarray,
    templates: list[np.ndarray],
    options: SearchOptions,
    stats: SearchStats,
) -> list[Match]:
    usable = [t for t in templates if t is not None and t.size]
    if haystack is None or not haystack.size or not usable:
        return []

    # 1) 최근 찾은 위치 주변부터
    if options.hint is not None:
        hinted = _search_hint(haystack, usable, options, stats)
        if hinted:
            return hinted

    # 2) 지정 범위(또는 전체)
    region, dx, dy = _apply_roi(haystack, options.roi)
    found: list[Match] = []
    for index, template in enumerate(usable):
        match = _search_one(region, template, options, stats)
        if match is not None:
            found.append(match.offset(dx, dy))
            if options.mode == "any":
                return found
        elif options.mode == "all":
            return []  # 하나라도 없으면 실패

    if not found:
        return []
    if options.mode == "best":
        return [max(found, key=lambda m: m.score)]
    return found


def _search_hint(
    haystack: np.ndarray,
    templates: list[np.ndarray],
    options: SearchOptions,
    stats: SearchStats,
) -> list[Match]:
    """최근 위치 주변만 먼저 본다. 대부분의 반복 작업이 여기서 끝난다."""
    hx, hy = options.hint
    biggest = max(templates, key=lambda t: t.shape[0] * t.shape[1])
    th, tw = biggest.shape[:2]
    margin = options.hint_margin
    box = (
        hx - margin,
        hy - margin,
        tw + margin * 2,
        th + margin * 2,
    )
    region, dx, dy = _apply_roi(haystack, box)
    if not region.size:
        return []
    # 실제 스캔량은 아래 _search_one 이 기록한다. 여기서 더하면 이중 계산이 된다.
    stats.note("최근 위치 주변")

    narrow = SearchOptions(
        threshold=options.threshold,
        mode=options.mode,
        scales=options.scales,
        grayscale=options.grayscale,
        use_pyramid=False,  # 이미 작은 영역이다
        overlap=options.overlap,
    )
    found: list[Match] = []
    for index, template in enumerate(templates):
        match = _search_one(region, template, narrow, stats)
        if match is not None:
            found.append(Match(match.x + dx, match.y + dy, match.width, match.height,
                               match.score, index))
            if options.mode == "any":
                return found
        elif options.mode == "all":
            return []
    if options.mode == "best" and found:
        return [max(found, key=lambda m: m.score)]
    return found


def _search_one(
    scene_bgr: np.ndarray,
    template_bgr: np.ndarray,
    options: SearchOptions,
    stats: SearchStats,
) -> Match | None:
    """템플릿 하나. 배율 목록을 돌며 가장 좋은 결과를 고른다."""
    best: Match | None = None
    for scale in options.scales or (1.0,):
        template = _rescale(template_bgr, scale)
        if not _usable(scene_bgr, template):
            continue
        candidate = (
            _match_pyramid(scene_bgr, template, options, stats)
            if _should_use_pyramid(scene_bgr, template, options)
            else _match_direct(scene_bgr, template, options, stats)
        )
        if candidate is not None and (best is None or candidate.score > best.score):
            best = candidate
    return best


# ---------------------------------------------------------------- 단계별 구현


def _match_direct(
    scene_bgr: np.ndarray,
    template_bgr: np.ndarray,
    options: SearchOptions,
    stats: SearchStats,
) -> Match | None:
    scene = _prepare(scene_bgr, options.grayscale)
    needle = _prepare(template_bgr, options.grayscale)
    stats.note("원본 탐색", _pixels(scene))
    result = cv2.matchTemplate(scene, needle, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
    if max_val < options.threshold:
        return None
    return Match(int(max_loc[0]), int(max_loc[1]), needle.shape[1], needle.shape[0],
                 float(max_val))


def _match_pyramid(
    scene_bgr: np.ndarray,
    template_bgr: np.ndarray,
    options: SearchOptions,
    stats: SearchStats,
) -> Match | None:
    """축소본에서 후보를 찾고 원본에서 확인한다."""
    scene = _prepare(scene_bgr, options.grayscale)
    needle = _prepare(template_bgr, options.grayscale)

    small_scene = cv2.resize(scene, None, fx=PYRAMID_SCALE, fy=PYRAMID_SCALE,
                             interpolation=cv2.INTER_AREA)
    small_needle = cv2.resize(needle, None, fx=PYRAMID_SCALE, fy=PYRAMID_SCALE,
                              interpolation=cv2.INTER_AREA)
    if not _usable(small_scene, small_needle):
        return _match_direct(scene_bgr, template_bgr, options, stats)

    stats.note("축소 탐색", _pixels(small_scene))
    coarse = cv2.matchTemplate(small_scene, small_needle, cv2.TM_CCOEFF_NORMED)
    loose = max(0.05, options.threshold - COARSE_SLACK)
    candidates = _peak_points(coarse, loose, limit=5,
                              width=small_needle.shape[1], height=small_needle.shape[0],
                              overlap=options.overlap)
    if not candidates:
        return None

    th, tw = needle.shape[:2]
    pad = 8
    best: Match | None = None
    for cx, cy, _score in candidates:
        x = int(cx / PYRAMID_SCALE) - pad
        y = int(cy / PYRAMID_SCALE) - pad
        window, dx, dy = _apply_roi(scene, (x, y, tw + pad * 2, th + pad * 2))
        if not _usable(window, needle):
            continue
        stats.note("정밀 검증", _pixels(window))
        result = cv2.matchTemplate(window, needle, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
        if max_val >= options.threshold:
            match = Match(int(max_loc[0]) + dx, int(max_loc[1]) + dy, tw, th, float(max_val))
            if best is None or match.score > best.score:
                best = match
    return best


# ---------------------------------------------------------------- 보조


def _should_use_pyramid(scene: np.ndarray, template: np.ndarray, options: SearchOptions) -> bool:
    if not options.use_pyramid:
        return False
    if scene.shape[0] * scene.shape[1] < PYRAMID_MIN_PIXELS:
        return False
    # 템플릿이 너무 작으면 축소하면서 특징이 사라진다
    return min(template.shape[0], template.shape[1]) >= 16


def _pixels(image: np.ndarray) -> int:
    """픽셀 수. ``ndarray.size`` 는 3채널이면 3배로 세므로 쓰면 안 된다."""
    if image is None or not image.size:
        return 0
    return int(image.shape[0] * image.shape[1])


def _prepare(image: np.ndarray, grayscale: bool) -> np.ndarray:
    if grayscale and image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def _rescale(template: np.ndarray, scale: float) -> np.ndarray:
    if abs(scale - 1.0) < 1e-6:
        return template
    return cv2.resize(template, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)


def _usable(scene: np.ndarray, template: np.ndarray) -> bool:
    """템플릿이 화면보다 크면 매칭할 수 없다."""
    if scene is None or template is None or not scene.size or not template.size:
        return False
    return scene.shape[0] >= template.shape[0] and scene.shape[1] >= template.shape[1]


def _apply_roi(
    image: np.ndarray, roi: tuple[int, int, int, int] | None
) -> tuple[np.ndarray, int, int]:
    """ROI 를 잘라 내고 원본 좌표로 되돌릴 오프셋을 함께 준다."""
    if roi is None:
        return image, 0, 0
    x, y, w, h = roi
    height, width = image.shape[:2]
    x1 = max(0, min(width, x))
    y1 = max(0, min(height, y))
    x2 = max(0, min(width, x + w))
    y2 = max(0, min(height, y + h))
    if x2 <= x1 or y2 <= y1:
        return image[0:0, 0:0], 0, 0
    return image[y1:y2, x1:x2], x1, y1


def _peak_points(
    result: np.ndarray, threshold: float, limit: int, width: int, height: int, overlap: float
) -> list[tuple[int, int, float]]:
    """상관계수 맵에서 서로 떨어진 상위 후보들."""
    points: list[tuple[int, int, float]] = []
    work = result.copy()
    for _ in range(limit):
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(work)
        if max_val < threshold:
            break
        points.append((int(max_loc[0]), int(max_loc[1]), float(max_val)))
        # 주변을 지워 같은 봉우리를 다시 잡지 않게 한다
        x0 = max(0, max_loc[0] - int(width * (1 - overlap)))
        y0 = max(0, max_loc[1] - int(height * (1 - overlap)))
        x1 = min(work.shape[1], max_loc[0] + int(width * (1 - overlap)) + 1)
        y1 = min(work.shape[0], max_loc[1] + int(height * (1 - overlap)) + 1)
        work[y0:y1, x0:x1] = -1
    return points


def _peaks(
    result: np.ndarray, width: int, height: int, options: SearchOptions, index: int
) -> list[Match]:
    return [
        Match(x, y, width, height, score, index)
        for x, y, score in _peak_points(
            result, options.threshold, options.limit, width, height, options.overlap
        )
    ]


# ---------------------------------------------------------------- 최근 위치 캐시


class MatchCache:
    """객체별 '최근 찾은 위치'.

    편집기 문서에 적어 둔 규칙(`cache_or_search` / `always` / `cache_only`)을 실제로 구현하는
    자리다. 수명은 플로우 한 번 실행이며, 상황이 바뀌면 버린다.
    """

    def __init__(self) -> None:
        self._boxes: dict[str, tuple[int, int, int, int]] = {}
        self._state: str = ""

    def remember(self, key: str, match: Match) -> None:
        self._boxes[key] = match.box

    def hint(self, key: str) -> tuple[int, int] | None:
        box = self._boxes.get(key)
        return (box[0], box[1]) if box else None

    def center(self, key: str) -> tuple[int, int] | None:
        box = self._boxes.get(key)
        return (box[0] + box[2] // 2, box[1] + box[3] // 2) if box else None

    def has(self, key: str) -> bool:
        return key in self._boxes

    def forget(self, key: str) -> None:
        self._boxes.pop(key, None)

    def clear(self) -> None:
        self._boxes.clear()

    def on_state_changed(self, state: str) -> None:
        """상황이 바뀌면 이전 화면에서 찾은 위치는 의미가 없다."""
        if state != self._state:
            self._state = state
            self.clear()
