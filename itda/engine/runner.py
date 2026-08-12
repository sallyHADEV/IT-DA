"""플로우 실행기.

노드를 순회하며 그 안의 액션을 실행한다. 편집기에서 정한 규칙 — 선/후 딜레이, 재시도,
예외 처리, 분기·반복·서브플로우 — 이 실제로 동작하는 곳이다.

이벤트는 :mod:`itda.core.events` 버스로만 내보낸다. 그래서 데모 재생과 똑같이 캔버스가
켜지고, GUI 쪽 코드는 하나도 바꿀 필요가 없다.
"""

from __future__ import annotations

import random
import threading
import time

from itda.core import registry
from itda.core.events import BUS, FAIL, OK, RUNNING, SKIPPED
from itda.core.model import Flow, Node
from itda.engine.context import ExecutionContext, Stopped
from itda.engine.executors import StopFlow, run_sequence, run_window_op

#: 한 플로우에서 밟을 수 있는 최대 노드 수 (순환 방어)
MAX_STEPS = 10000


class FlowRunner:
    """플로우 하나를 실행한다."""

    def __init__(self, ctx: ExecutionContext, flow: Flow, flow_key: str,
                 depth: int = 0) -> None:
        self.ctx = ctx
        self.flow = flow
        self.flow_key = flow_key
        self.depth = depth
        self.steps = 0
        #: 예외 정책이 "지정 노드로 이동" 일 때 러너 루프가 이어받을 노드
        self._pending: Node | None = None

    # ------------------------------------------------------------ 실행

    def run(self) -> bool:
        """시작 노드부터 끝까지. 성공 여부를 돌려준다."""
        start = self.flow.start_node()
        if start is None:
            self.ctx.log("시작 노드가 없습니다", level="error")
            return False

        self.ctx.flow_key = self.flow_key
        self.ctx.seed_variables(self.flow)
        self.ctx.publish_variables()
        BUS.flow_running.emit(self.flow_key, True)
        self.ctx.log("실행 시작", level="info")

        try:
            return self._walk(start)
        except Stopped:
            self.ctx.log("사용자가 정지했습니다", level="warn")
            return False
        except StopFlow as stop:
            if stop.scope == "all":
                self.ctx.stop()
            self.ctx.log(f"중단: {stop.reason or '중단 액션'}", level="info")
            return True
        finally:
            BUS.flow_running.emit(self.flow_key, False)
            self.ctx.publish_variables()

    def _walk(self, node: Node | None) -> bool:
        while node is not None:
            self.ctx.check_stop()
            self.steps += 1
            if self.steps > MAX_STEPS:
                self.ctx.log(f"{MAX_STEPS}단계를 넘어 중단합니다 (순환일 수 있습니다)",
                             level="error")
                return False

            port = self._run_node(node)

            if self._pending is not None:  # 예외 정책의 '지정 노드로 이동'
                node, self._pending = self._pending, None
                continue
            if port is None:
                return node.type == "end" and node.params.get("result") != "fail"

            following = self._next(node, port)
            if following is None:
                # 이어지는 곳이 없으면 여기서 끝난다. 실패 출구로 나왔다면 실패다.
                return port != "fail"
            node = following
        return True

    def _next(self, node: Node, port: str) -> Node | None:
        edges = self.flow.edges_from(node.id, port)
        if not edges:
            if port == "fail":
                self.ctx.log("실패 출구에 연결이 없어 실행을 멈춥니다", level="warn")
            return None
        edge = edges[0]
        BUS.edge_fired.emit(self.flow_key, edge.id)
        return self.flow.node(edge.dst_node)

    # ------------------------------------------------------------ 노드

    def _run_node(self, node: Node) -> str | None:
        """노드 하나. 나갈 출구 이름을 돌려준다(끝이면 None)."""
        self.ctx.node_title = node.title
        self.ctx.action_title = ""
        BUS.node_status.emit(self.flow_key, node.id, RUNNING)

        spec = registry.node_type(node.type)
        if spec is None:
            BUS.node_status.emit(self.flow_key, node.id, FAIL)
            self.ctx.log(f"알 수 없는 노드 종류: {node.type}", level="error")
            return "fail"

        if node.type == "note":
            BUS.node_status.emit(self.flow_key, node.id, SKIPPED)
            return "ok"

        # 끼어든 화면(팝업)부터 치운다 — 안 그러면 아래 동작이 엉뚱한 곳을 누른다
        self._handle_interrupts()

        if node.required_state and spec.allows_state:
            outcome = self._ensure_state(node)
            if outcome is not None:
                return outcome

        self.ctx.delay_before(node.pre)

        # 입력 권한은 노드 단위로 빌린다 — 클릭과 그 뒤 입력이 다른 플로우에 쪼개지면 안 된다
        if self.ctx.arbiter is not None and node.actions:
            with self.ctx.arbiter.hold(self.flow_key, self.ctx.priority) as granted:
                if not granted:
                    self.ctx.log("입력 권한을 얻지 못했습니다 (다른 플로우가 사용 중)",
                                 level="warn")
                    BUS.node_status.emit(self.flow_key, node.id, FAIL)
                    return "fail"
                # 잠금을 쥔 이름을 알려 둔다 — check_stop 이 이 이름으로 심장박동을 보내
                # 오래 기다리는 노드가 "멈춘 것" 으로 오해받아 잠금을 뺏기지 않게 한다.
                outer_owner = self.ctx.arbiter_owner
                self.ctx.arbiter_owner = self.flow_key
                try:
                    return self._attempt_node(node, spec)
                finally:
                    self.ctx.arbiter_owner = outer_owner
        return self._attempt_node(node, spec)

    def _attempt_node(self, node: Node, spec) -> str | None:
        """재시도까지 포함한 노드 본체 실행."""
        attempts = max(1, node.retry.count + 1)
        last_error = ""
        for attempt in range(attempts):
            self.ctx.check_stop()
            if attempt:
                self.ctx.log(f"재시도 {attempt}/{node.retry.count}", level="warn")
                self.ctx.sleep(node.retry.interval_ms)
            try:
                port, error = self._execute_node(node, spec)
            except (Stopped, StopFlow):
                raise
            except Exception as e:  # 액션 하나 때문에 실행 전체가 죽지 않게
                port, error = None, f"{type(e).__name__}: {e}"
            if error is None:
                self.ctx.delay_after(node.post)
                BUS.node_status.emit(self.flow_key, node.id, OK)
                self.ctx.publish_variables()
                return port
            last_error = error

        return self._handle_error(node, last_error)

    def _handle_interrupts(self) -> None:
        """워처가 켜져 있고 인터럽트 상황이 등록돼 있을 때만 확인한다."""
        machine = self.ctx.states
        if machine is None or not machine.graph.watcher.enabled:
            return
        if not any(s.interrupt for s in machine.graph.states):
            return
        machine.handle_interrupts()

    def _ensure_state(self, node: Node) -> str | None:
        """노드가 요구하는 상황을 맞춘다. 노드를 실행하면 안 될 때 출구 이름을 돌려준다."""
        machine = self.ctx.states
        if machine is None:
            self.ctx.log("상황 머신이 없어 상황 조건을 건너뜁니다", level="warn")
            return None
        if machine.is_in(node.required_state):
            return None

        current = machine.current_name()
        mode = node.on_wrong_state
        self.ctx.log(
            f"필요한 상황 '{node.required_state}' 이 아닙니다 (지금 '{current}')", level="warn"
        )

        match mode:
            case "skip":
                BUS.node_status.emit(self.flow_key, node.id, SKIPPED)
                self.ctx.log("이 노드를 건너뜁니다", level="warn")
                return "ok"
            case "wait":
                if machine.wait_for(node.required_state, node.state_timeout_ms):
                    return None
            case "fail":
                BUS.node_status.emit(self.flow_key, node.id, FAIL)
                return "fail"
            case _:  # navigate
                if machine.ensure(node.required_state, node.state_timeout_ms):
                    return None

        BUS.node_status.emit(self.flow_key, node.id, FAIL)
        self.ctx.log(f"'{node.required_state}' 상황을 만들지 못했습니다", level="error")
        return "fail"

    def _execute_node(self, node: Node, spec) -> tuple[str | None, str | None]:
        """노드 종류별 동작. ``(출구, 오류)`` — 오류가 None 이면 성공."""
        match node.type:
            case "start":
                return "ok", None
            case "end":
                result = node.params.get("result", "success")
                if result == "stop_all":
                    self.ctx.stop()
                return None, None
            case "window":
                outcome = run_window_op(node.params, self.ctx)
                return ("ok", None) if outcome.ok else ("fail", outcome.message)
            case "subflow":
                ok = self._call_subflow(node)
                return ("ok", None) if ok else ("fail", "서브플로우 실패")
            case "state_gate":
                return self._run_state_gate(node)
            case "branch":
                error = self._run_actions(node)
                if error:
                    return "fail", error
                return ("true" if self.ctx.truthy(node.params.get("expr", "")) else "false"), None
            case "switch":
                error = self._run_actions(node)
                if error:
                    return "fail", error
                try:
                    value = str(self.ctx.value(node.params.get("expr", "")))
                except Exception as e:
                    return "fail", f"판정식 오류: {e}"
                cases = [c.strip() for c in str(node.params.get("cases", "")).split(",") if c.strip()]
                return (value if value in cases else "default"), None
            case "loop":
                return self._run_loop(node)
            case _:
                error = self._run_actions(node)
                return ("ok", None) if error is None else ("fail", error)

    def _run_state_gate(self, node: Node) -> tuple[str | None, str | None]:
        machine = self.ctx.states
        params = node.params
        target = params.get("target_state", "")
        if machine is None:
            return "fail", "상황 머신이 연결되지 않았습니다"
        if not target:
            return "fail", "목표 상황이 지정되지 않았습니다"

        timeout = params.get("timeout_ms", 10000)
        match params.get("mode", "navigate"):
            case "wait":
                ok = machine.wait_for(target, timeout)
            case "check":
                ok = machine.is_in(target)
            case _:
                ok = machine.ensure(target, timeout)
        return ("ok", None) if ok else ("fail", f"'{target}' 상황이 아닙니다")

    def _run_loop(self, node: Node) -> tuple[str | None, str | None]:
        params = node.params
        mode = params.get("mode", "count")
        limit = max(1, int(params.get("max_iterations", 1000)))
        count = int(params.get("count", 1))

        iteration = 0
        while iteration < limit:
            self.ctx.check_stop()
            if mode == "count" and iteration >= count:
                break
            if mode == "while" and not self.ctx.truthy(params.get("expr", "")):
                break
            if mode == "until" and iteration and self.ctx.truthy(params.get("expr", "")):
                break

            error = self._run_actions(node)
            if error:
                return "fail", error
            iteration += 1
            if params.get("interval_ms"):
                self.ctx.sleep(params["interval_ms"])

        if iteration >= limit:
            self.ctx.log(f"최대 반복({limit})에 도달했습니다", level="warn")
        return "ok", None

    def _run_actions(self, node: Node) -> str | None:
        """노드 안의 액션 시퀀스. 오류 메시지를 돌려준다(성공이면 None)."""
        return run_sequence(node.actions, self.ctx, self.flow_key, node.id)

    def _call_subflow(self, node: Node) -> bool:
        if self.ctx.run_flow is None:
            return False
        args = {}
        for line in str(node.params.get("args", "")).splitlines():
            if "=" in line:
                name, _, raw = line.partition("=")
                args[name.strip()] = self.ctx.text(raw.strip())
        return bool(
            self.ctx.run_flow(
                node.params.get("flow", ""), args, node.params.get("wait", True),
                node.params.get("priority", 0),
            )
        )

    # ------------------------------------------------------------ 예외 처리

    def _handle_error(self, node: Node, message: str) -> str | None:
        """노드의 예외 정책대로 처리하고 다음 출구를 정한다."""
        policy = node.on_error
        self.ctx.log(policy.message or message, level="error")
        BUS.node_status.emit(self.flow_key, node.id, FAIL)

        if policy.capture_screenshot:
            self._capture_error_shot(node)

        match policy.mode:
            case "continue":
                self.ctx.log("무시하고 계속합니다", level="warn")
                return "ok"
            case "goto":
                target = self.flow.node(policy.target)
                if target is None:
                    self.ctx.log("이동할 노드를 찾지 못했습니다", level="error")
                    return None
                self.ctx.log(f"'{target.title}' 로 이동해 이어갑니다", level="warn")
                self._pending = target
                return None
            case "stop":
                raise StopFlow("flow", message)
            case "raise_up":
                raise StopFlow("flow", message)
            case _:
                return "fail"

    def _capture_error_shot(self, node: Node) -> None:
        try:
            from itda.vision import capture

            base = self.ctx.project.path
            if base is None:
                return
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = base / "captures" / f"error_{stamp}.png"
            capture.save_pixmap(capture.grab_all(), path)
            self.ctx.log(f"오류 화면 저장: {path}", level="warn")
        except Exception:
            pass


