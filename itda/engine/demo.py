"""데모 재생기.

실제로 마우스를 움직이지 않고, 플로우를 따라가며 이벤트만 흘린다. 목적은 두 가지다.

1. 사용자가 만든 플로우가 어떤 순서로 도는지 눈으로 확인한다(연결 실수 찾기).
2. 실행 시각화 경로(이벤트 버스 → 캔버스 하이라이트 · 로그 · 변수 워치)를 2차 엔진 없이
   완성해 둔다. 2차 엔진은 여기와 똑같은 이벤트를 발행하기만 하면 된다.
"""

from __future__ import annotations

import random

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from itda.core import registry
from itda.core.events import BUS, FAIL, OK, RUNNING, SKIPPED
from itda.core.model import Flow, Node
from itda.engine.input import planner, touch
from itda.engine.input.planner import resolve_human
from itda.engine.input.steps import summarize, total_duration_ms

MAX_STEPS = 300


class DemoRunner(QObject):
    """플로우를 한 노드씩 훑으며 이벤트를 발행한다."""

    finished = pyqtSignal()
    running_changed = pyqtSignal(bool)

    def __init__(self, project, flow: Flow, flow_key: str, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.flow = flow
        self.flow_key = flow_key
        self.step_ms = 700
        self.rng = random.Random()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._step)
        self._current: Node | None = None
        self._steps = 0
        self._paused = False
        self._variables: dict[str, object] = {}
        #: 객체별 '최근 찾은 위치'. 2차 엔진도 같은 캐시를 갖는다.
        self._found: dict[str, tuple[int, int]] = {}
        self._found_point = (640, 480)
        #: 계획 미리보기용 가상 커서 위치
        self._cursor = (0, 0)

    # ------------------------------------------------------------ 제어

    @property
    def is_running(self) -> bool:
        return self._current is not None and not self._paused

    def start(self) -> bool:
        start = self.flow.start_node()
        if start is None:
            BUS.log("시작 노드가 없어 데모를 돌릴 수 없습니다", level="error", flow=self.flow_key)
            return False

        self._steps = 0
        self._paused = False
        self._found.clear()
        self._variables = {
            v.name: v.default for v in (*self.project.settings.globals, *self.flow.variables) if v.name
        }
        self._current = start
        BUS.flow_running.emit(self.flow_key, True)
        BUS.log("데모 재생 시작 (실제 입력은 나가지 않습니다)", level="info", flow=self.flow_key)
        self._announce_state()
        self.running_changed.emit(True)
        self._timer.start(0)
        return True

    def pause(self) -> None:
        if self._current is None:
            return
        self._paused = not self._paused
        if self._paused:
            self._timer.stop()
            BUS.log("일시정지", level="warn", flow=self.flow_key)
        else:
            BUS.log("계속", level="info", flow=self.flow_key)
            self._timer.start(self.step_ms)
        self.running_changed.emit(not self._paused)

    def stop(self, reason: str = "정지") -> None:
        if self._current is None and not self._paused:
            return
        self._timer.stop()
        self._current = None
        self._paused = False
        BUS.flow_running.emit(self.flow_key, False)
        BUS.log(reason, level="info", flow=self.flow_key)
        self.running_changed.emit(False)
        self.finished.emit()

    # ------------------------------------------------------------ 진행

    def _step(self) -> None:
        node = self._current
        if node is None:
            return

        self._steps += 1
        if self._steps > MAX_STEPS:
            BUS.log(f"{MAX_STEPS}단계를 넘어 데모를 멈춥니다 (순환일 수 있습니다)",
                    level="warn", flow=self.flow_key)
            self.stop("데모 종료")
            return

        if node.breakpoint:
            BUS.node_status.emit(self.flow_key, node.id, "break")
            BUS.log("중단점에서 멈춤 — 계속하려면 재생을 누르세요",
                    level="warn", flow=self.flow_key, node=node.title)
            self._paused = True
            self.running_changed.emit(False)
            node.breakpoint = False  # 다시 누르면 지나가도록
            return

        BUS.node_status.emit(self.flow_key, node.id, RUNNING)

        spec = registry.node_type(node.type)
        if node.required_state and spec is not None and spec.allows_state:
            BUS.log(
                f"'{node.required_state}' 상황이 필요합니다 → 상황 확인/이동",
                level="info", flow=self.flow_key, node=node.title,
            )
            BUS.state_detected.emit("", node.required_state)

        for action in node.actions:
            if not action.enabled:
                BUS.action_status.emit(self.flow_key, node.id, action.id, SKIPPED)
                continue
            BUS.action_status.emit(self.flow_key, node.id, action.id, OK)
            BUS.log(
                registry.action_summary(action.type, action.params),
                level="debug", flow=self.flow_key, node=node.title,
                action=action.title or action.type,
            )
            self._simulate_lookup(node, action)
            self._preview_input(node, action)
            if action.out_var:
                self._variables[action.out_var] = self._fake_result(action.type)
                if action.type in ("image_search", "wait_image"):
                    x, y = self._found_point
                    self._variables[f"{action.out_var}_x"] = x
                    self._variables[f"{action.out_var}_y"] = y
                    self._variables[f"{action.out_var}_ok"] = True
            if action.type in ("set_var", "calc") and action.params.get("name"):
                self._variables[action.params["name"]] = action.params.get("value", "…")

        self._describe_node(node)
        BUS.variables.emit(self.flow_key, dict(self._variables))
        BUS.node_status.emit(self.flow_key, node.id, OK)

        if node.type == "end":
            BUS.log("플로우 종료 노드에 도달", level="info", flow=self.flow_key, node=node.title)
            self.stop("데모 종료")
            return

        nxt = self._next_node(node)
        if nxt is None:
            BUS.node_status.emit(self.flow_key, node.id, FAIL if node.type != "note" else OK)
            BUS.log("다음으로 이어지는 연결이 없습니다", level="warn",
                    flow=self.flow_key, node=node.title)
            self.stop("데모 종료")
            return

        self._current = nxt
        self._timer.start(self.step_ms)

    def _next_node(self, node: Node) -> Node | None:
        """나가는 연결 중 하나를 고른다. 분기는 첫 출구를 쓴다."""
        spec = registry.node_type(node.type)
        ports = spec.ports_out(node.params) if spec else ["ok"]
        for port in ports:
            edges = self.flow.edges_from(node.id, port)
            if edges:
                edge = edges[0]
                BUS.edge_fired.emit(self.flow_key, edge.id)
                return self.flow.node(edge.dst_node)
        edges = self.flow.edges_from(node.id)
        if edges:
            BUS.edge_fired.emit(self.flow_key, edges[0].id)
            return self.flow.node(edges[0].dst_node)
        return None

    def _simulate_lookup(self, node: Node, action) -> None:
        """객체 위치를 새로 찾는지, 최근 찾은 위치를 재사용하는지 로그로 보여 준다.

        실제 매칭은 2차 엔진의 일이지만, 규칙 자체는 여기서 그대로 흉내 내어 사용자가
        플로우를 짤 때 "여기서 또 찾는구나" 를 눈으로 확인할 수 있게 한다.
        """
        params = action.params or {}

        if action.type in ("image_search", "wait_image"):
            for name in params.get("objects") or []:
                if action.type == "wait_image" and not params.get("remember_position", True):
                    continue
                self._found[name] = self._found_point
                BUS.log(f"'{name}' 위치를 기억했습니다 {self._found_point}",
                        level="debug", flow=self.flow_key, node=node.title)
            return

        if params.get("target_mode") != "object":
            return
        name = params.get("object") or ""
        if not name:
            return
        lookup = params.get("object_lookup", "cache_or_search")
        known = self._found.get(name)
        if lookup == "always":
            self._found[name] = self._found_point
            BUS.log(f"'{name}' 을(를) 다시 찾습니다 (항상 새로 찾기)",
                    level="debug", flow=self.flow_key, node=node.title)
        elif known is not None:
            BUS.log(f"'{name}' 의 최근 찾은 위치 {known} 를 재사용합니다",
                    level="debug", flow=self.flow_key, node=node.title)
        elif lookup == "cache_only":
            BUS.log(f"'{name}' 의 최근 위치가 없습니다 — 먼저 '이미지 찾기'가 필요합니다",
                    level="warn", flow=self.flow_key, node=node.title)
        else:
            self._found[name] = self._found_point
            BUS.log(f"'{name}' 의 최근 위치가 없어 지금 찾습니다",
                    level="debug", flow=self.flow_key, node=node.title)

    def _describe_node(self, node: Node) -> None:
        """액션을 담지 않는 노드(창 맞추기·플로우 호출 등)가 무엇을 할지 알린다."""
        spec = registry.node_type(node.type)
        if spec is None or spec.allows_actions:
            return
        params = node.params or {}
        match node.type:
            case "window":
                from itda.core.window_spec import summarize as window_summary

                BUS.log(f"{window_summary(params)} (데모라 실제 창은 옮기지 않습니다)",
                        level="debug", flow=self.flow_key, node=node.title)
            case "subflow":
                BUS.log(f"플로우 '{params.get('flow') or '?'}' 호출",
                        level="debug", flow=self.flow_key, node=node.title)
            case "state_gate":
                BUS.log(f"'{params.get('target_state') or '?'}' 상황으로 이동",
                        level="debug", flow=self.flow_key, node=node.title)

    def _preview_input(self, node: Node, action) -> None:
        """입력 액션이 실제로 어떻게 움직일지 계획해 로그로 보여 준다.

        계획만 만들고 주입하지 않는다(:class:`~itda.engine.input.DryRunSender` 와 같은 원리).
        사람처럼 움직이기 설정이 실제로 어떤 궤적·시간을 만드는지 편집 중에 확인할 수 있다.
        """
        try:
            steps = self._plan_for(action)
        except Exception:  # 미리보기 하나 때문에 데모가 멈추면 안 된다
            return
        if not steps:
            return
        moves = [s for s in steps if s.kind in ("move", "touch")]
        if moves:
            self._cursor = (moves[-1].x, moves[-1].y)
        total = total_duration_ms(steps)
        BUS.log(
            f"계획 {len(steps)}단계 · 약 {total:.0f}ms · {summarize(steps, 3)}",
            level="debug", flow=self.flow_key, node=node.title,
            action=action.title or action.type,
        )

    def _plan_for(self, action) -> list:
        """액션 하나의 입력 계획. 입력 계열이 아니면 빈 목록."""
        params = action.params or {}
        human = resolve_human(self.project.settings.human, params.get("humanize", "inherit"))
        timing = self.project.settings.timing
        rng = self.rng
        target = self._target_point(params)

        match action.type:
            case "click":
                return planner.plan_click(
                    target, start=self._cursor, button=params.get("button", "left"),
                    click_type=params.get("click_type", "single"), human=human,
                    timing=timing, rng=rng, move_first=params.get("move_first", True),
                )
            case "move":
                return planner.plan_move(
                    self._cursor, target, human, timing,
                    duration_ms=params.get("duration_ms") or None, rng=rng,
                )
            case "drag":
                start = tuple(params.get("from_point") or [0, 0])
                end = tuple(params.get("to_point") or [0, 0])
                return planner.plan_drag(
                    start, end, button=params.get("button", "left"),
                    duration_ms=params.get("duration_ms", 300), human=human,
                    timing=timing, rng=rng,
                )
            case "scroll":
                return planner.plan_scroll(params.get("amount", 0), target, human, rng)
            case "key_press":
                if not params.get("keys"):
                    return []
                return planner.plan_key(
                    params["keys"], action=params.get("action", "tap"),
                    repeat=params.get("repeat", 1), human=human, rng=rng,
                )
            case "type_text":
                return planner.plan_text(
                    params.get("text", ""), interval_ms=params.get("interval_ms", 30),
                    human=human, rng=rng,
                )
            case "touch_point":
                return touch.plan_tap([target], hold_ms=params.get("hold_ms", 80))
            case "touch_multi":
                points = [tuple(p) for p in (params.get("points") or [])]
                if params.get("gesture") in ("pinch_in", "pinch_out") and len(points) >= 2:
                    center = (
                        (points[0][0] + points[1][0]) // 2,
                        (points[0][1] + points[1][1]) // 2,
                    )
                    distance = params.get("distance", 80)
                    inward = params.get("gesture") == "pinch_in"
                    return touch.plan_pinch(
                        center,
                        start_distance=distance if not inward else distance * 2,
                        end_distance=distance * 2 if not inward else distance // 2,
                    )
                return touch.plan_tap(points, hold_ms=params.get("hold_ms", 120))
            case "touch_drag":
                return touch.plan_touch_drag(
                    [tuple(p) for p in (params.get("path") or [])],
                    duration_ms=params.get("duration_ms", 400),
                    hold_start_ms=params.get("hold_start_ms", 80),
                )
            case _:
                return []

    def _target_point(self, params: dict) -> tuple[int, int]:
        """계획용 목표 좌표. 객체 참조면 '최근 찾은 위치' 를 쓴다."""
        mode = params.get("target_mode", "fixed")
        if mode == "object":
            return self._found.get(params.get("object", ""), self._found_point)
        if mode == "current":
            return self._cursor
        point = params.get("point") or [0, 0]
        return (int(point[0]), int(point[1]))

    def _announce_state(self) -> None:
        states = self.project.states.states
        if states:
            first = states[0]
            BUS.state_detected.emit(first.id, first.name)
        else:
            BUS.state_detected.emit("", self.project.states.watcher.unknown_name)

    def _fake_result(self, action_type: str):
        """데모용 그럴듯한 결과값."""
        match action_type:
            case "image_search":
                return list(self._found_point)  # 찾기의 결과는 좌표 [x, y]
            case "wait_image" | "pixel_check":
                return True
            case "ocr_read":
                return "123"
            case "screenshot":
                return "captures/demo.png"
            case _:
                return self.rng.randint(1, 100)
