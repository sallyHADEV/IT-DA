"""액션 시퀀스 편집 대화상자.

플로우 캔버스 밖에서 액션 목록을 편집할 때 쓴다 — 지금은 상황 전이(A 화면에서 B 화면으로
가기 위해 할 동작)가 유일한 사용처다. 캔버스와 같은 위젯(액션 목록 + 속성 폼)을 그대로
재사용하므로 조작 방법이 다르지 않다.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QSplitter,
    QVBoxLayout,
)

from itda.gui.commands import EditHost
from itda.gui.dialogs import localize
from itda.gui.panels.action_list import ActionListPanel
from itda.gui.panels.property_panel import PropertyPanel
from itda.gui.widgets.schema_form import FormContext


class ActionEditorDialog(QDialog):
    """``actions`` 리스트를 가진 임의의 객체를 편집한다."""

    def __init__(self, owner, project, context: FormContext, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(940, 620)
        self.owner = owner
        self.host = EditHost(project, on_changed=self._on_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        hint = QLabel(
            "이 동작들은 상황을 옮길 때 실행됩니다. 예: 메인 화면에서 '설정' 버튼을 클릭."
        )
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.action_panel = ActionListPanel()
        self.action_panel.set_scene(self.host)
        self.action_panel.set_node(owner)
        self.action_panel.action_selected.connect(self._on_action_selected)
        splitter.addWidget(self.action_panel)

        self.property_panel = PropertyPanel()
        self.property_panel.set_scene(self.host, context)
        splitter.addWidget(self.property_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        buttons = localize(QDialogButtonBox(QDialogButtonBox.StandardButton.Close))
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _on_action_selected(self, owner, action) -> None:
        if action is None:
            self.property_panel.show_none()
        else:
            self.property_panel.show_action(owner, action)

    def _on_changed(self) -> None:
        self.action_panel.refresh_labels()
