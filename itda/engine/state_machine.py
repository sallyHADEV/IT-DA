"""상황 인식과 이동 — 이 도구의 간판 기능.

세 가지를 한다.

1. **판정** — 조건 트리를 평가해 지금 화면이 어떤 상황인지 이름을 붙인다.
2. **이동** — 목표 상황까지 전이 그래프의 최소 비용 경로를 찾아 그 동작들을 실행한다.
3. **가로채기(자가 복구)** — 광고·업데이트 팝업처럼 끼어드는 화면(``interrupt``)이 뜨면
   하던 일을 잠시 멈추고 그것부터 닫은 뒤, 원래 목표로 돌아간다.

3번이 없으면 "설정창으로 이동" 도중 팝업 하나에 경로가 통째로 무너진다. 다른 매크로 도구가
약한 지점이기도 하다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from itda.core.events import BUS
from itda.core.model import Condition, State, StateGraph
from itda.engine.context import ExecutionContext
from itda.engine.executors import run_sequence

#: 같은 인터럽트가 이만큼 연속으로 뜨면 포기한다 (무한 팝업 방어)
MAX_INTERRUPT_REPEATS = 3
#: 판정 결과를 재사용하는 시간
DETECT_TTL_MS = 250


@dataclass
class Detection:
    state: State | None
    at_ms: float

    @property
    def name(self) -> str:
        return self.state.name if self.state else ""


# ---------------------------------------------------------------- 조건 평가


def evaluate(condition: Condition | None, ctx: ExecutionContext) -> bool:
    """조건 트리 하나를 평가한다."""
    if condition is None:
        return False
    result = _evaluate_raw(condition, ctx)
    return (not result) if condition.negate else result


def _evaluate_raw(condition: Condition, ctx: ExecutionContext) -> bool:
    match condition.op:
        case "and":
            # 자식이 없는 묶음은 "아무 조건도 없음" 이다. 참으로 두면 모든 상황이 맞아 버린다.
            return bool(condition.items) and all(evaluate(c, ctx) for c in condition.items)
        case "or":
            return any(evaluate(c, ctx) for c in condition.items)
        case "not":
            return not all(evaluate(c, ctx) for c in condition.items)
        case _:
            return _evaluate_leaf(condition, ctx)


def _evaluate_leaf(condition: Condition, ctx: ExecutionContext) -> bool:
    params = condition.params or {}
    match condition.type:
        case "object_visible":
            name = params.get("object", "")
            if not name:
                return False
            return ctx.find_object([name], threshold=params.get("threshold", 0.0)) is not None
        case "window_title":
            title = _foreground_title(ctx)
            wanted = params.get("contains", "")
            if not wanted:
                return bool(title)
            return title == wanted if params.get("exact") else wanted.lower() in title.lower()
        case "window_active":
            wanted = params.get("title", "")
            return bool(wanted) and wanted.lower() in _foreground_title(ctx).lower()
        case "ocr_contains":
            return _ocr_contains(params, ctx)
        case "pixel_color":
            return _pixel_matches(params, ctx)
        case "expr":
            return ctx.truthy(params.get("expr", ""))
        case _:
            ctx.log(f"알 수 없는 조건: {condition.type}", level="warn")
            return False


def _foreground_title(ctx: ExecutionContext) -> str:
    try:
        from itda.engine.window import WindowController

        window = WindowController().foreground()
        return window.title if window else ""
    except Exception:
        return ""


def _ocr_contains(params: dict, ctx: ExecutionContext) -> bool:
    from itda.vision import ocr

    rect = params.get("region") or [0, 0, 0, 0]
    if rect[2] <= 0 or rect[3] <= 0:
        return False
    frame = ctx.screen()
    patch = frame[rect[1]:rect[1] + rect[3], rect[0]:rect[0] + rect[2]]
    result = ocr.read(patch, lang=params.get("lang", "kor+eng"),
                      layout=params.get("layout", ocr.DEFAULT_PSM))
    if not result.ok:
        ctx.log(result.message, level="warn")
        return False
    return params.get("text", "") in result.text


def _pixel_matches(params: dict, ctx: ExecutionContext) -> bool:
    point = params.get("point") or [0, 0]
    frame = ctx.screen()
    x, y = int(point[0]), int(point[1])
    if not (0 <= y < frame.shape[0] and 0 <= x < frame.shape[1]):
        return False
    blue, green, red = (int(v) for v in frame[y, x][:3])
    expected = str(params.get("color", "#ffffff")).lstrip("#")
    try:
        er, eg, eb = (int(expected[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return False
    tolerance = int(params.get("tolerance", 12))
    return all(abs(a - b) <= tolerance for a, b in ((red, er), (green, eg), (blue, eb)))


# ---------------------------------------------------------------- 상황 머신


class StateMachine:
    """상황 판정 · 이동 · 가로채기."""

    def __init__(self, graph: StateGraph, ctx: ExecutionContext) -> None:
        self.graph = graph
        self.ctx = ctx
        self._last = Detection(None, 0.0)
        self._interrupt_streak: dict[str, int] = {}

    # ------------------------------------------------------------ 판정

    def detect(self, fresh: bool = False) -> State | None:
        """지금 화면의 상황. 짧은 시간 안에는 직전 결과를 재사용한다."""
        now = time.perf_counter() * 1000
        if not fresh and (now - self._last.at_ms) < DETECT_TTL_MS:
            return self._last.state

        if fresh:
            self.ctx.invalidate_frame()

        matched: list[State] = []
        for state in self.graph.states:
            self.ctx.check_stop()
            if evaluate(state.condition, self.ctx):
                matched.append(state)

        # 끼어드는 화면이 먼저, 그다음 우선순위
        best = max(matched, key=lambda s: (s.interrupt, s.priority), default=None)
        self._last = Detection(best, now)

        name = best.name if best else self.graph.watcher.unknown_name
        BUS.state_detected.emit(best.id if best else "", name)
        return best

    def current_name(self) -> str:
        state = self.detect()
        return state.name if state else self.graph.watcher.unknown_name

    def resolve(self, key: str) -> State | None:
        """이름이나 id 로 상황을 찾는다."""
        return self.graph.state(key) or self.graph.state_by_name(key)

    def is_in(self, key: str) -> bool:
        target = self.resolve(key)
        if target is None:
            return False
        return self.detect() is target

    # ------------------------------------------------------------ 가로채기

    def handle_interrupts(self, limit: int = 4) -> bool:
        """끼어든 화면이 있으면 닫는다.

        Returns:
            하나라도 처리했으면 True. (원래 하던 일은 그 뒤에 다시 시도해야 한다)
        """
        handled = False
        for _ in range(limit):
            state = self.detect(fresh=True)
            if state is None or not state.interrupt:
                if state is not None:
                    self._interrupt_streak.pop(state.id, None)
                return handled

            streak = self._interrupt_streak.get(state.id, 0) + 1
            self._interrupt_streak[state.id] = streak
            if streak > MAX_INTERRUPT_REPEATS:
                self.ctx.log(
                    f"'{state.name}' 가 {streak}번 연속으로 떠서 포기합니다", level="error"
                )
                return handled

            self.ctx.log(f"끼어든 화면 '{state.name}' 을(를) 처리합니다", level="warn")
            if not self._escape(state):
                return handled
            handled = True
        return handled

    def _escape(self, state: State) -> bool:
        """인터럽트 상황에서 빠져나가는 전이를 실행한다."""
        exits = self.graph.transitions_from(state.id)
        if not exits:
            self.ctx.log(
                f"'{state.name}' 에서 빠져나가는 전이가 없습니다 — 닫는 방법을 등록하세요",
                level="error",
            )
            return False
        transition = min(exits, key=lambda t: t.cost)
        return self._run_transition(transition, state)

    # ------------------------------------------------------------ 이동

    def ensure(self, key: str, timeout_ms: int = 10000) -> bool:
        """목표 상황이 될 때까지 이동한다. 이미 그 상황이면 아무것도 하지 않는다."""
        target = self.resolve(key)
        if target is None:
            self.ctx.log(f"없는 상황입니다: {key}", level="error")
            return False

        deadline = time.perf_counter() + max(0, timeout_ms) / 1000
        while True:
            self.ctx.check_stop()
            self.handle_interrupts()

            current = self.detect(fresh=True)
            if current is target:
                return True

            if current is None:
                self.ctx.log(
                    f"지금 화면을 알 수 없습니다 — '{target.name}' 로 가는 길을 찾지 못했습니다",
                    level="warn",
                )
                if not self._wait_a_moment(deadline):
                    return False
                continue

            path = self.graph.find_path(current.id, target.id)
            if not path:
                self.ctx.log(
                    f"'{current.name}' → '{target.name}' 경로가 없습니다", level="error"
                )
                return False

            self.ctx.log(
                "이동: " + " → ".join(
                    [current.name] + [self._name_of(t.dst) for t in path]
                ),
                level="info",
            )
            for transition in path:
                self.ctx.check_stop()
                if not self._run_transition(transition, current):
                    break
                if self.handle_interrupts():
                    break  # 팝업이 끼어들었으면 경로를 다시 계산한다

            if self.detect(fresh=True) is target:
                return True
            if time.perf_counter() >= deadline:
                self.ctx.log(f"'{target.name}' 로 이동하지 못했습니다 (시간 초과)", level="error")
                return False

    def wait_for(self, key: str, timeout_ms: int = 10000, poll_ms: int = 300) -> bool:
        """이동하지 않고 그 상황이 되기만 기다린다."""
        target = self.resolve(key)
        if target is None:
            self.ctx.log(f"없는 상황입니다: {key}", level="error")
            return False

        deadline = time.perf_counter() + max(0, timeout_ms) / 1000
        while True:
            self.ctx.check_stop()
            if self.detect(fresh=True) is target:
                return True
            if time.perf_counter() >= deadline:
                return False
            self.ctx.sleep(poll_ms, jitter_pct=0)

    # ------------------------------------------------------------ 내부

    def _run_transition(self, transition, from_state: State | None) -> bool:
        source = self._name_of(transition.src)
        destination = self._name_of(transition.dst)
        self.ctx.log(f"전이 실행: {source} → {destination}", level="debug")

        error = run_sequence(transition.actions, self.ctx)
        if error:
            self.ctx.log(f"전이 실패: {error}", level="error")
            return False

        if transition.settle_ms:
            self.ctx.sleep(transition.settle_ms, jitter_pct=0)
        self.ctx.invalidate_frame()
        self._last = Detection(None, 0.0)  # 화면이 바뀌었으니 다시 판정한다
        return True

    def _name_of(self, state_id: str) -> str:
        state = self.graph.state(state_id)
        return state.name if state else "(없는 상황)"

    def _wait_a_moment(self, deadline: float) -> bool:
        if time.perf_counter() >= deadline:
            return False
        self.ctx.sleep(400, jitter_pct=0)
        return True
