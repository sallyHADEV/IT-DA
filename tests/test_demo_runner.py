"""데모 재생기 테스트.

이벤트 버스 → 캔버스 시각화 경로가 실제로 이어지는지 확인한다.
2차 실행 엔진은 여기와 같은 이벤트만 발행하면 되므로, 이 테스트가 그 계약서다.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF

from itda.core.events import BUS, OK, RUNNING
from itda.core.model import Action, VarDecl
from itda.engine.demo import DemoRunner
from itda.gui.commands import AddEdgeCommand


@pytest.fixture
def demo_flow(scene):
    """시작 → 동작 → 종료 로 이어지는 플로우."""
    flow = scene.flow
    start = flow.start_node()
    work = flow.nodes[1]
    work.title = "로그인"
    work.actions.append(Action(type="click", params={"point": [10, 20]}))
    work.actions.append(Action(type="ocr_read", out_var="읽은값"))
    end = scene.add_node("end", QPointF(400, 0))

    edge = flow.connect(work.id, "ok", end.id)
    flow.edges.remove(edge)
    scene.undo_stack.push(AddEdgeCommand(scene, edge))
    return flow, start, work, end


@pytest.fixture
def collector(qapp):
    """버스 이벤트를 모으는 수집기."""

    class Collector:
        def __init__(self):
            self.node_status = []
            self.edges = []
            self.logs = []
            self.variables = []
            self.running = []

        def connect(self):
            BUS.node_status.connect(self._node)
            BUS.edge_fired.connect(self._edge)
            BUS.logged.connect(self._log)
            BUS.variables.connect(self._vars)
            BUS.flow_running.connect(self._running)

        def disconnect(self):
            for signal, slot in (
                (BUS.node_status, self._node),
                (BUS.edge_fired, self._edge),
                (BUS.logged, self._log),
                (BUS.variables, self._vars),
                (BUS.flow_running, self._running),
            ):
                signal.disconnect(slot)

        def _node(self, flow, node_id, status):
            self.node_status.append((node_id, status))

        def _edge(self, flow, edge_id):
            self.edges.append(edge_id)

        def _log(self, record):
            self.logs.append(record)

        def _vars(self, flow, values):
            self.variables.append(dict(values))

        def _running(self, flow, running):
            self.running.append(running)

    c = Collector()
    c.connect()
    yield c
    c.disconnect()


def run_to_completion(runner: DemoRunner, qapp, max_steps: int = 40) -> None:
    """타이머를 기다리지 않고 단계를 직접 돌린다."""
    runner.step_ms = 0
    runner.start()
    for _ in range(max_steps):
        if runner._current is None:
            break
        runner._step()
        qapp.processEvents()


def test_demo_walks_from_start_to_end(qapp, scene, demo_flow, collector):
    flow, start, work, end = demo_flow
    runner = DemoRunner(scene.project, flow, "main")

    run_to_completion(runner, qapp)

    visited = [node_id for node_id, status in collector.node_status if status == RUNNING]
    assert visited == [start.id, work.id, end.id]


def test_each_node_reports_running_then_ok(qapp, scene, demo_flow, collector):
    flow, _start, work, _end = demo_flow
    runner = DemoRunner(scene.project, flow, "main")

    run_to_completion(runner, qapp)

    statuses = [s for node_id, s in collector.node_status if node_id == work.id]
    assert statuses == [RUNNING, OK]


def test_edges_fire_in_order(qapp, scene, demo_flow, collector):
    flow, _start, _work, _end = demo_flow
    runner = DemoRunner(scene.project, flow, "main")

    run_to_completion(runner, qapp)

    assert len(collector.edges) == 2
    assert collector.edges == [e.id for e in flow.edges]


def test_canvas_highlights_follow_events(qapp, scene, demo_flow):
    """씬이 실제로 이벤트를 받아 노드 색을 바꾸는지 (시각화 경로 전체)."""
    flow, _start, work, _end = demo_flow
    scene.clear_statuses()

    BUS.node_status.connect(
        lambda key, node_id, status: scene.set_node_status(node_id, status)
    )
    BUS.node_status.emit("main", work.id, RUNNING)
    qapp.processEvents()

    assert scene.node_items[work.id].status == RUNNING


def test_actions_are_logged_with_summary(qapp, scene, demo_flow, collector):
    flow, _start, work, _end = demo_flow
    runner = DemoRunner(scene.project, flow, "main")

    run_to_completion(runner, qapp)

    messages = [r.message for r in collector.logs]
    assert any("클릭" in m for m in messages)
    assert any("OCR" in m for m in messages)


def test_disabled_actions_are_skipped_in_log(qapp, scene, demo_flow, collector):
    flow, _start, work, _end = demo_flow
    work.actions[0].enabled = False
    runner = DemoRunner(scene.project, flow, "main")

    run_to_completion(runner, qapp)

    assert not any("클릭" in r.message for r in collector.logs)


def test_out_var_appears_in_variable_watch(qapp, scene, demo_flow, collector):
    flow, _start, _work, _end = demo_flow
    runner = DemoRunner(scene.project, flow, "main")

    run_to_completion(runner, qapp)

    assert collector.variables
    assert "읽은값" in collector.variables[-1]


def test_declared_variables_are_seeded(qapp, scene, demo_flow, collector):
    flow, _start, _work, _end = demo_flow
    flow.variables.append(VarDecl(name="시도횟수", type="int", default="3"))
    runner = DemoRunner(scene.project, flow, "main")

    run_to_completion(runner, qapp)

    assert "시도횟수" in collector.variables[0]


def test_required_state_is_announced(qapp, scene, demo_flow, collector):
    flow, _start, work, _end = demo_flow
    work.required_state = "설정창"
    runner = DemoRunner(scene.project, flow, "main")

    run_to_completion(runner, qapp)

    assert any("설정창" in r.message for r in collector.logs)


def test_breakpoint_pauses_run(qapp, scene, demo_flow, collector):
    flow, _start, work, _end = demo_flow
    work.breakpoint = True
    runner = DemoRunner(scene.project, flow, "main")
    runner.step_ms = 0

    runner.start()
    runner._step()  # 시작 노드
    runner._step()  # 중단점 노드에서 멈춤

    assert runner._paused
    assert any("중단점" in r.message for r in collector.logs)
    assert ("break" in [s for _n, s in collector.node_status])


def test_flow_without_start_node_refuses(qapp, scene, collector):
    flow = scene.flow
    start = flow.start_node()
    flow.nodes.remove(start)
    runner = DemoRunner(scene.project, flow, "main")

    assert runner.start() is False
    assert any("시작 노드가 없어" in r.message for r in collector.logs)


def test_running_flag_toggles(qapp, scene, demo_flow, collector):
    flow, *_ = demo_flow
    runner = DemoRunner(scene.project, flow, "main")

    run_to_completion(runner, qapp)

    assert collector.running[0] is True
    assert collector.running[-1] is False


def test_dead_end_stops_with_warning(qapp, scene, collector):
    """연결이 끊긴 곳에서 멈추고 경고를 남긴다 — 플로우 실수를 찾는 용도."""
    flow = scene.flow
    runner = DemoRunner(scene.project, flow, "main")

    run_to_completion(runner, qapp)

    assert any("이어지는 연결이 없습니다" in r.message for r in collector.logs)


def test_cycle_is_capped(qapp, scene, collector):
    """되돌아오는 연결이 있어도 무한히 돌지 않는다."""
    flow = scene.flow
    start = flow.start_node()
    work = flow.nodes[1]
    edge = flow.connect(work.id, "ok", start.id)
    flow.edges.remove(edge)
    scene.undo_stack.push(AddEdgeCommand(scene, edge))

    runner = DemoRunner(scene.project, flow, "main")
    run_to_completion(runner, qapp, max_steps=500)

    assert runner._current is None
    assert any("순환일 수 있습니다" in r.message for r in collector.logs)


def test_image_search_stores_coordinates(qapp, scene, collector):
    """'이미지 찾기' 의 결과는 좌표다 — 변수와 파생 변수(_x/_y/_ok)에 담긴다."""
    flow = scene.flow
    node = flow.nodes[1]
    node.actions.append(
        Action(type="image_search", out_var="로그인위치",
               params={"objects": ["로그인_버튼"]})
    )
    runner = DemoRunner(scene.project, flow, "main")

    run_to_completion(runner, qapp)

    values = collector.variables[-1]
    assert values["로그인위치"] == [640, 480]
    assert values["로그인위치_x"] == 640
    assert values["로그인위치_y"] == 480
    assert values["로그인위치_ok"] is True


def test_click_reuses_position_found_earlier(qapp, scene, collector):
    """찾기 → 클릭 순서면 클릭은 다시 찾지 않는다 (기본값)."""
    node = scene.flow.nodes[1]
    node.actions.append(Action(type="image_search", params={"objects": ["로그인_버튼"]}))
    node.actions.append(
        Action(type="click", params={"target_mode": "object", "object": "로그인_버튼",
                                     "object_lookup": "cache_or_search"})
    )
    runner = DemoRunner(scene.project, scene.flow, "main")

    run_to_completion(runner, qapp)

    messages = [r.message for r in collector.logs]
    assert any("재사용" in m for m in messages)
    assert not any("다시 찾습니다" in m for m in messages)


def test_click_without_earlier_search_finds_now(qapp, scene, collector):
    """찾기 없이 클릭만 두어도 동작한다 — 그 자리에서 찾는다."""
    node = scene.flow.nodes[1]
    node.actions.append(
        Action(type="click", params={"target_mode": "object", "object": "확인_버튼",
                                     "object_lookup": "cache_or_search"})
    )
    runner = DemoRunner(scene.project, scene.flow, "main")

    run_to_completion(runner, qapp)

    assert any("지금 찾습니다" in r.message for r in collector.logs)


def test_always_lookup_searches_again(qapp, scene, collector):
    node = scene.flow.nodes[1]
    node.actions.append(Action(type="image_search", params={"objects": ["목록_항목"]}))
    node.actions.append(
        Action(type="click", params={"target_mode": "object", "object": "목록_항목",
                                     "object_lookup": "always"})
    )
    runner = DemoRunner(scene.project, scene.flow, "main")

    run_to_completion(runner, qapp)

    assert any("다시 찾습니다" in r.message for r in collector.logs)


def test_cache_only_warns_when_nothing_found_yet(qapp, scene, collector):
    node = scene.flow.nodes[1]
    node.actions.append(
        Action(type="click", params={"target_mode": "object", "object": "없던_버튼",
                                     "object_lookup": "cache_only"})
    )
    runner = DemoRunner(scene.project, scene.flow, "main")

    run_to_completion(runner, qapp)

    warnings = [r for r in collector.logs if r.level == "warn"]
    assert any("최근 위치가 없습니다" in r.message for r in warnings)


def test_wait_image_can_skip_remembering_position(qapp, scene, collector):
    """대기는 좌표가 목적이 아니므로 기억을 끌 수 있다."""
    node = scene.flow.nodes[1]
    node.actions.append(
        Action(type="wait_image",
               params={"objects": ["로딩표시"], "until": "appear", "remember_position": False})
    )
    runner = DemoRunner(scene.project, scene.flow, "main")

    run_to_completion(runner, qapp)

    assert not any("위치를 기억했습니다" in r.message for r in collector.logs)


def test_demo_previews_the_real_input_plan(qapp, scene, collector):
    """데모가 실제 입력 계획(궤적·시간)을 만들어 보여 준다 — 마우스는 움직이지 않는다."""
    node = scene.flow.nodes[1]
    node.actions.append(
        Action(type="click", params={"target_mode": "fixed", "point": [800, 600]})
    )
    runner = DemoRunner(scene.project, scene.flow, "main")

    run_to_completion(runner, qapp)

    plans = [r.message for r in collector.logs if "계획" in r.message and "단계" in r.message]
    assert plans, "입력 계획 미리보기가 로그에 없다"
    assert "이동" in plans[0]


def test_plan_preview_follows_the_humanize_profile(qapp, scene):
    """설정을 끄면 계획 단계 수가 줄어든다(직선·일정 속도)."""
    node = scene.flow.nodes[1]
    node.actions.append(
        Action(type="type_text", params={"text": "안녕하세요", "interval_ms": 30})
    )
    runner = DemoRunner(scene.project, scene.flow, "main")

    scene.project.settings.human.enabled = True
    humanized = runner._plan_for(node.actions[0])
    scene.project.settings.human.enabled = False
    mechanical = runner._plan_for(node.actions[0])

    assert len({s.delay_ms for s in humanized}) > 1
    assert len({s.delay_ms for s in mechanical}) == 1


def test_plan_preview_uses_the_found_position_for_object_targets(qapp, scene):
    node = scene.flow.nodes[1]
    node.actions.append(Action(type="image_search", params={"objects": ["버튼"]}))
    node.actions.append(
        Action(type="click", params={"target_mode": "object", "object": "버튼"})
    )
    runner = DemoRunner(scene.project, scene.flow, "main")
    runner._found["버튼"] = (321, 654)

    steps = runner._plan_for(node.actions[1])
    last_move = [s for s in steps if s.kind == "move"][-1]

    assert abs(last_move.x - 321) <= 5 and abs(last_move.y - 654) <= 5


def test_plan_preview_never_raises_on_broken_params(qapp, scene):
    node = scene.flow.nodes[1]
    node.actions.append(Action(type="key_press", params={"keys": "없는키+조합"}))
    runner = DemoRunner(scene.project, scene.flow, "main")

    runner._preview_input(node, node.actions[0])  # 예외 없이 지나가야 한다


def test_stop_clears_state(qapp, scene, demo_flow):
    flow, *_ = demo_flow
    runner = DemoRunner(scene.project, flow, "main")
    runner.step_ms = 0
    runner.start()

    runner.stop()

    assert runner._current is None
    assert runner.is_running is False
