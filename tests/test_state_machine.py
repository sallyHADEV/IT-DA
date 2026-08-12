"""상황 인식 · 이동 · 자가 복구 테스트.

화면을 합성 이미지로 갈아 끼워 "지금 어떤 화면인가" 를 만들어 낸다.
전이 동작은 DryRunSender 로 기록만 한다.
"""

from __future__ import annotations

import numpy as np
import pytest

from itda.core.model import Action, Condition, Node, State, TargetObject, Transition
from itda.engine.context import ExecutionContext
from itda.engine.input import DryRunSender
from itda.engine.runner import Engine
from itda.engine.state_machine import StateMachine, evaluate


class FakeScreen:
    """지금 화면이 무엇인지 테스트가 직접 정한다."""

    def __init__(self) -> None:
        self.visible: set[str] = set()

    def install(self, monkeypatch, machine_ctx: ExecutionContext) -> None:
        def find_object(_self, names, **kwargs):
            from itda.vision.matcher import Match

            for name in names:
                if name in self.visible:
                    return Match(10, 10, 20, 20, 0.99)
            return None

        monkeypatch.setattr(ExecutionContext, "find_object", find_object)
        monkeypatch.setattr(
            ExecutionContext, "screen",
            lambda _self, fresh=False: np.zeros((100, 100, 3), dtype=np.uint8),
        )


@pytest.fixture
def screen():
    return FakeScreen()


@pytest.fixture
def engine(project, monkeypatch, screen):
    e = Engine(project, sender=DryRunSender())
    project.settings.timing.default_pre_ms = 0
    project.settings.timing.default_post_ms = 0
    project.settings.human.enabled = False
    screen.install(monkeypatch, e.ctx)
    return e


def visible_when(object_name: str) -> Condition:
    return Condition(op="and", items=[
        Condition(type="object_visible", params={"object": object_name})
    ])


def add_state(project, name: str, marker: str, **kwargs) -> State:
    state = State(name=name, condition=visible_when(marker), **kwargs)
    project.states.states.append(state)
    project.objects.objects.append(TargetObject(name=marker))
    return state


# ---------------------------------------------------------------- 조건 트리


def test_and_requires_every_child(engine, screen):
    screen.visible = {"A"}
    condition = Condition(op="and", items=[
        Condition(type="object_visible", params={"object": "A"}),
        Condition(type="object_visible", params={"object": "B"}),
    ])
    assert evaluate(condition, engine.ctx) is False

    screen.visible = {"A", "B"}
    assert evaluate(condition, engine.ctx) is True


def test_or_needs_one(engine, screen):
    screen.visible = {"B"}
    condition = Condition(op="or", items=[
        Condition(type="object_visible", params={"object": "A"}),
        Condition(type="object_visible", params={"object": "B"}),
    ])
    assert evaluate(condition, engine.ctx) is True


def test_empty_and_group_is_false(engine):
    """조건이 하나도 없는 묶음이 참이면 모든 상황이 맞아 버린다."""
    assert evaluate(Condition(op="and", items=[]), engine.ctx) is False


def test_negate_flips_the_result(engine, screen):
    screen.visible = {"A"}
    condition = Condition(type="object_visible", params={"object": "A"}, negate=True)
    assert evaluate(condition, engine.ctx) is False


def test_nested_tree(engine, screen):
    screen.visible = {"A", "C"}
    condition = Condition(op="and", items=[
        Condition(type="object_visible", params={"object": "A"}),
        Condition(op="or", items=[
            Condition(type="object_visible", params={"object": "B"}),
            Condition(type="object_visible", params={"object": "C"}),
        ]),
    ])
    assert evaluate(condition, engine.ctx) is True


def test_unknown_condition_is_false(engine):
    assert evaluate(Condition(type="존재하지않음"), engine.ctx) is False


def test_expr_condition_uses_variables(engine):
    engine.ctx.variables.set("n", 5)
    assert evaluate(Condition(type="expr", params={"expr": "n > 3"}), engine.ctx) is True
    assert evaluate(Condition(type="expr", params={"expr": "n > 9"}), engine.ctx) is False


# ---------------------------------------------------------------- 판정


def test_detects_the_matching_state(project, engine, screen):
    add_state(project, "메인화면", "메인마커")
    add_state(project, "설정창", "설정마커")
    machine = engine.ctx.states

    screen.visible = {"설정마커"}
    assert machine.detect(fresh=True).name == "설정창"

    screen.visible = {"메인마커"}
    assert machine.detect(fresh=True).name == "메인화면"


def test_priority_breaks_ties(project, engine, screen):
    add_state(project, "일반", "마커", priority=0)
    add_state(project, "구체적", "마커", priority=10)
    screen.visible = {"마커"}

    assert engine.ctx.states.detect(fresh=True).name == "구체적"


