"""프로젝트 탐색기 — 플로우 목록과 실행 항목.

플로우 하나가 파일 하나이므로 이 목록이 곧 프로젝트 폴더의 flows/ 내용이다.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from itda.gui import style

ROLE_KEY = Qt.ItemDataRole.UserRole + 1


class ProjectPanel(QWidget):
    """플로우 목록 패널."""

    flow_activated = pyqtSignal(str)
    project_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.project = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(12)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        self.btn_add = QPushButton("＋ 플로우")
        self.btn_add.clicked.connect(self.add_flow)
        self.btn_del = QPushButton("삭제")
        self.btn_del.clicked.connect(self.delete_selected)
        buttons.addWidget(self.btn_add)
        buttons.addWidget(self.btn_del)
        layout.addLayout(buttons)

    # ------------------------------------------------------------ 표시

    def set_project(self, project) -> None:
        self.project = project
        self.reload()

    def reload(self) -> None:
        self.tree.clear()
        if self.project is None:
            return

        root = QTreeWidgetItem(self.tree, ["플로우"])
        font = QFont()
        font.setBold(True)
        root.setFont(0, font)
        root.setForeground(0, style.TEXT_DIM)
        root.setFlags(Qt.ItemFlag.ItemIsEnabled)

        entries = {e.flow: e for e in self.project.settings.entries}
        for key in self.project.flow_keys():
            flow = self.project.flow(key)
            entry = entries.get(key)
            label = f"{flow.name}  ({key})" if flow.name != key else key
            item = QTreeWidgetItem(root, [label])
            item.setData(0, ROLE_KEY, key)
            marks = []
            if entry and entry.autostart:
                marks.append("자동 시작")
            if entry and entry.priority:
                marks.append(f"우선순위 {entry.priority}")
            item.setToolTip(
                0,
                "\n".join([f"노드 {len(flow.nodes)}개, 연결 {len(flow.edges)}개", *marks]),
            )
            if entry and entry.autostart:
                item.setForeground(0, QColor(style.ACCENT))
        root.setExpanded(True)

    def current_key(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, ROLE_KEY) if item else None

    # ------------------------------------------------------------ 편집

    def add_flow(self) -> None:
        if self.project is None:
            return
        name, ok = QInputDialog.getText(self, "새 플로우", "이름:", text="새 플로우")
        if not ok or not name.strip():
            return
        key, _ = self.project.add_flow(name.strip())
        self.reload()
        self.project_changed.emit()
        self.flow_activated.emit(key)

    def rename_selected(self) -> None:
        key = self.current_key()
        if not key or self.project is None:
            return
        flow = self.project.flow(key)
        name, ok = QInputDialog.getText(self, "플로우 이름 변경", "이름:", text=flow.name)
        if not ok or not name.strip():
            return
        flow.name = name.strip()
        self.project.mark_dirty()
        self.reload()
        self.project_changed.emit()

    def rename_file_key(self) -> None:
        """파일 이름(참조 키)을 바꾼다. 참조도 함께 갱신된다."""
        key = self.current_key()
        if not key or self.project is None:
            return
        new_key, ok = QInputDialog.getText(self, "파일 이름 변경", "flows/<이름>.flow.json", text=key)
        if not ok or not new_key.strip():
            return
        renamed = self.project.rename_flow(key, new_key.strip())
        self.reload()
        self.project_changed.emit()
        self.flow_activated.emit(renamed)

    def delete_selected(self) -> None:
        key = self.current_key()
        if not key or self.project is None:
            return
        if len(self.project.flows) <= 1:
            QMessageBox.information(self, "삭제할 수 없음", "플로우는 최소 하나가 있어야 합니다.")
            return
        answer = QMessageBox.question(
            self,
            "플로우 삭제",
            f"'{key}' 플로우를 삭제할까요?\n이 플로우를 호출하는 노드가 있으면 검사에서 경고가 표시됩니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.project.remove_flow(key)
        self.reload()
        self.project_changed.emit()

    def toggle_autostart(self) -> None:
        key = self.current_key()
        if not key or self.project is None:
            return
        from itda.core.model import FlowEntry

        entry = next((e for e in self.project.settings.entries if e.flow == key), None)
        if entry is None:
            entry = FlowEntry(flow=key)
            self.project.settings.entries.append(entry)
        entry.autostart = not entry.autostart
        self.project.mark_dirty()
        self.reload()
        self.project_changed.emit()

    # ------------------------------------------------------------ 이벤트

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        key = item.data(0, ROLE_KEY)
        if key:
            self.flow_activated.emit(key)

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None or not item.data(0, ROLE_KEY):
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("열기", lambda: self.flow_activated.emit(item.data(0, ROLE_KEY)))
        menu.addSeparator()
        menu.addAction("이름 변경", self.rename_selected)
        menu.addAction("파일 이름 변경", self.rename_file_key)
        menu.addAction("자동 시작 켜기/끄기", self.toggle_autostart)
        menu.addSeparator()
        menu.addAction("삭제", self.delete_selected)
        menu.exec(self.tree.mapToGlobal(pos))
