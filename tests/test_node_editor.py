"""노드 편집 창 테스트 — 팔레트 + 액션 시퀀스 카드 + 속성."""

from __future__ import annotations

import pytest

from itda.core import registry
from itda.core.model import Action, Node
from itda.gui.canvas.sequence_scene import CARD_GAP, CARD_HEIGHT, MARGIN_TOP, SequenceScene
from itda.gui.dialogs.node_editor_dialog import NodeEditorDialog
from itda.gui.widgets.schema_form import FormContext


@pytest.fixture
def node(scene):
    target = scene.flow.nodes[1]
    target.title = "로그인"
    target.actions = [
        Action(type="click", params=registry.action_params("click", None)),
        Action(type="type_text", params=registry.action_params("type_text", {"text": "가나"})),
    ]
    return target


@pytest.fixture
def sequence(qapp, scene, node):
    return SequenceScene(scene, node)


@pytest.fixture
def dialog(qapp, scene, node):
    return NodeEditorDialog(scene, node, FormContext())


# ---------------------------------------------------------------- 시퀀스 씬


def test_one_card_per_action(sequence, node):
    assert len(sequence.cards) == len(node.actions)
    assert [card.action for card in sequence.cards] == node.actions


def test_cards_are_stacked_top_to_bottom(sequence):
    ys = [card.pos().y() for card in sequence.cards]
    assert ys == sorted(ys)
    assert ys[1] - ys[0] == CARD_HEIGHT + CARD_GAP


def test_card_shows_label_and_summary(sequence):
    card = sequence.cards[1]
    assert card.label() == "문자 입력"
    assert "가나" in card.summary()


def test_add_action_at_the_end(sequence, node):
    sequence.add_action("sleep")
    assert [a.type for a in node.actions] == ["click", "type_text", "sleep"]
    assert len(sequence.cards) == 3


def test_add_action_at_a_position(sequence, node):
    sequence.add_action("sleep", index=1)
    assert [a.type for a in node.actions] == ["click", "sleep", "type_text"]


def test_unknown_action_type_is_ignored(sequence, node):
    assert sequence.add_action("존재하지않음") is None
    assert len(node.actions) == 2


def test_drop_index_follows_the_y_position(sequence):
    assert sequence.drop_index_at(0) == 0
    assert sequence.drop_index_at(MARGIN_TOP + CARD_HEIGHT + CARD_GAP) == 1
    assert sequence.drop_index_at(99999) == 2  # 맨 끝


def test_move_action_reorders(sequence, node):
    sequence.move_action(0, 1)
    assert [a.type for a in node.actions] == ["type_text", "click"]


def test_remove_action(sequence, node):
    sequence.remove_action(node.actions[0])
    assert [a.type for a in node.actions] == ["type_text"]


def test_toggle_enabled(sequence, node):
    assert node.actions[0].enabled is True
    sequence.toggle_enabled(node.actions[0])
    assert node.actions[0].enabled is False


def test_duplicate_keeps_params_but_new_id(sequence, node):
    sequence.select_action(node.actions[1])
    sequence.duplicate_selected()

    assert len(node.actions) == 3
    original, copy = node.actions[1], node.actions[2]
    assert copy.id != original.id
    assert copy.params["text"] == "가나"
    copy.params["text"] = "다름"
    assert original.params["text"] == "가나"


def test_edits_share_the_flow_undo_stack(sequence, scene, node):
    """창을 닫은 뒤에도 Ctrl+Z 로 되돌릴 수 있어야 한다."""
    before = len(node.actions)
    sequence.add_action("beep")
    assert len(node.actions) == before + 1

    scene.undo_stack.undo()
    assert len(node.actions) == before


def test_selection_signal(sequence, node):
    seen = []
    sequence.action_selected.connect(seen.append)

    sequence.select_action(node.actions[1])

    assert seen and seen[-1] is node.actions[1]


# ---------------------------------------------------------------- 편집 창


