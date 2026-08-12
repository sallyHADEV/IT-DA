"""로그 패널 — 이벤트 버스의 로그를 그대로 보여준다."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from itda.core.events import BUS, LogRecord
from itda.gui import style

MAX_ROWS = 3000
LEVEL_ORDER = {"debug": 0, "info": 1, "warn": 2, "error": 3}


class LogPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._records: list[LogRecord] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.filter_text = QLineEdit()
        self.filter_text.setPlaceholderText("로그 검색")
        self.filter_text.setClearButtonEnabled(True)
        self.filter_text.textChanged.connect(self._refilter)
        bar.addWidget(self.filter_text, 1)

        self.only_problems = QCheckBox("경고·오류만")
        self.only_problems.toggled.connect(self._refilter)
        bar.addWidget(self.only_problems)

        self.autoscroll = QCheckBox("자동 스크롤")
        self.autoscroll.setChecked(True)
        bar.addWidget(self.autoscroll)

        clear = QPushButton("지우기")
        clear.clicked.connect(self.clear)
        bar.addWidget(clear)
        layout.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["시각", "위치", "내용"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 96)
        self.tree.setColumnWidth(1, 190)
        layout.addWidget(self.tree, 1)

        BUS.logged.connect(self.append)

    # ------------------------------------------------------------

    def append(self, record: LogRecord) -> None:
        self._records.append(record)
        if len(self._records) > MAX_ROWS:
            self._records = self._records[-MAX_ROWS:]
            self._rebuild()
            return
        item = self._make_item(record)
        if item is not None and self.autoscroll.isChecked():
            self.tree.scrollToBottom()

    def _make_item(self, record: LogRecord) -> QTreeWidgetItem | None:
        if not self._passes(record):
            return None
        where = " / ".join(x for x in (record.flow, record.node, record.action) if x)
        item = QTreeWidgetItem(self.tree, [record.time_text(), where, record.message])
        color = style.LEVEL_COLORS.get(record.level, style.TEXT)
        for col in range(3):
            item.setForeground(col, QColor(color))
        item.setTextAlignment(0, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        return item

    def _passes(self, record: LogRecord) -> bool:
        if self.only_problems.isChecked() and LEVEL_ORDER.get(record.level, 1) < 2:
            return False
        text = self.filter_text.text().strip().lower()
        if text and text not in f"{record.message} {record.flow} {record.node}".lower():
            return False
        return True

    def _refilter(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        self.tree.clear()
        for record in self._records:
            self._make_item(record)
        if self.autoscroll.isChecked():
            self.tree.scrollToBottom()

    def clear(self) -> None:
        self._records.clear()
        self.tree.clear()
