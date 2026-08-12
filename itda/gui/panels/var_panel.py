"""실행 상태 패널 — 현재 상황 배지 + 변수 워치.

실행 중에 "지금 타겟 프로그램이 어떤 화면으로 판정되고 있는지" 와 "변수 값이 어떻게 변하는지"
를 본다. 이벤트 버스만 구독하므로 데모 재생과 2차 실행 엔진 모두에서 그대로 동작한다.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from itda.core.events import BUS
from itda.gui import style


class VarPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._values: dict[str, object] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.state_badge = QLabel("상황 —")
        self.state_badge.setStyleSheet(
            f"background: {style.SURFACE_ALT.name()}; color: {style.TEXT_DIM.name()};"
            "border-radius: 9px; padding: 4px 10px;"
        )
        head.addWidget(self.state_badge)

        self.flow_badge = QLabel("정지")
        self.flow_badge.setStyleSheet(
            f"background: {style.SURFACE_ALT.name()}; color: {style.TEXT_DIM.name()};"
            "border-radius: 9px; padding: 4px 10px;"
        )
        head.addWidget(self.flow_badge)
        head.addStretch(1)
        layout.addLayout(head)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["변수", "값"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 150)
        layout.addWidget(self.tree, 1)

        BUS.variables.connect(self._on_variables)
        BUS.state_detected.connect(self._on_state)
        BUS.flow_running.connect(self._on_flow_running)

    # ------------------------------------------------------------

    def _on_variables(self, _flow: str, values: dict) -> None:
        changed = {k for k, v in values.items() if self._values.get(k) != v}
        self._values = dict(values)

        self.tree.clear()
        for name in sorted(values):
            item = QTreeWidgetItem(self.tree, [name, str(values[name])])
            if name in changed:
                item.setForeground(1, QColor(style.ACCENT))
            item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))

    def _on_state(self, _state_id: str, name: str) -> None:
        self.state_badge.setText(f"상황 · {name or '—'}")
        self.state_badge.setStyleSheet(
            f"background: {style.ACCENT.name()}; color: #1d222d;"
            "border-radius: 9px; padding: 4px 10px; font-weight: 600;"
        )

    def _on_flow_running(self, flow: str, running: bool) -> None:
        if running:
            self.flow_badge.setText(f"실행 중 · {flow}")
            self.flow_badge.setStyleSheet(
                f"background: {style.STATUS_COLORS['ok'].name()}; color: #1d222d;"
                "border-radius: 9px; padding: 4px 10px; font-weight: 600;"
            )
        else:
            self.flow_badge.setText("정지")
            self.flow_badge.setStyleSheet(
                f"background: {style.SURFACE_ALT.name()}; color: {style.TEXT_DIM.name()};"
                "border-radius: 9px; padding: 4px 10px;"
            )

    def clear(self) -> None:
        self._values.clear()
        self.tree.clear()