def test_interrupt_state_wins_over_priority(project, engine, screen):
    add_state(project, "메인화면", "마커", priority=50)
    add_state(project, "광고팝업", "마커", priority=0, interrupt=True)
    screen.visible = {"마커"}

    assert engine.ctx.states.detect(fresh=True).name == "광고팝업"


def test_unknown_when_nothing_matches(project, engine, screen):
    add_state(project, "메인화면", "마커")
    screen.visible = set()

    assert engine.ctx.states.detect(fresh=True) is None
    assert engine.ctx.states.current_name() == "UNKNOWN"


def test_resolve_by_name_or_id(project, engine):
    state = add_state(project, "설정창", "마커")
    machine = engine.ctx.states
    assert machine.resolve("설정창") is state
    assert machine.resolve(state.id) is state
    assert machine.resolve("없는것") is None


# ---------------------------------------------------------------- 이동


def build_two_rooms(project, screen):
    """메인화면 ⇄ 설정창. 전이는 '이동' 이라는 글자를 입력하는 것으로 흉내 낸다."""
    main = add_state(project, "메인화면", "메인마커")
    settings = add_state(project, "설정창", "설정마커")
    project.states.transitions.append(
        Transition(src=main.id, dst=settings.id, settle_ms=0,
                   actions=[Action(type="type_text", params={"text": "설정으로"})])
    )
    project.states.transitions.append(
        Transition(src=settings.id, dst=main.id, settle_ms=0,
                   actions=[Action(type="type_text", params={"text": "메인으로"})])
    )
    return main, settings


def test_ensure_does_nothing_when_already_there(project, engine, screen):
    build_two_rooms(project, screen)
    screen.visible = {"설정마커"}

    assert engine.ctx.states.ensure("설정창") is True
    assert engine.ctx.sender.text() == ""


def test_ensure_runs_the_transition_actions(project, engine, screen, monkeypatch):
    build_two_rooms(project, screen)
    screen.visible = {"메인마커"}

    # 전이 동작이 실행되면 화면이 바뀐다
    original_send = engine.ctx.send

    def send_and_switch(steps):
        original_send(steps)
        if engine.ctx.sender.text().endswith("설정으로"):
            screen.visible = {"설정마커"}

    engine.ctx.send = send_and_switch

    assert engine.ctx.states.ensure("설정창") is True
    assert engine.ctx.sender.text() == "설정으로"


def test_ensure_fails_when_no_path_exists(project, engine, screen):
    add_state(project, "메인화면", "메인마커")
    add_state(project, "고립된창", "고립마커")
    screen.visible = {"메인마커"}

    assert engine.ctx.states.ensure("고립된창", timeout_ms=200) is False


def test_ensure_fails_for_unknown_state(project, engine, screen):
    assert engine.ctx.states.ensure("없는상황", timeout_ms=100) is False


def test_ensure_times_out_when_transition_does_not_work(project, engine, screen):
    """동작은 했는데 화면이 안 바뀌면 시간 초과로 끝난다."""
    build_two_rooms(project, screen)
    screen.visible = {"메인마커"}

    assert engine.ctx.states.ensure("설정창", timeout_ms=150) is False


def test_wait_for_returns_when_the_screen_changes(project, engine, screen):
    add_state(project, "로딩중", "로딩마커")
    add_state(project, "완료", "완료마커")
    screen.visible = {"완료마커"}

    assert engine.ctx.states.wait_for("완료", timeout_ms=200) is True
    assert engine.ctx.states.wait_for("로딩중", timeout_ms=150) is False


# ---------------------------------------------------------------- 자가 복구


def build_popup(project, screen):
    main = add_state(project, "메인화면", "메인마커")
    popup = add_state(project, "광고팝업", "광고마커", interrupt=True)
    project.states.transitions.append(
        Transition(src=popup.id, dst=main.id, settle_ms=0,
                   actions=[Action(type="type_text", params={"text": "닫기"})])
    )
    return main, popup


def test_interrupt_is_closed_and_work_resumes(project, engine, screen):
    build_popup(project, screen)
    screen.visible = {"광고마커"}

    original_send = engine.ctx.send

    def send_and_close(steps):
        original_send(steps)
        if "닫기" in engine.ctx.sender.text():
            screen.visible = {"메인마커"}  # 팝업이 닫혔다

    engine.ctx.send = send_and_close

    handled = engine.ctx.states.handle_interrupts()

    assert handled is True
    assert engine.ctx.sender.text() == "닫기"
    assert engine.ctx.states.detect(fresh=True).name == "메인화면"


def test_no_interrupt_means_no_work(project, engine, screen):
    build_popup(project, screen)
    screen.visible = {"메인마커"}

    assert engine.ctx.states.handle_interrupts() is False
    assert engine.ctx.sender.text() == ""


