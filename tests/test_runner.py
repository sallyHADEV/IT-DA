"""실행 엔진 테스트.

DryRunSender 로 돌리므로 실제 입력은 나가지 않는다(conftest 안전장치가 이중으로 막는다).
화면이 필요한 액션은 합성 이미지를 넣어 준다.
"""

from __future__ import annotations

import numpy as np
import pytest

from itda.core.model import Action, ErrorPolicy, Node, Retry, VarDecl
from itda.engine.context import ExecutionContext
from itda.engine.input import DryRunSender
from itda.engine.runner import Engine, FlowRunner
from itda.gui.commands import AddEdgeCommand


@pytest.fixture
def sender():
    return DryRunSender()


@pytest.fixture
def engine(project, sender):
    e = Engine(project, sender=sender)
    # 대기를 실제로 자면 테스트가 느려진다. 딜레이는 0 으로.
    project.settings.timing.default_pre_ms = 0
    project.settings.timing.default_post_ms = 0
    project.settings.human.enabled = False
    return e


def connect(project, flow, src, port, dst) -> None:
    edge = flow.connect(src.id, port, dst.id)
    assert edge is not None


def linear_flow(project, *nodes: Node):
    """시작 → 노드들 → 순서대로 연결한 main 플로우."""
    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    previous = flow.start_node()
    for node in nodes:
        flow.add_node(node)
        connect(project, flow, previous, "ok", node)
        previous = node
    return flow


def action_node(title: str, *actions: Action, **kwargs) -> Node:
    node = Node(type="action_group", title=title, actions=list(actions), **kwargs)
    return node


# ---------------------------------------------------------------- 기본 흐름


def test_runs_a_simple_flow(project, engine):
    linear_flow(
        project,
        action_node("변수 준비", Action(type="set_var", params={"name": "횟수", "value": "3"})),
        action_node("로그", Action(type="log", params={"message": "횟수=${횟수}"})),
    )

    assert engine.run("main") is True
    assert engine.ctx.variables.get("횟수") == 3


def test_flow_without_start_node_fails(project, engine):
    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type != "start"]
    assert engine.run("main") is False


def test_unknown_flow_key(project, engine):
    assert engine.run("없는플로우") is False


def test_end_node_result_decides_success(project, engine):
    linear_flow(project, Node(type="end", title="끝", params={"result": "success"}))
    assert engine.run("main") is True

    linear_flow(project, Node(type="end", title="끝", params={"result": "fail"}))
    assert engine.run("main") is False


# ---------------------------------------------------------------- 액션 실행


def test_click_sends_input_through_the_sender(project, engine, sender):
    linear_flow(
        project,
        action_node(
            "클릭",
            Action(type="click", params={"target_mode": "fixed", "point": [640, 480]}),
        ),
    )
    project.settings.timing.click_offset_px = 0

    engine.run("main")

    assert sender.positions()[-1] == (640, 480)


def test_type_text_interpolates_variables(project, engine, sender):
    linear_flow(
        project,
        action_node(
            "입력",
            Action(type="set_var", params={"name": "이름", "value": '"홍길동"'}),
            Action(type="type_text", params={"text": "안녕 ${이름}"}),
        ),
    )

    engine.run("main")

    assert sender.text() == "안녕 홍길동"


def test_calc_updates_a_variable(project, engine):
    linear_flow(
        project,
        action_node(
            "계산",
            Action(type="set_var", params={"name": "n", "value": "10"}),
            Action(type="calc", params={"name": "n", "op": "add", "operand": "5"}),
        ),
    )

    engine.run("main")

    assert engine.ctx.variables.get("n") == 15


def test_disabled_action_is_skipped(project, engine, sender):
    linear_flow(
        project,
        action_node(
            "입력",
            Action(type="type_text", enabled=False, params={"text": "무시"}),
            Action(type="type_text", params={"text": "실행"}),
        ),
    )

    engine.run("main")

    assert sender.text() == "실행"


def test_action_without_executor_fails_the_node(project, engine):
    linear_flow(project, action_node("이상한 액션", Action(type="존재하지않음")))
    assert engine.run("main") is False


# ---------------------------------------------------------------- 분기 / 반복


def test_branch_takes_the_true_port(project, engine, sender):
    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()

    setup = flow.add_node(action_node("준비", Action(type="set_var",
                                                    params={"name": "n", "value": "5"})))
    branch = flow.add_node(Node(type="branch", title="분기", params={"expr": "n > 3"}))
    yes = flow.add_node(action_node("참", Action(type="type_text", params={"text": "참"})))
    no = flow.add_node(action_node("거짓", Action(type="type_text", params={"text": "거짓"})))

    connect(project, flow, start, "ok", setup)
    connect(project, flow, setup, "ok", branch)
    connect(project, flow, branch, "true", yes)
    connect(project, flow, branch, "false", no)

    engine.run("main")

    assert sender.text() == "참"


