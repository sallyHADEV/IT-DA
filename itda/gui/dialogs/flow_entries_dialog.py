"""멀티 플로우 실행 설정.

"복수의 매크로가 동시에 동작하게 구성할 수 있고, 우선순위를 가져갈 수 있음" 에 해당한다.
여기서 정한 목록이 project.json 에 저장되고, 2차의 스케줄러가 그대로 읽어 실행한다.

우선순위는 마우스·키보드처럼 하나뿐인 자원을 누가 먼저 쓰는지를 정한다. 숫자가 클수록 먼저다.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from itda.core.model import FlowEntry
from itda.gui.dialogs import localize

COLUMNS = ["플로우", "사용", "자동 시작", "반복", "우선순위"]


class FlowEntriesDialog(QDialog):
    def __init__(self, project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("멀티 플로우 실행 설정")
        self.project = project
        self.resize(620, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)

        hint = QLabel(
            "여러 매크로를 동시에 돌릴 수 있습니다. 우선순위가 높은 플로우가 마우스·키보드를 먼저 씁니다."
        )
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        bar = QHBoxLayout()
        add = QPushButton("＋ 항목 추가")
        add.clicked.connect(self.add_row)
        remove = QPushButton("선택 삭제")
        remove.clicked.connect(self.remove_selected)
        bar.addWidget(add)
        bar.addWidget(remove)
        bar.addStretch(1)
        layout.addLayout(bar)

        buttons = localize(
            QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.load()

    # ------------------------------------------------------------

    def load(self) -> None:
        self.table.setRowCount(0)
        for entry in self.project.settings.entries:
            self._append_row(entry)

    def add_row(self) -> None:
        keys = self.project.flow_keys()
        self._append_row(FlowEntry(flow=keys[0] if keys else ""))

    def _append_row(self, entry: FlowEntry) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        combo = QComboBox()
        combo.addItems(self.project.flow_keys())
        index = combo.findText(entry.flow)
        if index < 0 and entry.flow:
            combo.addItem(entry.flow)
            index = combo.count() - 1
        combo.setCurrentIndex(max(0, index))
        self.table.setCellWidget(row, 0, combo)

        for column, checked in ((1, entry.enabled), (2, entry.autostart), (3, entry.loop)):
            box = QCheckBox()
            box.setChecked(checked)
            box.setStyleSheet("margin-left: 12px;")
            self.table.setCellWidget(row, column, box)

        spin = QSpinBox()
        spin.setRange(-10, 10)
        spin.setValue(entry.priority)
        spin.setToolTip("클수록 먼저 입력 장치를 차지합니다.")
        self.table.setCellWidget(row, 4, spin)

        self.table.setItem(row, 0, QTableWidgetItem())
        self.table.item(row, 0).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def entries(self) -> list[FlowEntry]:
        result: list[FlowEntry] = []
        for row in range(self.table.rowCount()):
            flow = self.table.cellWidget(row, 0).currentText()
            if not flow:
                continue
            result.append(
                FlowEntry(
                    flow=flow,
                    enabled=self.table.cellWidget(row, 1).isChecked(),
                    autostart=self.table.cellWidget(row, 2).isChecked(),
                    loop=self.table.cellWidget(row, 3).isChecked(),
                    priority=self.table.cellWidget(row, 4).value(),
                )
            )
        return result

    def accept(self) -> None:
        self.project.settings.entries = self.entries()
        self.project.mark_dirty()
        super().accept()