# ---------------------------------------------------------------- 여러 플로우


class Engine:
    """프로젝트 하나를 실행한다. 서브플로우 호출과 정지 신호를 관리한다.

    Args:
        sender: 입력 주입기. 기본은 아무것도 하지 않는 :class:`DryRunSender`.
        arbiter: 입력 장치 중재기. 비동기로 띄운 플로우와 입력이 섞이지 않게 한다.
        sender_factory: 비동기 플로우에 줄 주입기를 만드는 함수. 없으면 안전한 기본값.
    """

    def __init__(
        self,
        project,
        sender=None,
        rng: random.Random | None = None,
        arbiter=None,
        sender_factory=None,
    ) -> None:
        from itda.engine.state_machine import StateMachine

        self.project = project
        self.stop_flag = {"stop": False}
        self.arbiter = arbiter
        self.sender_factory = sender_factory or _default_sender
        self.ctx = ExecutionContext(
            project=project,
            sender=sender or _default_sender(),
            rng=rng or random.Random(),
            stop_flag=self.stop_flag,
            arbiter=arbiter,
        )
        self.ctx.run_flow = self._run_subflow
        self.ctx.states = StateMachine(project.states, self.ctx)
        self._depth = 0
        #: 비동기로 띄운 자식 실행들 — 정지할 때 함께 멈춘다
        self._children: list[tuple[str, Engine, threading.Thread]] = []
        self._children_lock = threading.Lock()

    def run(self, flow_key: str) -> bool:
        flow = self.project.flow(flow_key)
        if flow is None:
            BUS.log(f"플로우를 찾을 수 없습니다: {flow_key}", level="error")
            return False
        if self.stop_flag.get("stop"):
            BUS.log("실행 전에 이미 정지 요청이 들어왔습니다", level="warn")
            return False
        return FlowRunner(self.ctx, flow, flow_key).run()

    def _prune_children(self) -> None:
        """완료된 비동기 스레드 슬롯을 정리한다."""
        with self._children_lock:
            self._children = [item for item in self._children if item[2].is_alive()]

    def stop(self) -> None:
        self.stop_flag["stop"] = True
        with self._children_lock:
            children_copy = list(self._children)
        for key, child, _thread in children_copy:
            child.stop()
            BUS.log(f"비동기 플로우 '{key}' 에도 정지를 전달했습니다", level="debug")

    def join_children(self, timeout: float = 5.0) -> bool:
        """비동기로 띄운 플로우들이 끝날 때까지 기다린다."""
        import time as _time

        deadline = _time.perf_counter() + timeout
        with self._children_lock:
            threads = [item[2] for item in self._children]
        for thread in threads:
            thread.join(max(0.0, deadline - _time.perf_counter()))
        return not self.children_running()

    def children_running(self) -> bool:
        with self._children_lock:
            return any(thread.is_alive() for _k, _c, thread in self._children)

    def _run_subflow(
        self, flow_key: str, args: dict, wait: bool = True, priority: int = 0
    ) -> bool:
        from itda.core.project import MAX_SUBFLOW_DEPTH

        flow = self.project.flow(flow_key)
        if flow is None:
            BUS.log(f"서브플로우를 찾을 수 없습니다: {flow_key}", level="error")
            return False
        if self._depth >= MAX_SUBFLOW_DEPTH:
            BUS.log(f"플로우 호출이 {MAX_SUBFLOW_DEPTH}단계를 넘었습니다", level="error")
            return False

        if not wait:
            return self._spawn_async(flow_key, args, priority)

        for name, value in (args or {}).items():
            self.ctx.variables.set(name, value)

        outer_key, outer_title = self.ctx.flow_key, self.ctx.node_title
        self._depth += 1
        try:
            return FlowRunner(self.ctx, flow, flow_key, self._depth).run()
        finally:
            self._depth -= 1
            self.ctx.flow_key, self.ctx.node_title = outer_key, outer_title

    def _spawn_async(self, flow_key: str, args: dict, priority: int) -> bool:
        """플로우를 배경에서 띄우고 곧바로 돌아온다.

        자기 엔진과 변수 공간을 갖는다 — 부모와 변수를 공유하면 서로 덮어써서 원인을 못 찾는
        버그가 난다. 대신 **입력 장치 중재기는 공유**해서 마우스·키보드가 섞이지 않게 한다.
        """
        child = Engine(
            self.project,
            sender=self.sender_factory(),
            arbiter=self.arbiter,
            sender_factory=self.sender_factory,
        )
        child.ctx.priority = priority
        # 자식은 백그라운드 스레드에서 실행되므로 GUI tick을 공유하지 않는다.
        child.ctx.tick = None
        for name, value in (args or {}).items():
            child.ctx.variables.set(name, value, "flow")

        def run() -> None:
            try:
                child.run(flow_key)
            except Exception as e:  # 배경 스레드가 조용히 죽지 않게
                BUS.log(f"비동기 플로우 '{flow_key}' 오류: {type(e).__name__}: {e}",
                        level="error")
            finally:
                if self.arbiter is not None:
                    self.arbiter.release(flow_key)

        thread = threading.Thread(target=run, name=f"itda-async-{flow_key}", daemon=True)
        with self._children_lock:
            self._children.append((flow_key, child, thread))
        thread.start()
        BUS.log(f"플로우 '{flow_key}' 를 배경에서 시작했습니다 (우선순위 {priority})",
                level="info")
        return True


def _default_sender():
    """기본은 안전한 쪽 — 명시적으로 실주입기를 넣어야 실제로 움직인다."""
    from itda.engine.input import DryRunSender

    return DryRunSender()