def test_switch_picks_the_matching_case(project, engine, sender):
    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()

    setup = flow.add_node(action_node("준비", Action(type="set_var",
                                                    params={"name": "s", "value": '"재시도"'})))
    switch = flow.add_node(Node(type="switch", title="분기",
                                params={"expr": "s", "cases": "성공, 재시도, 취소"}))
    retry = flow.add_node(action_node("재시도", Action(type="type_text", params={"text": "R"})))
    other = flow.add_node(action_node("그 외", Action(type="type_text", params={"text": "D"})))

    connect(project, flow, start, "ok", setup)
    connect(project, flow, setup, "ok", switch)
    connect(project, flow, switch, "재시도", retry)
    connect(project, flow, switch, "default", other)

    engine.run("main")

    assert sender.text() == "R"


def test_loop_repeats_the_action_list(project, engine, sender):
    linear_flow(
        project,
        Node(
            type="loop",
            title="세 번",
            params={"mode": "count", "count": 3, "max_iterations": 100},
            actions=[Action(type="type_text", params={"text": "x"})],
        ),
    )

    engine.run("main")

    assert sender.text() == "xxx"


def test_while_loop_stops_when_condition_turns_false(project, engine, sender):
    linear_flow(
        project,
        action_node("준비", Action(type="set_var", params={"name": "n", "value": "0"})),
        Node(
            type="loop",
            title="반복",
            params={"mode": "while", "expr": "n < 4", "max_iterations": 50},
            actions=[
                Action(type="type_text", params={"text": "y"}),
                Action(type="calc", params={"name": "n", "op": "add", "operand": "1"}),
            ],
        ),
    )

    engine.run("main")

    assert sender.text() == "yyyy"
    assert engine.ctx.variables.get("n") == 4


def test_loop_respects_max_iterations(project, engine, sender):
    linear_flow(
        project,
        Node(
            type="loop",
            title="무한",
            params={"mode": "forever", "max_iterations": 5},
            actions=[Action(type="type_text", params={"text": "z"})],
        ),
    )

    engine.run("main")

    assert sender.text() == "zzzzz"


def test_if_action_skips_the_rest(project, engine, sender):
    linear_flow(
        project,
        action_node(
            "조건",
            Action(type="set_var", params={"name": "n", "value": "1"}),
            Action(type="if", params={"expr": "n > 5", "on_false": "skip_rest"}),
            Action(type="type_text", params={"text": "실행되면 안 됨"}),
        ),
    )

    engine.run("main")

    assert sender.text() == ""


# ---------------------------------------------------------------- 재시도 / 예외


def test_retry_then_give_up(project, engine):
    """못 찾는 이미지 → 재시도 횟수만큼 시도한 뒤 실패."""
    node = action_node(
        "찾기",
        Action(type="image_search", params={"objects": ["없는객체"], "required": True}),
        retry=Retry(count=2, interval_ms=0),
    )
    linear_flow(project, node)

    assert engine.run("main") is False


def test_error_policy_continue_keeps_going(project, engine, sender):
    failing = action_node(
        "실패",
        Action(type="image_search", params={"objects": ["없는객체"]}),
        on_error=ErrorPolicy(mode="continue"),
    )
    linear_flow(project, failing,
                action_node("다음", Action(type="type_text", params={"text": "계속"})))

    assert engine.run("main") is True
    assert sender.text() == "계속"


def test_error_policy_fail_port_routes_to_the_fail_edge(project, engine, sender):
    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()

    failing = flow.add_node(
        action_node("실패", Action(type="image_search", params={"objects": ["없는객체"]}))
    )
    recover = flow.add_node(action_node("복구", Action(type="type_text", params={"text": "복구"})))

    connect(project, flow, start, "ok", failing)
    connect(project, flow, failing, "fail", recover)

    engine.run("main")

    assert sender.text() == "복구"


def test_error_policy_goto_jumps_to_the_node(project, engine, sender):
    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()

    target = flow.add_node(action_node("대피소", Action(type="type_text", params={"text": "대피"})))
    failing = flow.add_node(
        action_node(
            "실패",
            Action(type="image_search", params={"objects": ["없는객체"]}),
            on_error=ErrorPolicy(mode="goto", target=target.id),
        )
    )
    connect(project, flow, start, "ok", failing)

    engine.run("main")

    assert sender.text() == "대피"