def test_repeating_popup_gives_up(project, engine, screen):
    """닫아도 계속 뜨는 팝업에 무한히 매달리지 않는다."""
    build_popup(project, screen)
    screen.visible = {"광고마커"}  # 닫아도 그대로

    engine.ctx.states.handle_interrupts()
    engine.ctx.states.handle_interrupts()

    assert engine.ctx.sender.text().count("닫기") <= 4


def test_interrupt_without_escape_transition_is_reported(project, engine, screen):
    add_state(project, "막힌팝업", "팝업마커", interrupt=True)
    screen.visible = {"팝업마커"}

    assert engine.ctx.states.handle_interrupts() is False


def test_popup_during_navigation_is_cleared_first(project, engine, screen):
    """설정창으로 가는 도중 팝업이 뜨면, 먼저 닫고 다시 간다."""
    main, settings = build_two_rooms(project, screen)
    popup = add_state(project, "광고팝업", "광고마커", interrupt=True)
    project.states.transitions.append(
        Transition(src=popup.id, dst=main.id, settle_ms=0,
                   actions=[Action(type="type_text", params={"text": "[닫기]"})])
    )
    screen.visible = {"광고마커"}  # 시작하자마자 팝업

    original_send = engine.ctx.send

    def scripted(steps):
        original_send(steps)
        typed = engine.ctx.sender.text()
        if typed.endswith("[닫기]"):
            screen.visible = {"메인마커"}
        elif typed.endswith("설정으로"):
            screen.visible = {"설정마커"}

    engine.ctx.send = scripted

    assert engine.ctx.states.ensure("설정창", timeout_ms=3000) is True
    assert engine.ctx.sender.text() == "[닫기]설정으로"


# ---------------------------------------------------------------- 노드 연동


def flow_with(project, *nodes):
    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    previous = flow.start_node()
    for node in nodes:
        flow.add_node(node)
        flow.connect(previous.id, "ok", node.id)
        previous = node
    return flow


def test_required_state_navigates_before_running(project, engine, screen):
    build_two_rooms(project, screen)
    screen.visible = {"메인마커"}

    flow_with(
        project,
        Node(type="action_group", title="설정에서 할 일", required_state="설정창",
             on_wrong_state="navigate", state_timeout_ms=3000,
             actions=[Action(type="type_text", params={"text": "작업"})]),
    )

    original_send = engine.ctx.send

    def scripted(steps):
        original_send(steps)
        if engine.ctx.sender.text().endswith("설정으로"):
            screen.visible = {"설정마커"}

    engine.ctx.send = scripted

    assert engine.run("main") is True
    assert engine.ctx.sender.text() == "설정으로작업"


def test_required_state_skip_mode(project, engine, screen):
    build_two_rooms(project, screen)
    screen.visible = {"메인마커"}

    flow_with(
        project,
        Node(type="action_group", title="설정 전용", required_state="설정창",
             on_wrong_state="skip",
             actions=[Action(type="type_text", params={"text": "실행되면 안 됨"})]),
    )

    assert engine.run("main") is True
    assert engine.ctx.sender.text() == ""


def test_required_state_fail_mode(project, engine, screen):
    build_two_rooms(project, screen)
    screen.visible = {"메인마커"}

    flow_with(
        project,
        Node(type="action_group", title="설정 전용", required_state="설정창",
             on_wrong_state="fail",
             actions=[Action(type="type_text", params={"text": "안 됨"})]),
    )

    assert engine.run("main") is False


def test_state_gate_node_navigates(project, engine, screen):
    build_two_rooms(project, screen)
    screen.visible = {"메인마커"}

    flow_with(
        project,
        Node(type="state_gate", title="설정창으로",
             params={"target_state": "설정창", "mode": "navigate", "timeout_ms": 3000}),
    )

    original_send = engine.ctx.send

    def scripted(steps):
        original_send(steps)
        if engine.ctx.sender.text().endswith("설정으로"):
            screen.visible = {"설정마커"}

    engine.ctx.send = scripted

    assert engine.run("main") is True


def test_state_gate_check_mode_fails_when_not_there(project, engine, screen):
    build_two_rooms(project, screen)
    screen.visible = {"메인마커"}

    flow_with(
        project,
        Node(type="state_gate", title="확인",
             params={"target_state": "설정창", "mode": "check"}),
    )

    assert engine.run("main") is False


def test_goto_state_action(project, engine, screen):
    build_two_rooms(project, screen)
    screen.visible = {"설정마커"}

    flow_with(
        project,
        Node(type="action_group", title="이동",
             actions=[Action(type="goto_state", params={"target_state": "설정창"})]),
    )

    assert engine.run("main") is True


def test_wait_state_action_times_out(project, engine, screen):
    build_two_rooms(project, screen)
    screen.visible = {"메인마커"}

    flow_with(
        project,
        Node(type="action_group", title="대기",
             actions=[Action(type="wait_state",
                             params={"target_state": "설정창", "timeout_ms": 120,
                                     "poll_ms": 30, "required": True})]),
    )

    assert engine.run("main") is False
