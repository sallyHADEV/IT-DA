"""메인 윈도우 배선 테스트.

패널·도크·시그널이 실제로 연결되어 있는지 본다. 화면은 오프스크린이라 보이지 않지만
위젯 트리와 신호는 그대로 동작한다.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF

from itda.core.events import BUS, OK, RUNNING
from itda.core.model import Action, State, TargetObject
from itda.gui.main_window import MainWindow


@pytest.fixture
def window(qapp):
    # 최근 프로젝트 복원은 끈다 — 테스트는 항상 같은 상태에서 시작해야 한다
    w = MainWindow(restore_recent=False)
    yield w
    w.stop_demo()
    w.project.mark_dirty(False)
    w.close()


def test_window_opens_with_default_project(window):
    assert window.tabs.count() == 1
    assert window.current_scene() is not None
    assert window.project.flow("main") is not None


def test_all_docks_exist(window):
    docks = {
        window.dock_project, window.dock_palette, window.dock_objects,
        window.dock_actions, window.dock_property, window.dock_log, window.dock_vars,
    }
    assert len(docks) == 7


def test_selecting_node_fills_property_and_action_panels(window):
    scene = window.current_scene()
    node = scene.flow.nodes[1]
    node.actions.append(Action(type="click"))

    scene.select_only(node.id)

    assert window.property_panel.node is node
    assert window.action_panel.node is node
    assert window.action_panel.list.count() == 1


def test_clearing_selection_resets_panels(window):
    scene = window.current_scene()
    scene.select_only(scene.flow.nodes[1].id)
    scene.clearSelection()

    assert window.property_panel.node is None
    assert window.action_panel.node is None


def test_action_selection_switches_property_panel(window):
    scene = window.current_scene()
    node = scene.flow.nodes[1]
    action = Action(type="type_text")
    node.actions.append(action)
    scene.select_only(node.id)

    window.action_panel.select_action(action.id)

    assert window.property_panel.action is action


def test_form_context_lists_project_contents(window):
    window.project.add_object(TargetObject(name="확인 버튼"))
    window.project.states.states.append(State(name="설정창"))
    key, _ = window.project.add_flow("보조")

    context = window.form_context()

    assert "확인 버튼" in context.objects()
    assert "설정창" in context.states()
    assert key in context.flows()
    assert any(node_id for node_id, _label in context.nodes())


def test_known_variables_include_out_vars(window):
    node = window.project.flow("main").nodes[1]
    node.actions.append(Action(type="ocr_read", out_var="점수"))
    node.actions.append(Action(type="set_var", params={"name": "횟수"}))

    names = window.form_context().variables()

    assert "점수" in names and "횟수" in names


def test_opening_second_flow_adds_tab_with_own_undo_stack(window):
    key, _ = window.project.add_flow("보조 루틴")
    window.open_flow(key)

    assert window.tabs.count() == 2
    first = window.views["main"].flow_scene.undo_stack
    second = window.views[key].flow_scene.undo_stack
    assert first is not second


def test_closing_tab_releases_view(window):
    key, _ = window.project.add_flow("보조 루틴")
    window.open_flow(key)

    window._close_tab(window.tabs.indexOf(window.views[key]))

    assert key not in window.views
    assert window.tabs.count() == 1


def test_runtime_events_paint_the_canvas(window):
    """이벤트 버스 → 메인 윈도우 → 씬 하이라이트."""
    scene = window.current_scene()
    node_id = scene.flow.nodes[1].id

    BUS.node_status.emit("main", node_id, RUNNING)
    assert scene.node_items[node_id].status == RUNNING

    BUS.node_status.emit("main", node_id, OK)
    assert scene.node_items[node_id].status == OK


def test_demo_run_marks_nodes_and_stops(window, qapp):
    scene = window.current_scene()
    end = scene.add_node("end", QPointF(400, 0))
    flow = scene.flow
    from itda.gui.commands import AddEdgeCommand

    edge = flow.connect(flow.nodes[1].id, "ok", end.id)
    flow.edges.remove(edge)
    scene.undo_stack.push(AddEdgeCommand(scene, edge))

    window.start_demo()
    assert window.demo is not None
    window.demo.step_ms = 0
    for _ in range(20):
        if window.demo is None or window.demo._current is None:
            break
        window.demo._step()
        qapp.processEvents()

    assert scene.node_items[end.id].status in (OK, RUNNING)

    window.stop_demo()
    assert all(item.status == "idle" for item in scene.node_items.values())


def test_demo_without_start_node_does_not_crash(window):
    scene = window.current_scene()
    scene.flow.nodes.remove(scene.flow.start_node())

    window.start_demo()

    assert window.demo is None


def test_validate_reports_problems_to_log(window):
    from itda.core.model import Node

    window.project.flow("main").add_node(Node(type="subflow", params={"flow": "없는것"}))
    before = len(window.log_panel._records)

    window.validate_project()

    assert len(window.log_panel._records) > before
    assert any("없는 플로우" in r.message for r in window.log_panel._records)


def test_title_shows_dirty_marker(window):
    window.project.mark_dirty(False)
    window._update_title()
    assert "•" not in window.windowTitle()

    window.current_scene().add_node("action_group", QPointF(0, 0))
    assert "•" in window.windowTitle()


def test_recent_project_is_remembered_and_restored(qapp, tmp_path):
    """실행할 때마다 빈 프로젝트가 아니라 마지막에 쓰던 것이 열려야 한다."""
    first = MainWindow(restore_recent=False)
    first.project.settings.name = "이어서 작업"
    first.project.save(tmp_path / "내프로젝트")
    first._remember_recent()
    first.project.mark_dirty(False)
    first.close()

    second = MainWindow(restore_recent=True)
    try:
        assert second.project.path == tmp_path / "내프로젝트"
        assert second.project.settings.name == "이어서 작업"
    finally:
        second.project.mark_dirty(False)
        second.close()


def test_missing_recent_project_falls_back_to_a_new_one(qapp, tmp_path):
    from PyQt6.QtCore import QSettings

    from itda.gui.main_window import RECENT_KEY, SETTINGS_APP, SETTINGS_ORG

    QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(RECENT_KEY, str(tmp_path / "사라진프로젝트"))

    window = MainWindow(restore_recent=True)
    try:
        assert window.project.path is None  # 새 프로젝트로 시작
        assert window.current_scene() is not None
    finally:
        window.project.mark_dirty(False)
        window.close()


def test_save_and_reopen_project_roundtrip(window, tmp_path):
    scene = window.current_scene()
    node = scene.flow.nodes[1]
    node.title = "저장 확인용"
    node.actions.append(Action(type="click", params={"point": [7, 8]}))

    window.project.save(tmp_path / "proj")
    window.open_project_path(tmp_path / "proj")

    reopened = window.project.flow("main")
    saved = next(n for n in reopened.nodes if n.title == "저장 확인용")
    assert saved.actions[0].params["point"] == [7, 8]
    assert window.tabs.count() == 1


def test_toolbar_fits_the_default_window_width(qapp):
    """기본 창 크기에서 도구모음이 자기 자신도 못 담으면 안 된다.

    넘치면 뒤쪽 버튼이 넘침 메뉴(») 로 숨는데, 하필 뒤쪽에 실행 정지가 있다.
    실측: 고치기 전 필요폭 1501px > 기본 창 1500px 라 '검사' 가 이미 숨어 있었다.
    """
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QToolBar

    from itda.gui import style
    from itda.gui.main_window import MainWindow

    # 테마를 적용해야 실제 앱과 같은 글꼴·여백으로 재진다. 안 하면 버튼이 좁게 나와
    # 넘치는 상태에서도 통과해 버린다(실제로 그렇게 틀렸다).
    style.apply_theme(qapp)

    window = MainWindow(restore_recent=False)
    window.resize(1500, 950)
    window.show()
    loop = QEventLoop()  # 도구모음이 실제로 배치될 시간을 준다
    QTimer.singleShot(250, loop.quit)
    loop.exec()
    try:
        toolbar = window.findChildren(QToolBar)[0]
        assert toolbar.sizeHint().width() <= 1500

        hidden = [
            action.text()
            for action in toolbar.actions()
            if not action.isSeparator()
            and (button := toolbar.widgetForAction(action)) is not None
            and not button.isVisible()
        ]
        assert hidden == []
    finally:
        window.project.mark_dirty(False)
        window.close()
