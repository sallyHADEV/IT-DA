"""실행 문맥.

액션 하나하나가 필요로 하는 것들을 한 곳에 모은다 — 화면, 입력, 변수, 타이밍, 로그.
액션의 ``execute`` 가 짧게 유지되는 이유가 이 객체다.

**안전 규칙**: 실제 입력은 ``sender`` 를 통해서만 나간다. 기본값은
:class:`~itda.engine.input.DryRunSender` 라, 명시적으로 실주입기를 넣기 전에는 아무것도
움직이지 않는다.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from itda.core.events import BUS
from itda.core.humanize import HumanProfile
from itda.core.timing import Timing, TimingProfile, jitter_ms, resolve
from itda.core.variables import VariableStore, cast_value, interpolate, safe_eval
from itda.engine.input import DryRunSender, Sender
from itda.engine.input.planner import resolve_human
from itda.engine.input.steps import Step
from itda.vision import capture, coords
from itda.vision.matcher import Match, MatchCache, SearchOptions, SearchStats, find

#: 화면을 다시 찍기 전까지 재사용하는 시간. 한 노드 안에서 여러 번 찾을 때 캡처를 아낀다.
FRAME_TTL_MS = 120


class Stopped(Exception):
    """사용자가 정지를 눌렀다. 실행 흐름을 즉시 접는다."""


@dataclass
class ActionResult:
    """액션 하나의 결과."""

    ok: bool = True
    value: Any = None
    message: str = ""

    @classmethod
    def failed(cls, message: str) -> ActionResult:
        return cls(ok=False, message=message)


@dataclass
class ExecutionContext:
    """플로우 하나를 실행하는 동안 유지되는 상태."""

    project: Any
    flow_key: str = ""
    sender: Sender = field(default_factory=DryRunSender)
    variables: VariableStore = field(default_factory=VariableStore)
    cache: MatchCache = field(default_factory=MatchCache)
    rng: random.Random = field(default_factory=random.Random)
    #: 실행을 멈추라는 신호. 러너와 GUI 가 함께 본다.
    stop_flag: dict = field(default_factory=lambda: {"stop": False})
    #: 현재 노드/액션 (로그에 위치를 남기려고)
    node_title: str = ""
    action_title: str = ""
    #: 서브플로우 호출 훅 — 러너가 채운다. (플로우 이름, 인자, 대기여부) -> 성공
    run_flow: Any = None
    #: 실행 중 주기적으로 부를 콜백. GUI 가 화면을 갱신하고 정지 버튼을 받도록 한다.
    tick: Any = None
    #: 상황 머신 (:class:`itda.engine.state_machine.StateMachine`). 엔진이 채운다.
    states: Any = None
    #: 입력 장치 중재기 (:class:`itda.engine.arbiter.InputArbiter`). 멀티 플로우일 때만.
    arbiter: Any = None
    #: 이 플로우의 우선순위 — 중재기가 순서를 정하는 기준.
    priority: int = 0
    #: 지금 입력 잠금을 쥐고 있는 이름. 러너가 노드마다 채운다.
    #: ``flow_key`` 를 쓰지 않는 이유 — 서브플로우를 부르는 동안 그 값이 바뀌어서,
    #: 정작 잠금을 쥔 바깥 플로우에게 심장박동이 전달되지 않는다.
    arbiter_owner: str = ""

    _frame: np.ndarray | None = field(default=None, repr=False)
    _frame_at: float = 0.0
    _cursor: tuple[int, int] = (0, 0)

    # ------------------------------------------------------------ 설정 접근

    @property
    def timing(self) -> TimingProfile:
        return self.project.settings.timing

    @property
    def human_profile(self) -> HumanProfile:
        return self.project.settings.human

    def human(self, params: dict | None = None) -> HumanProfile:
        """액션의 ``humanize`` 설정(상속/켬/끔)을 반영한 프로파일."""
        setting = (params or {}).get("humanize", "inherit")
        return resolve_human(self.human_profile, setting)

    # ------------------------------------------------------------ 정지

    def stop(self) -> None:
        self.stop_flag["stop"] = True

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_flag.get("stop"))

    def check_stop(self) -> None:
        """정지 확인. 실행 중 가장 자주 불리는 지점이라 GUI 갱신도 여기서 한다.

        입력 잠금의 심장박동도 여기서 보낸다 — 이미지 찾기·대기의 폴링 루프가 매 회차마다
        부르므로, 정상 동작 중인 노드는 자연히 살아 있다고 알리게 된다. 반대로 진짜 멈춘
        플로우는 여기에 못 오므로 중재기가 예정대로 잠금을 회수한다.
        """
        if self.tick is not None:
            self.tick()
        if self.arbiter is not None and self.arbiter_owner:
            self.arbiter.touch(self.arbiter_owner)
        if self.should_stop:
            raise Stopped()

    # ------------------------------------------------------------ 시간

    def sleep(self, ms: float, jitter_pct: float | None = None) -> None:
        """대기. 정지를 누르면 곧바로 빠져나온다."""
        if ms <= 0:
            return
        pct = self.timing.jitter_pct if jitter_pct is None else jitter_pct
        total = jitter_ms(int(ms), max(0.0, pct), self.rng) / 1000.0
        end = time.perf_counter() + total
        while True:
            self.check_stop()
            remaining = end - time.perf_counter()
            if remaining <= 0:
                return
            time.sleep(min(0.05, remaining))

    def delay_before(self, timing: Timing | None) -> None:
        resolved = resolve(timing, self.timing)
        self.sleep(resolved.pre_ms, resolved.jitter_pct)

    def delay_after(self, timing: Timing | None) -> None:
        resolved = resolve(timing, self.timing)
        self.sleep(resolved.post_ms, resolved.jitter_pct)

    # ------------------------------------------------------------ 화면

    def screen(self, fresh: bool = False) -> np.ndarray:
        """현재 화면(물리 픽셀). 짧은 시간 안에는 같은 프레임을 재사용한다."""
        now = time.perf_counter() * 1000
        if fresh or self._frame is None or (now - self._frame_at) > FRAME_TTL_MS:
            # 작업 스레드에서도 동작하는 경로(Windows 는 GDI)를 쓴다
            self._frame = capture.grab_array()
            self._frame_at = now
        return self._frame

    def screen_region(
        self, roi: tuple[int, int, int, int] | None
    ) -> tuple[np.ndarray, int, int, bool]:
        """검색에 쓸 화면 조각 ``(frame, dx, dy, 잘라왔는가)``.

        ``roi`` 가 없으면 평소처럼 전체 화면(과 그 캐시)을 쓴다. 있으면 **그 사각형만**
        새로 찍는다 — 전체를 찍어 잘라 쓰는 것보다 훨씬 싸고, 폴링 중에는 어차피 매번
        새 프레임이 필요해서 캐시를 못 쓴다.

        마지막 값이 필요한 이유: ROI 가 (0, 0) 에서 시작하면 ``dx``·``dy`` 가 0 이라
        오프셋만 봐서는 잘라 왔는지 알 수 없고, 매처가 조각을 한 번 더 자르게 된다.
        """
        if not roi:
            return self.screen(), 0, 0, False
        x, y, w, h = (int(v) for v in roi)
        if w <= 0 or h <= 0:
            return self.screen(), 0, 0, False
        patch = capture.grab_array((x, y, w, h))
        if patch.size == 0:  # 캡처 실패 — 전체 화면으로 물러난다
            return self.screen(), 0, 0, False
        return patch, x, y, True

    def _local_hint(self, name: str, dx: int, dy: int) -> tuple[int, int] | None:
        """기억해 둔 위치(화면 좌표)를 잘라 낸 조각 기준으로 옮긴다."""
        hint = self.cache.hint(name)
        if hint is None:
            return None
        return (hint[0] - dx, hint[1] - dy)

    def invalidate_frame(self) -> None:
        """화면을 바꾼 직후(클릭·창 이동 등)에는 캐시를 버린다."""
        self._frame = None

    def screens(self) -> list[coords.ScreenInfo]:
        return coords.current_screens()

    # ------------------------------------------------------------ 객체 찾기

    def object_by_name(self, name: str):
        repo = self.project.objects
        return repo.get(name) or repo.by_name(name)

    def templates_of(self, name: str) -> list[np.ndarray]:
        """객체의 이미지들을 읽어 온다."""
        obj = self.object_by_name(name)
        if obj is None:
            return []
        images = []
        for relative in obj.images:
            path = self.project.image_path(relative)
            if path is None:
                continue
            image = capture.load_bgr(Path(path))
            if image.size:
                images.append(image)
        return images

    def find_object(
        self,
        names: list[str],
        threshold: float = 0.0,
        mode: str = "any",
        roi: tuple[int, int, int, int] | None = None,
        use_hint: bool = True,
        stats: SearchStats | None = None,
    ) -> Match | None:
        """객체(여러 개면 mode 대로)를 화면에서 찾는다. 찾으면 위치를 기억한다."""
        found: list[Match] = []
        # 검색 범위가 정해져 있으면 **그만큼만 찍는다.** 예전에는 늘 가상 데스크톱 전체를
        # 찍어 놓고 매처가 잘라 썼는데, 모니터 두 대(3440x2640 = 9.1M 픽셀)에서 한 번에
        # 131ms 가 들었다 — 300x200 만 찍으면 8ms 다(실측). 폴링 루프가 이걸 반복한다.
        frame, dx, dy, cropped = self.screen_region(roi)
        # 조각을 이미 잘라 왔으면 매처가 또 자를 필요가 없다. 못 잘라 왔으면(전체 화면으로
        # 물러난 경우) 예전처럼 매처에게 맡긴다.
        local_roi = None if cropped else roi
        for name in names:
            obj = self.object_by_name(name)
            templates = self.templates_of(name)
            if not templates:
                continue
            options = SearchOptions(
                threshold=threshold or (obj.match.threshold if obj else None)
                or self.timing.match_threshold,
                mode="any",
                scales=tuple(obj.match.scales) if obj and obj.match.scales else (1.0,),
                grayscale=obj.match.grayscale if obj else True,
                roi=local_roi,
                hint=self._local_hint(name, dx, dy) if use_hint else None,
            )
            # 결과는 잘라 낸 조각 기준이라, 기억하거나 돌려주기 전에 화면 좌표로 되돌린다.
            matches = [m.offset(dx, dy) for m in find(frame, templates, options, stats)]
            if matches:
                self.cache.remember(name, matches[0])
                if mode == "any":
                    return matches[0]
                found.append(matches[0])
            if mode == "all":
                if not matches:
                    return None
        if mode == "all" and len(found) != len(names):
            return None
        return max(found, key=lambda match: match.score) if found else None

    def object_point(self, name: str, lookup: str = "cache_or_search") -> tuple[int, int] | None:
        """객체의 클릭 지점. ``lookup`` 규칙(최근 위치 재사용/항상 새로 찾기)을 따른다."""
        obj = self.object_by_name(name)
        anchor = (obj.anchor_dx, obj.anchor_dy) if obj else (0, 0)

        if lookup != "always":
            center = self.cache.center(name)
            if center is not None:
                return (center[0] + anchor[0], center[1] + anchor[1])
            if lookup == "cache_only":
                return None

        match = self.find_object([name])
        if match is None:
            return None
        cx, cy = match.center
        return (cx + anchor[0], cy + anchor[1])

    # ------------------------------------------------------------ 입력

    def send(self, steps: list[Step]) -> None:
        """계획한 입력을 주입한다. 중간에 정지를 누르면 멈춘다."""
        for step in steps:
            self.check_stop()
            self.sender.wait(step.delay_ms)
            self.sender.apply(step)
            if step.kind in ("move", "touch"):
                self._cursor = (step.x, step.y)
        self.invalidate_frame()

    @property
    def cursor(self) -> tuple[int, int]:
        return self._cursor

    # ------------------------------------------------------------ 변수 / 문자열

    def text(self, template: str) -> str:
        return interpolate(template or "", self.variables.snapshot())

    def value(self, expr: str) -> Any:
        return safe_eval(expr or "", self.variables.snapshot())

    def truthy(self, expr: str) -> bool:
        try:
            return bool(self.value(expr))
        except Exception as e:
            self.log(f"조건식 오류: {e}", level="warn")
            return False

    def set_var(self, name: str, value: Any, scope: str = "flow") -> None:
        if name:
            self.variables.set(name, value, scope)

    def seed_variables(self, flow) -> None:
        """선언된 변수들을 기본값으로 채운다."""
        for decl in self.project.settings.globals:
            if decl.name:
                self.variables.set(decl.name, cast_value(decl.default, decl.type), "global")
        for decl in getattr(flow, "variables", []):
            if decl.name:
                self.variables.set(decl.name, cast_value(decl.default, decl.type), "flow")

    def publish_variables(self) -> None:
        BUS.variables.emit(self.flow_key, self.variables.snapshot())

    # ------------------------------------------------------------ 로그

    def log(self, message: str, level: str = "info") -> None:
        BUS.log(message, level=level, flow=self.flow_key,
                node=self.node_title, action=self.action_title)