def test_stop_action_ends_the_flow(project, engine, sender):
    linear_flow(
        project,
        action_node(
            "중단",
            Action(type="stop", params={"scope": "flow", "reason": "테스트"}),
            Action(type="type_text", params={"text": "실행되면 안 됨"}),
        ),
    )

    assert engine.run("main") is True
    assert sender.text() == ""


# ---------------------------------------------------------------- 정지


def test_stop_flag_interrupts_the_run(project, engine, sender):
    """정지를 누르면 남은 액션이 실행되지 않는다."""
    linear_flow(
        project,
        action_node("첫째", Action(type="type_text", params={"text": "A"})),
        action_node("둘째", Action(type="type_text", params={"text": "B"})),
    )

    original = engine.ctx.send

    def send_and_stop(steps):
        original(steps)
        engine.stop()  # 첫 입력 직후 정지

    engine.ctx.send = send_and_stop

    assert engine.run("main") is False
    assert sender.text() == "A"


# ---------------------------------------------------------------- 서브플로우


def test_subflow_runs_and_shares_variables(project, engine, sender):
    key, sub = project.add_flow("서브")
    sub.nodes = [n for n in sub.nodes if n.type == "start"]
    sub.edges = []
    sub_start = sub.start_node()
    inner = sub.add_node(action_node("내부", Action(type="type_text", params={"text": "안쪽"})))
    sub.connect(sub_start.id, "ok", inner.id)

    linear_flow(project, Node(type="subflow", title="호출", params={"flow": key, "wait": True}))

    assert engine.run("main") is True
    assert sender.text() == "안쪽"


def test_subflow_args_become_variables(project, engine):
    key, sub = project.add_flow("서브")
    linear_flow(project, Node(type="subflow", title="호출",
                              params={"flow": key, "args": "인자=값", "wait": True}))

    engine.run("main")

    assert engine.ctx.variables.get("인자") == "값"


def test_missing_subflow_fails(project, engine):
    linear_flow(project, Node(type="subflow", title="호출", params={"flow": "없음"}))
    assert engine.run("main") is False


def test_recursive_subflow_is_capped(project, engine):
    """A → A 로 자기를 부르면 깊이 제한에서 멈춘다."""
    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()
    caller = flow.add_node(Node(type="subflow", title="자기호출", params={"flow": "main"}))
    connect(project, flow, start, "ok", caller)

    assert engine.run("main") is False  # 예외 없이 실패로 끝난다


# ---------------------------------------------------------------- 변수 선언


def test_declared_variables_are_seeded(project, engine):
    project.settings.globals.append(VarDecl(name="전역값", type="int", default="7"))
    project.flow("main").variables.append(VarDecl(name="지역값", type="str", default="가"))
    linear_flow(project, action_node("빈 노드"))

    engine.run("main")

    assert engine.ctx.variables.get("전역값") == 7
    assert engine.ctx.variables.get("지역값") == "가"


# ---------------------------------------------------------------- 이미지 검색 연동


def test_image_search_finds_a_synthetic_target(project, engine, monkeypatch, tmp_path):
    """화면을 합성 이미지로 바꿔 끼워 매칭 → 클릭까지 이어지는지 본다."""
    import cv2

    from itda.core.model import TargetObject
    from itda.vision import capture

    project.save(tmp_path / "p")
    button = np.full((40, 90, 3), 220, dtype=np.uint8)
    cv2.rectangle(button, (2, 2), (87, 37), (40, 40, 40), 2)

    scene = np.random.default_rng(1).integers(60, 90, size=(720, 1280, 3), dtype=np.uint8)
    scene[300:340, 400:490] = button

    image_path = tmp_path / "button.png"
    capture.save_bgr(button, image_path)
    relative = project.import_image(image_path, "확인버튼")
    project.objects.objects.append(TargetObject(name="확인버튼", images=[relative]))

    monkeypatch.setattr(ExecutionContext, "screen", lambda self, fresh=False: scene)
    project.settings.timing.click_offset_px = 0

    linear_flow(
        project,
        action_node(
            "찾아 클릭",
            Action(type="image_search", out_var="위치",
                   params={"objects": ["확인버튼"], "required": True}),
            Action(type="click", params={"target_mode": "object", "object": "확인버튼"}),
        ),
    )

    assert engine.run("main") is True
    assert engine.ctx.variables.get("위치") == [445, 320]
    assert engine.ctx.variables.get("위치_ok") is True
    assert engine.ctx.sender.positions()[-1] == (445, 320)
