"""비동기 플로우 실행 테스트.

`끝날 때까지 대기` 를 끄면 배경에서 돌고 곧바로 다음 노드로 넘어가야 한다.
스키마에만 있고 실제로는 동기로 돌던 구멍을 메운 부분이다.
"""

from __future__ import annotations

import time

import pytest

from itda.core.model import Action, Node
from itda.engine.arbiter import InputArbiter
from itda.engine.input import DryRunSender
from itda.engine.runner import Engine


@pytest.fixture
def quick(project):
    project.settings.timing.default_pre_ms = 0
    project.settings.timing.default_post_ms = 0
    project.settings.human.enabled = False
    return project


def fill(flow, *actions: Action) -> None:
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()
    node = flow.add_node(Node(type="action_group", title="작업", actions=list(actions)))
    flow.connect(start.id, "ok", node.id)


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------- 동기 (기존 동작)


def test_wait_true_runs_inline(quick):
    key, sub = quick.add_flow("서브")
    fill(sub, Action(type="type_text", params={"text": "안쪽"}))
    fill(quick.flow("main"),
         Action(type="run_flow", params={"flow": key, "wait": True}),
         Action(type="type_text", params={"text": "바깥"}))

    engine = Engine(quick, sender=DryRunSender())
    assert engine.run("main") is True

    # 같은 문맥에서 순서대로 실행된다
    assert engine.ctx.sender.text() == "안쪽바깥"
    assert engine.children_running() is False


# ---------------------------------------------------------------- 비동기


def test_wait_false_returns_immediately(quick):
    key, sub = quick.add_flow("서브")
    fill(sub, Action(type="sleep", params={"ms": 300, "jitter_pct": 0}),
         Action(type="type_text", params={"text": "늦게"}))
    fill(quick.flow("main"),
         Action(type="run_flow", params={"flow": key, "wait": False}),
         Action(type="type_text", params={"text": "먼저"}))

    engine = Engine(quick, sender=DryRunSender())
    started = time.perf_counter()
    assert engine.run("main") is True
    elapsed = time.perf_counter() - started

    # 서브가 300ms 자는데 본체는 기다리지 않았다
    assert elapsed < 0.25
    assert engine.ctx.sender.text() == "먼저"

    assert engine.join_children(timeout=5)


def test_async_child_actually_runs(quick):
    key, sub = quick.add_flow("서브")
    fill(sub, Action(type="type_text", params={"text": "배경작업"}))
    fill(quick.flow("main"), Action(type="run_flow", params={"flow": key, "wait": False}))

    engine = Engine(quick, sender=DryRunSender())
    engine.run("main")
    assert engine.join_children(timeout=5)

    child = engine._children[0][1]
    assert child.ctx.sender.text() == "배경작업"


def test_async_child_has_its_own_variables(quick):
    """부모와 변수를 공유하면 서로 덮어써서 원인을 못 찾는 버그가 난다."""
    key, sub = quick.add_flow("서브")
    fill(sub, Action(type="set_var", params={"name": "n", "value": "99"}))
    fill(quick.flow("main"),
         Action(type="set_var", params={"name": "n", "value": "1"}),
         Action(type="run_flow", params={"flow": key, "wait": False}))

    engine = Engine(quick, sender=DryRunSender())
    engine.run("main")
    assert engine.join_children(timeout=5)

    assert engine.ctx.variables.get("n") == 1
    assert engine._children[0][1].ctx.variables.get("n") == 99


def test_async_args_are_passed(quick):
    key, sub = quick.add_flow("서브")
    fill(sub, Action(type="log", params={"message": "받음"}))
    fill(quick.flow("main"),
         Action(type="run_flow", params={"flow": key, "wait": False, "args": "인자=값"}))

    engine = Engine(quick, sender=DryRunSender())
    engine.run("main")
    assert engine.join_children(timeout=5)

    assert engine._children[0][1].ctx.variables.get("인자") == "값"


def test_async_uses_a_separate_sender(quick):
    """부모와 주입기를 공유하면 입력 기록이 뒤섞인다."""
    key, sub = quick.add_flow("서브")
    fill(sub, Action(type="type_text", params={"text": "자식"}))
    fill(quick.flow("main"),
         Action(type="run_flow", params={"flow": key, "wait": False}),
         Action(type="type_text", params={"text": "부모"}))

    engine = Engine(quick, sender=DryRunSender(), sender_factory=DryRunSender)
    engine.run("main")
    assert engine.join_children(timeout=5)

    assert engine.ctx.sender.text() == "부모"
    assert engine._children[0][1].ctx.sender.text() == "자식"


def test_async_shares_the_input_arbiter(quick):
    key, sub = quick.add_flow("서브")
    fill(sub, Action(type="type_text", params={"text": "x"}))
    fill(quick.flow("main"), Action(type="run_flow", params={"flow": key, "wait": False}))

    arbiter = InputArbiter()
    engine = Engine(quick, sender=DryRunSender(), arbiter=arbiter,
                    sender_factory=DryRunSender)
    engine.run("main")
    assert engine.join_children(timeout=5)

    child = engine._children[0][1]
    assert child.arbiter is arbiter
    assert child.ctx.arbiter is arbiter
    assert arbiter.owner is None  # 끝나면 반납한다


def test_async_priority_is_carried(quick):
    key, sub = quick.add_flow("서브")
    fill(sub, Action(type="log", params={"message": "우선순위"}))
    fill(quick.flow("main"),
         Action(type="run_flow", params={"flow": key, "wait": False, "priority": 7}))

    engine = Engine(quick, sender=DryRunSender(), sender_factory=DryRunSender)
    engine.run("main")
    assert engine.join_children(timeout=5)

    assert engine._children[0][1].ctx.priority == 7


def test_subflow_node_can_run_async(quick):
    key, sub = quick.add_flow("서브")
    fill(sub, Action(type="type_text", params={"text": "노드비동기"}))

    flow = quick.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()
    caller = flow.add_node(
        Node(type="subflow", title="호출", params={"flow": key, "wait": False, "priority": 3})
    )
    flow.connect(start.id, "ok", caller.id)

    engine = Engine(quick, sender=DryRunSender(), sender_factory=DryRunSender)
    assert engine.run("main") is True
    assert engine.join_children(timeout=5)

    assert engine._children[0][1].ctx.sender.text() == "노드비동기"


def test_stopping_the_parent_stops_children(quick):
    key, sub = quick.add_flow("서브")
    fill(sub, Action(type="sleep", params={"ms": 3000, "jitter_pct": 0}))
    fill(quick.flow("main"), Action(type="run_flow", params={"flow": key, "wait": False}))

    engine = Engine(quick, sender=DryRunSender(), sender_factory=DryRunSender)
    engine.run("main")
    assert wait_until(lambda: engine.children_running())

    started = time.perf_counter()
    engine.stop()

    assert engine.join_children(timeout=5)
    assert time.perf_counter() - started < 2.0  # 3초를 다 기다리지 않는다


def test_missing_async_flow_reports_failure(quick):
    fill(quick.flow("main"),
         Action(type="run_flow", params={"flow": "없는것", "wait": False}))

    engine = Engine(quick, sender=DryRunSender())
    assert engine.run("main") is False


def test_children_running_is_false_before_any_spawn(quick):
    engine = Engine(quick, sender=DryRunSender())
    assert engine.children_running() is False
    assert engine.join_children(timeout=0.1) is True