def test_dialog_has_palette_sequence_and_properties(dialog):
    assert dialog.palette.actions_only is True
    assert len(dialog.sequence.cards) == 2
    assert dialog.properties is not None


def test_palette_in_actions_only_mode_hides_nodes(dialog):
    from itda.gui.panels.palette import ROLE_PAYLOAD

    tree = dialog.palette.tree
    payloads = []
    for i in range(tree.topLevelItemCount()):
        root = tree.topLevelItem(i)
        for j in range(root.childCount()):
            payloads.append(root.child(j).data(0, ROLE_PAYLOAD))

    assert payloads
    assert all(p.startswith("action:") for p in payloads)


def test_dialog_starts_on_node_properties(dialog, node):
    assert dialog.properties.node is node
    assert dialog.properties.action is None


def test_selecting_a_card_switches_properties_to_that_action(dialog, node):
    dialog.sequence.select_action(node.actions[0])
    assert dialog.properties.action is node.actions[0]


def test_clearing_selection_returns_to_node_properties(dialog, node):
    dialog.sequence.select_action(node.actions[0])
    dialog.sequence.clearSelection()
    assert dialog.properties.action is None
    assert dialog.properties.node is node


def test_caption_counts_actions(dialog, node):
    dialog._refresh_caption()
    assert "2개" in dialog.caption.text()

    dialog.sequence.add_action("beep")
    assert "3개" in dialog.caption.text()


def test_dialog_undo_redo_rebuilds_cards(dialog, node):
    dialog.sequence.add_action("beep")
    assert len(dialog.sequence.cards) == 3

    dialog._undo()
    assert len(dialog.sequence.cards) == 2

    dialog._redo()
    assert len(dialog.sequence.cards) == 3


def test_node_without_actions_disables_the_sequence(qapp, scene):
    from PyQt6.QtCore import QPointF

    gate = scene.add_node("state_gate", QPointF(0, 0))
    dialog = NodeEditorDialog(scene, gate, FormContext())

    assert dialog.view.isEnabled() is False
    assert dialog.palette.isEnabled() is False
    assert "담지 않습니다" in dialog.caption.text()


def test_title_follows_the_node(qapp, scene, node):
    dialog = NodeEditorDialog(scene, node, FormContext())
    assert "로그인" in dialog.windowTitle()

    node.title = "바뀐 이름"
    dialog._refresh_caption()
    assert "바뀐 이름" in dialog.windowTitle()


@pytest.fixture
def window(qapp):
    from itda.gui.main_window import MainWindow

    w = MainWindow(restore_recent=False)
    yield w
    w.project.mark_dirty(False)
    w.close()


def test_double_click_opens_the_editor_for_that_node(window):
    """플로우 캔버스에서 더블클릭 → 그 노드의 편집 창."""
    opened = {}

    def fake_exec(self):
        opened["title"] = self.windowTitle()
        opened["node"] = getattr(self, "node", None)
        return 0

    # QDialog.exec 를 직접 갈아 끼우면 안 된다. 저장해 둔 값을 되돌려 놔도 원래의 슬롯이
    # 아니라 타입에 묶인 래퍼가 들어가서, 이후 모든 테스트에서 dialog.exec() 가 깨진다.
    # 파이썬 하위 클래스에 얹었다 지우면 상속이 그대로 복구된다.
    NodeEditorDialog.exec = fake_exec
    try:
        scene = window.current_scene()
        target = scene.flow.nodes[1]
        target.title = "더블클릭 대상"
        window._on_node_double_clicked(target.id)
    finally:
        del NodeEditorDialog.exec

    assert opened.get("node") is target
    assert "더블클릭 대상" in opened.get("title", "")


def test_patching_dialog_exec_in_tests_does_not_leak(qapp):
    """앞 테스트가 QDialog.exec 를 되돌리지 못하면 뒤 테스트들이 조용히 깨진다."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QDialog

    probe = QDialog()
    QTimer.singleShot(0, lambda: probe.done(3))
    assert probe.exec() == 3
