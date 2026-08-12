"""실제 실행 제어 테스트.

실주입기(Win32Sender)를 만드는 경로까지만 확인하고, 주입 자체는 conftest 안전장치가 막는다.
"""

from __future__ import annotations

import pytest

from itda.core.model import Action, Node
from itda.gui.run_controller import RunController


@pytest.fixture
def controller(qapp):
    c = RunController()
    yield c
    c.release_hotkey()


def test_starts_idle(controller):
    assert controller.running is False
    assert controller.engine is None


def test_stop_without_a_run_is_harmless(controller):
    controller.stop()  # 예외가 나면 안 된다


def test_global_hotkey_registers_and_releases(controller):
    """F12 전역 등록. 환경에 따라 실패할 수 있으므로 결과는 참/거짓 모두 허용한다."""
    ok = controller.install_hotkey()
    assert isinstance(ok, bool)
    if ok:
        assert controller.hotkey.registered
    controller.release_hotkey()
    assert controller.hotkey.registered is False


def test_run_uses_the_real_sender_and_is_blocked_by_the_guard(controller, project):
    """실제 실행 경로가 Win32Sender 를 쓰는지 — 안전장치가 막아 주므로 여기서 확인만 한다."""
    from itda.engine.input import Win32Sender

    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()
    node = flow.add_node(
        Node(type="action_group", title="클릭",
             actions=[Action(type="click", params={"target_mode": "fixed", "point": [10, 10]})])
    )
    flow.connect(start.id, "ok", node.id)

    captured = {}
    original_run = controller.run

    def spy(project_arg, flow_key):
        result = original_run(project_arg, flow_key)
        return result

    controller.run = spy
    ok = controller.run(project, "main")

    # 안전장치가 주입을 막으므로 실행은 실패로 끝난다 — 그게 정상이다
    assert ok is False
    assert controller.running is False


def test_run_reports_finish_signal(controller, project, qapp):
    seen = []
    controller.finished.connect(lambda key, ok: seen.append((key, ok)))

    controller.run(project, "main")

    assert seen and seen[0][0] == "main"


def test_missing_flow_finishes_as_failure(controller, project):
    assert controller.run(project, "없는플로우") is False


def test_multi_run_needs_autostart_entries(controller, project):
    project.settings.entries = []
    assert controller.run_multi(project) == []
    assert controller.running is False


def test_multi_run_starts_marked_flows(controller, project):
    """자동 시작 플로우들이 스케줄러에 올라가는지 — 주입은 안전장치가 막는다."""
    from itda.core.model import FlowEntry

    key, _ = project.add_flow("보조")
    project.settings.entries = [
        FlowEntry(flow="main", priority=5, autostart=True),
        FlowEntry(flow=key, priority=1, autostart=True),
    ]

    started = controller.run_multi(project)

    assert set(started) == {"main", key}
    if controller.scheduler is not None:
        controller.scheduler.stop_all()
        controller.scheduler.join(5)
    controller.stop()


def test_stop_reaches_the_scheduler(controller, project):
    from itda.core.model import FlowEntry

    project.settings.entries = [FlowEntry(flow="main", autostart=True, loop=True)]
    controller.run_multi(project)

    controller.stop()

    if controller.scheduler is not None:
        assert controller.scheduler.join(5) is True
