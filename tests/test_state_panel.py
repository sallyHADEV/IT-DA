"""상황 편집 패널 / 타이밍 프로파일 / 멀티 플로우 설정 테스트."""

from __future__ import annotations

import pytest

from itda.core.model import Action, Condition, State, Transition
from itda.gui.dialogs.flow_entries_dialog import FlowEntriesDialog
from itda.gui.dialogs.timing_dialog import TimingProfileDialog
from itda.gui.panels.state_panel import StatePanel
from itda.gui.widgets.schema_form import FormContext


@pytest.fixture
def panel(qapp, project):
    context = FormContext(objects=lambda: [o.name for o in project.objects.objects])
    return StatePanel(project, context)


def _add_state(project, name: str) -> State:
    state = State(name=name)
    project.states.states.append(state)
    return state


# ---------------------------------------------------------------- 상황


def test_states_are_listed(panel, project):
    _add_state(project, "메인")
    _add_state(project, "설정창")
    panel.reload()
    assert panel.state_list.count() == 2


def test_selecting_state_builds_condition_tree(panel, project):
    state = _add_state(project, "설정창")
    state.condition = Condition(
        op="and",
        items=[
            Condition(type="object_visible", params={"object": "설정제목"}),
            Condition(type="window_title", params={"contains": "메모장"}),
        ],
    )
    panel.reload()
    panel.select_state(state.id)

    root = panel.cond_tree.topLevelItem(0)
    assert root.childCount() == 2
    assert "설정제목" in root.child(0).text(0)


def test_add_condition_into_selected_group(panel, project):
    state = _add_state(project, "설정창")
    panel.reload()
    panel.select_state(state.id)

    panel.add_condition()

    assert len(state.condition.items) == 1
    assert state.condition.items[0].op == "leaf"
    assert panel.cond_tree.topLevelItem(0).childCount() == 1


def test_add_or_group_and_nest_condition(panel, project):
    state = _add_state(project, "설정창")
    panel.reload()
    panel.select_state(state.id)

    panel.add_group("or")
    panel.add_condition()  # OR 묶음이 선택된 상태이므로 그 안으로 들어가야 한다

    assert state.condition.items[0].op == "or"
    assert len(state.condition.items[0].items) == 1


def test_changing_condition_type_resets_params(panel, project):
    state = _add_state(project, "설정창")
    panel.reload()
    panel.select_state(state.id)
    panel.add_condition()
    condition = state.condition.items[0]
    assert condition.type == "object_visible"

    index = panel.cond_type.findData("window_title")
    panel.cond_type.setCurrentIndex(index)

    assert condition.type == "window_title"
    assert "contains" in condition.params
    assert "object" not in condition.params


def test_negate_marks_condition(panel, project):
    state = _add_state(project, "설정창")
    panel.reload()
    panel.select_state(state.id)
    panel.add_condition()

    panel.cond_negate.setChecked(True)

    assert state.condition.items[0].negate is True
    assert "NOT" in panel.cond_tree.topLevelItem(0).child(0).text(0)


def test_delete_condition_but_not_root(panel, project):
    state = _add_state(project, "설정창")
    panel.reload()
    panel.select_state(state.id)
    panel.add_condition()

    panel.delete_condition()
    assert state.condition.items == []

    panel.cond_tree.setCurrentItem(panel.cond_tree.topLevelItem(0))
    panel.delete_condition()  # 최상위 묶음은 남아야 한다
    assert state.condition is not None


def test_condition_param_edit_updates_label(panel, project):
    state = _add_state(project, "설정창")
    panel.reload()
    panel.select_state(state.id)
    panel.add_condition()
    condition = state.condition.items[0]

    panel._on_condition_param(condition, "object", "설정_제목")

    assert condition.params["object"] == "설정_제목"
    assert "설정_제목" in panel.cond_tree.topLevelItem(0).child(0).text(0)


def test_condition_form_is_replaced_not_stacked(panel, project):
    """조건을 갈아탈 때 이전 폼이 남아 겹치면 안 된다."""
    from itda.gui.widgets.schema_form import SchemaForm

    state = _add_state(project, "설정창")
    panel.reload()
    panel.select_state(state.id)
    panel.add_condition()
    panel.add_condition()

    root = panel.cond_tree.topLevelItem(0)
    panel.cond_tree.setCurrentItem(root.child(0))
    panel.cond_tree.setCurrentItem(root.child(1))

    assert len(panel.cond_form_box.findChildren(SchemaForm)) == 1


def test_interrupt_switch_marks_the_state(panel, project):
    """끼어드는 화면(팝업) 표시 — 실행 중 최우선으로 처리된다."""
    state = _add_state(project, "광고팝업")
    panel.reload()
    panel.select_state(state.id)
    assert panel.interrupt_row.isChecked() is False

    panel.interrupt_row.setChecked(True)
    panel._on_interrupt_toggled(True)

    assert state.interrupt is True
    assert "⚡" in panel.state_list.item(0).text()
    assert "끼어드는 화면" in panel.state_list.item(0).toolTip()


def test_interrupt_flag_is_saved(project, tmp_path):
    from itda.core.project import Project

    state = _add_state(project, "업데이트알림")
    state.interrupt = True
    project.save(tmp_path / "p")

    loaded = Project.load(tmp_path / "p")
    assert loaded.states.states[0].interrupt is True


