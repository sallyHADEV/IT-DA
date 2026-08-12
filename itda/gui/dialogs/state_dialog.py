"""상황 관리 대화상자 — :class:`~itda.gui.panels.state_panel.StatePanel` 을 감싼 창."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

from itda.gui.dialogs import localize
from itda.gui.panels.state_panel import StatePanel
from itda.gui.widgets.schema_form import FormContext


class StateDialog(QDialog):
    def __init__(self, project, context: FormContext, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("상황 관리")
        self.resize(1040, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.panel = StatePanel(project, context)
        layout.addWidget(self.panel, 1)

        buttons = localize(QDialogButtonBox(QDialogButtonBox.StandardButton.Close))
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
