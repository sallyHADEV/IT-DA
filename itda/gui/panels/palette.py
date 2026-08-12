"""팔레트 — 노드와 액션을 캔버스로 끌어다 놓는 목록.

레지스트리를 그대로 읽으므로, 액션을 새로 등록하면 여기에 자동으로 나타난다.
"""

from __future__ import annotations

from PyQt6.QtCore import QMimeData, QSize, Qt
from PyQt6.QtGui import QDrag, QFont, QPixmap
from PyQt6.QtWidgets import (
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from itda.core import registry
from itda.gui import icons, style
from itda.gui.canvas.view import PALETTE_MIME

ROLE_PAYLOAD = Qt.ItemDataRole.UserRole + 1


class PalettePanel(QWidget):
    """노드/액션 팔레트.

    Args:
        actions_only: 참이면 액션만 보여 준다. 노드 편집 창처럼 액션만 놓을 수 있는 곳에서 쓴다.
    """

    def __init__(self, parent=None, actions_only: bool = False) -> None:
        super().__init__(parent)
        self.actions_only = actions_only
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText("노드 · 액션 검색")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.tree = _PaletteTree()
        layout.addWidget(self.tree, 1)

        self.reload()

    def reload(self) -> None:
        self.tree.clear()

        if not self.actions_only:
            node_root = self._category("노드", "노드는 흐름의 단위입니다. 캔버스로 끌어다 놓으세요.")
            for type_id, spec in registry.NODE_TYPES.items():
                item = QTreeWidgetItem(node_root, [spec.label])
                item.setData(0, ROLE_PAYLOAD, f"node:{type_id}")
                item.setToolTip(0, spec.help or spec.label)
                # 종류 구분은 아이콘 색으로. 글자는 어두운 배경에서도 읽히도록 밝게 둔다.
                item.setIcon(0, icons.node_icon(type_id, spec.color))
                item.setForeground(0, style.TEXT)

        hint = (
            "액션을 순서 안의 원하는 자리에 끌어다 놓으세요."
            if self.actions_only
            else "액션을 캔버스에 놓으면 그 액션을 담은 동작 노드가 만들어집니다."
        )
        for category, actions in registry.actions_by_category().items():
            root = self._category(f"액션 · {category}", hint)
            for at in actions:
                item = QTreeWidgetItem(root, [at.LABEL])
                item.setData(0, ROLE_PAYLOAD, f"action:{at.ID}")
                item.setToolTip(0, at.HELP or at.LABEL)
                item.setIcon(0, icons.action_icon(at.ID, at.CATEGORY, at.COLOR))
                item.setForeground(0, style.TEXT)

        self.tree.expandAll()

    def _category(self, title: str, tip: str) -> QTreeWidgetItem:
        root = QTreeWidgetItem(self.tree, [title])
        font = QFont()
        font.setBold(True)
        root.setFont(0, font)
        root.setForeground(0, style.TEXT_DIM)
        root.setFlags(Qt.ItemFlag.ItemIsEnabled)
        root.setToolTip(0, tip)
        return root

    def _filter(self, text: str) -> None:
        text = (text or "").strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            visible_children = 0
            for j in range(root.childCount()):
                child = root.child(j)
                match = not text or text in child.text(0).lower()
                child.setHidden(not match)
                visible_children += int(match)
            root.setHidden(visible_children == 0)
        if text:
            self.tree.expandAll()


class _PaletteTree(QTreeWidget):
    """드래그 소스."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragOnly)
        self.setIndentation(8)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setIconSize(QSize(17, 17))

    def startDrag(self, actions) -> None:
        item = self.currentItem()
        payload = item.data(0, ROLE_PAYLOAD) if item else None
        if not payload:
            return
        mime = QMimeData()
        mime.setData(PALETTE_MIME, payload.encode("utf-8"))
        mime.setText(item.text(0).strip())

        drag = QDrag(self)
        drag.setMimeData(mime)
        pixmap = QPixmap(4, 4)
        pixmap.fill(Qt.GlobalColor.transparent)
        drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.CopyAction)