def test_priority_edit(panel, project):
    state = _add_state(project, "설정창")
    panel.reload()
    panel.select_state(state.id)

    panel.priority.setValue(7)

    assert state.priority == 7


# ---------------------------------------------------------------- 전이


def test_add_transition_between_states(panel, project):
    main = _add_state(project, "메인")
    _add_state(project, "설정창")
    panel.reload()
    panel.select_state(main.id)

    panel.add_transition()

    assert len(project.states.transitions) == 1
    assert project.states.transitions[0].src == main.id
    assert panel.transition_list.count() == 1


def test_transition_target_and_cost_edit(panel, project):
    main = _add_state(project, "메인")
    settings = _add_state(project, "설정창")
    _add_state(project, "출력창")
    panel.reload()
    panel.select_state(main.id)
    panel.add_transition()

    index = panel.transition_target.findData(settings.id)
    panel.transition_target.setCurrentIndex(index)
    panel.transition_cost.setValue(2.5)

    transition = project.states.transitions[0]
    assert transition.dst == settings.id
    assert transition.cost == 2.5


def test_delete_transition(panel, project):
    main = _add_state(project, "메인")
    _add_state(project, "설정창")
    panel.reload()
    panel.select_state(main.id)
    panel.add_transition()
    panel.transition_list.setCurrentRow(0)

    panel.delete_transition()

    assert project.states.transitions == []


def test_deleting_state_removes_its_transitions(panel, project, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    main = _add_state(project, "메인")
    other = _add_state(project, "설정창")
    project.states.transitions.append(Transition(src=main.id, dst=other.id))
    project.states.transitions.append(Transition(src=other.id, dst=main.id))
    panel.reload()
    panel.select_state(main.id)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    panel.delete_state()

    assert [s.name for s in project.states.states] == ["설정창"]
    assert project.states.transitions == []


def test_transition_actions_are_editable_like_node_actions(qapp, project):
    """전이의 이동 동작도 노드와 같은 액션 목록 위젯으로 편집된다."""
    from itda.gui.commands import EditHost
    from itda.gui.panels.action_list import ActionListPanel

    transition = Transition(src="a", dst="b")
    host = EditHost(project)
    panel = ActionListPanel()
    panel.set_scene(host)
    panel.set_node(transition)

    panel.add_action("click")
    panel.add_action("sleep")

    assert [a.type for a in transition.actions] == ["click", "sleep"]
    assert panel.list.count() == 2

    host.undo_stack.undo()
    assert [a.type for a in transition.actions] == ["click"]


def test_transition_summary_counts_actions(panel, project):
    main = _add_state(project, "메인")
    other = _add_state(project, "설정창")
    transition = Transition(src=main.id, dst=other.id, actions=[Action(type="click")])
    project.states.transitions.append(transition)
    panel.reload()
    panel.select_state(main.id)

    assert "동작 1개" in panel.transition_list.item(0).text()


# ---------------------------------------------------------------- 워처


def test_watcher_settings_persist(panel, project):
    panel.watch_interval.setValue(1200)
    panel.watch_unknown.setText("모르는화면")
    panel._on_watcher_changed()

    assert project.states.watcher.interval_ms == 1200
    assert project.states.watcher.unknown_name == "모르는화면"


# ---------------------------------------------------------------- 타이밍 프로파일


def test_timing_dialog_applies_profile(qapp, project):
    dialog = TimingProfileDialog(project)
    dialog.jitter.setValue(0.4)
    dialog.click_offset.setValue(6)
    dialog.post_ms.setValue(250)

    dialog.accept()

    profile = project.settings.timing
    assert profile.jitter_pct == 0.4
    assert profile.click_offset_px == 6
    assert profile.default_post_ms == 250
    assert project.dirty


def test_timing_change_affects_inheriting_nodes(qapp, project):
    """원클릭 전체 적용 — 상속 중인 노드의 실제 값이 함께 바뀌어야 한다."""
    from itda.core.timing import resolve

    node = project.flow("main").nodes[1]
    assert node.post.inherit

    dialog = TimingProfileDialog(project)
    dialog.post_ms.setValue(500)
    dialog.accept()

    assert resolve(node.post, project.settings.timing).post_ms == 500


def test_timing_reset_to_defaults(qapp, project):
    from itda.core.timing import TimingProfile

    dialog = TimingProfileDialog(project)
    dialog.jitter.setValue(0.9)
    dialog.reset_defaults()
    assert dialog.result_profile() == TimingProfile()


# ---------------------------------------------------------------- 멀티 플로우


def test_flow_entries_dialog_lists_and_saves(qapp, project):
    key, _ = project.add_flow("보조 루틴")
    dialog = FlowEntriesDialog(project)

    assert dialog.table.rowCount() == 1  # create_default 가 main 하나를 넣어 둔다

    dialog.add_row()
    combo = dialog.table.cellWidget(1, 0)
    combo.setCurrentIndex(combo.findText(key))
    dialog.table.cellWidget(1, 2).setChecked(True)  # 자동 시작
    dialog.table.cellWidget(1, 4).setValue(5)       # 우선순위

    dialog.accept()

    entries = {e.flow: e for e in project.settings.entries}
    assert set(entries) == {"main", key}
    assert entries[key].autostart is True
    assert entries[key].priority == 5


def test_flow_entries_remove_row(qapp, project):
    dialog = FlowEntriesDialog(project)
    dialog.table.selectRow(0)
    dialog.remove_selected()
    dialog.accept()

    assert project.settings.entries == []
