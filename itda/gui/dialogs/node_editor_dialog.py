"""노드 편집 창.

플로우차트에서 노드를 더블클릭하면 열린다. 노드 안을 하나의 작은 편집 화면으로 다룬다.

    [액션 팔레트]  |  [액션 시퀀스 카드]  |  [속성]

오른쪽 속성은 선택한 대상을 따라간다 — 카드를 고르면 그 액션, 아무것도 고르지 않으면 노드
자체(제목·상황 조건·타이밍·예외 처리). 편집은 플로우 캔버스와 **같은 되돌리기 스택**을 쓰므로
창을 닫은 뒤에도 Ctrl+Z 로 되돌릴 수 있다.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from itda.core import registry
from itda.gui import icons, style
from itda.gui.canvas.sequence_scene import SequenceScene, SequenceView
from itda.gui.dialogs import localize
from itda.gui.panels.palette import PalettePanel
from itda.gui.panels.property_panel import PropertyPanel
from itda.gui.widgets.schema_form import FormContext


class NodeEditorDialog(QDialog):
    """노드 하나를 편집한다."""

    def __init__(self, host, node, context: FormContext, parent=None) -> None:
        super().__init__(parent)
        self.host = host
        self.node = node
        self.context = context

        spec = registry.node_type(node.type)
        self.setWindowTitle(f"노드 편집 — {node.title or (spec.label if spec else node.type)}")
        self.resize(1180, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(self._build_header(spec))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_palette())
        splitter.addWidget(self._build_sequence())
        splitter.addWidget(self._build_properties())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([230, 420, 420])
        layout.addWidget(splitter, 1)

        buttons = localize(QDialogButtonBox(QDialogButtonBox.StandardButton.Close))
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._install_shortcuts()
        self._show_node()

    # ------------------------------------------------------------ 구성

    def _build_header(self, spec) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(8)

        icon = QLabel()
        color = style.node_color(self.node.type, spec.color if spec else "#4a6fa5")
        icon.setPixmap(icons.node_icon(self.node.type, color).pixmap(20, 20))
        row.addWidget(icon)

        self.title_label = QLabel()
        self.title_label.setProperty("role", "title")
        row.addWidget(self.title_label)

        row.addStretch(1)

        self.node_button = QToolButton()
        self.node_button.setText("노드 속성")
        self.node_button.setToolTip("제목·상황 조건·타이밍·예외 처리를 편집합니다")
        self.node_button.clicked.connect(self._show_node)
        row.addWidget(self.node_button)

        for icon_name, tip, slot in (
            ("copy", "선택 액션 복제 (Ctrl+D)", lambda: self.sequence.duplicate_selected()),
            ("minus", "선택 액션 삭제 (Delete)", lambda: self.sequence.delete_selected()),
        ):
            button = QToolButton()
            button.setIcon(icons.icon(icon_name, style.TEXT))
            button.setIconSize(QSize(16, 16))
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
        return box

    def _build_palette(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        caption = QLabel("액션 팔레트")
        caption.setProperty("role", "hint")
        layout.addWidget(caption)

        self.palette = PalettePanel(actions_only=True)
        layout.addWidget(self.palette, 1)
        return box

    def _build_sequence(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.caption = QLabel()
        self.caption.setProperty("role", "hint")
        layout.addWidget(self.caption)

        self.sequence = SequenceScene(self.host, self.node)
        self.sequence.action_selected.connect(self._on_action_selected)
        self.sequence.changed_actions.connect(self._refresh_caption)
        self.view = SequenceView(self.sequence)
        layout.addWidget(self.view, 1)
        return box

    def _build_properties(self) -> QWidget:
        self.properties = PropertyPanel()
        self.properties.set_scene(self.host, self.context)
        self.properties.edited.connect(self._on_edited)
        return self.properties

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+D"), self, lambda: self.sequence.duplicate_selected())
        QShortcut(QKeySequence.StandardKey.Undo, self, self._undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self._redo)

    # ------------------------------------------------------------ 반응

    def _undo(self) -> None:
        self.host.undo_stack.undo()
        self.sequence.rebuild()
        self._refresh_caption()

    def _redo(self) -> None:
        self.host.undo_stack.redo()
        self.sequence.rebuild()
        self._refresh_caption()

    def _on_action_selected(self, action) -> None:
        if action is None:
            self._show_node()
        else:
            self.properties.show_action(self.node, action)

    def _on_edited(self) -> None:
        """속성이 바뀌면 카드의 요약도 따라 바뀐다."""
        for card in self.sequence.cards:
            card.setToolTip(card._tooltip())
            card.update()
        self._refresh_caption()

    def _show_node(self) -> None:
        self.sequence.clearSelection()
        self.properties.show_node(self.node)
        self._refresh_caption()

    def _refresh_caption(self) -> None:
        spec = registry.node_type(self.node.type)
        title = self.node.title or (spec.label if spec else self.node.type)
        self.title_label.setText(title)
        self.setWindowTitle(f"노드 편집 — {title}")

        count = len(self.node.actions)
        if spec is not None and not spec.allows_actions:
            self.caption.setText(f"'{spec.label}' 노드는 액션을 담지 않습니다 — 설정은 오른쪽에서")
            self.view.setEnabled(False)
            self.palette.setEnabled(False)
        else:
            self.caption.setText(f"실행 순서 — 액션 {count}개 (끌어서 순서 변경, 더블클릭으로 켜고 끄기)")
