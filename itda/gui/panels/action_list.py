"""노드 내부 액션 시퀀스 편집기.

"개별 노드가 모듈형으로 작동(개별 노드 속에 여러 동작을 구성)" 을 담당하는 패널이다.
노드를 선택하면 그 안의 액션들이 실행 순서대로 나열되고, 끌어서 순서를 바꿀 수 있다.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from itda.core import registry
from itda.core.model import Action, Node
from itda.core.serde import clone
from itda.gui import icons, style
from itda.gui.commands import (
    AddActionCommand,
    MoveActionCommand,
    RemoveActionCommand,
    SetAttrCommand,
)

ROLE_ACTION_ID = Qt.ItemDataRole.UserRole + 1


class ActionListPanel(QWidget):
    """액션 시퀀스 목록.

    주 대상은 노드지만, ``actions`` 리스트와 ``action(id)`` 를 가진 것이면 무엇이든 편집할 수
    있다 — 상황 전이(Transition)의 이동 동작도 같은 위젯으로 편집한다.
    """

    action_selected = pyqtSignal(object, object)  # (소유자, Action | None)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.scene = None
        self.node: Node | None = None
        self._syncing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.title = QLabel("노드를 선택하세요")
        self.title.setProperty("role", "hint")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setAlternatingRowColors(True)
        self.list.setIconSize(QSize(17, 17))
        self.list.setSpacing(1)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self.list, 1)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.btn_add = self._button("plus", "액션 추가", self._show_add_menu)
        self.btn_dup = self._button("copy", "선택 액션 복제", self.duplicate_selected)
        self.btn_del = self._button("minus", "선택 액션 삭제", self.delete_selected)
        self.btn_up = self._button("up", "위로", lambda: self.move_selected(-1))
        self.btn_down = self._button("down", "아래로", lambda: self.move_selected(1))
        for b in (self.btn_add, self.btn_dup, self.btn_del, self.btn_up, self.btn_down):
            bar.addWidget(b)
        bar.addStretch(1)
        layout.addLayout(bar)

        self._update_enabled()

    def _button(self, icon_name: str, tip: str, slot) -> QToolButton:
        """도구 버튼. 글리프 문자는 폰트에 없으면 네모로 나오므로 벡터 아이콘을 쓴다."""
        b = QToolButton()
        b.setIcon(icons.icon(icon_name, style.TEXT))
        b.setIconSize(QSize(16, 16))
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    # ------------------------------------------------------------ 표시

    def set_scene(self, scene) -> None:
        self.scene = scene
        self.set_node(None)

    def set_node(self, node: Node | None) -> None:
        self.node = node
        self.reload()

    def _owner_spec(self):
        """노드면 노드 타입, 그 외(전이 등)이면 None."""
        return registry.node_type(getattr(self.node, "type", "")) if self.node else None

    def _owner_title(self) -> str:
        return getattr(self.node, "title", "") or getattr(self.node, "note", "") or "액션"

    def reload(self) -> None:
        self._syncing = True
        self.list.clear()

        node = self.node
        if node is None:
            self.title.setText("노드를 선택하세요")
        else:
            spec = self._owner_spec()
            if spec is not None and not spec.allows_actions:
                self.title.setText(f"'{spec.label}' 노드는 액션을 담지 않습니다")
            else:
                self.title.setText(f"{self._owner_title()} — 액션 {len(node.actions)}개")
                for index, action in enumerate(node.actions):
                    self.list.addItem(self._make_item(index, action))

        self._syncing = False
        self._update_enabled()

    def refresh_labels(self) -> None:
        """선택과 포커스를 건드리지 않고 항목 글자만 갱신한다.

        속성 패널에서 타이핑하는 중에도 요약이 따라 바뀌어야 하므로, 목록을 다시 만들면
        안 된다(선택이 초기화되고 폼이 재생성되어 입력이 끊긴다).
        """
        if self.node is None:
            return
        if self.list.count() != len(self.node.actions):
            self.reload()
            return
        self._syncing = True
        for i, action in enumerate(self.node.actions):
            item = self.list.item(i)
            fresh = self._make_item(i, action)
            item.setText(fresh.text())
            item.setToolTip(fresh.toolTip())
            item.setForeground(fresh.foreground())
            item.setFont(fresh.font())
            item.setIcon(fresh.icon())
            item.setCheckState(fresh.checkState())
            item.setData(ROLE_ACTION_ID, action.id)
        self.title.setText(f"{self._owner_title()} — 액션 {len(self.node.actions)}개")
        self._syncing = False

    def _make_item(self, index: int, action: Action) -> QListWidgetItem:
        at = registry.action_type(action.type)
        label = action.title or (at.LABEL if at else action.type)
        summary = registry.action_summary(action.type, action.params)
        item = QListWidgetItem(f"{index + 1}. {label} — {summary}")
        item.setData(ROLE_ACTION_ID, action.id)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if action.enabled else Qt.CheckState.Unchecked)
        item.setToolTip(f"{at.HELP if at else ''}\n{summary}".strip())

        # 종류는 아이콘 색으로 구분하고 글자는 밝게 둔다.
        # 글자에 종류 색을 쓰면 어두운 배경에서 읽기 힘들다.
        accent = QColor(at.COLOR if at else "#7a8ba6")
        item.setIcon(
            icons.action_icon(action.type, at.CATEGORY if at else "기타",
                              accent if action.enabled else style.TEXT_FAINT)
        )
        item.setForeground(style.TEXT if action.enabled else style.TEXT_FAINT)
        if not action.enabled:
            font = QFont()
            font.setStrikeOut(True)
            item.setFont(font)
        return item

    def current_action(self) -> Action | None:
        item = self.list.currentItem()
        if item is None or self.node is None:
            return None
        return self.node.action(item.data(ROLE_ACTION_ID))

    def select_action(self, action_id: str) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(ROLE_ACTION_ID) == action_id:
                self.list.setCurrentRow(i)
                return

    def _update_enabled(self) -> None:
        spec = self._owner_spec()
        can_edit = self.node is not None and (spec is None or spec.allows_actions)
        has_sel = self.list.currentItem() is not None
        self.btn_add.setEnabled(can_edit)
        for b in (self.btn_dup, self.btn_del, self.btn_up, self.btn_down):
            b.setEnabled(can_edit and has_sel)

    # ------------------------------------------------------------ 편집

    def _show_add_menu(self) -> None:
        if self.node is None or self.scene is None:
            return
        menu = QMenu(self)
        for category, actions in registry.actions_by_category().items():
            sub = menu.addMenu(category)
            for at in actions:
                act = sub.addAction(f"{at.ICON}  {at.LABEL}")
                act.setToolTip(at.HELP)
                act.triggered.connect(lambda _=False, t=at.ID: self.add_action(t))
        menu.exec(self.btn_add.mapToGlobal(self.btn_add.rect().bottomLeft()))

    def add_action(self, type_id: str) -> None:
        at = registry.action_type(type_id)
        if at is None or self.node is None or self.scene is None:
            return
        action = Action(type=type_id, params=at.defaults())
        index = self.list.currentRow() + 1 if self.list.currentRow() >= 0 else len(self.node.actions)
        self.scene.undo_stack.push(AddActionCommand(self.scene, self.node, action, index))
        self.reload()
        self.select_action(action.id)

    def duplicate_selected(self) -> None:
        action = self.current_action()
        if action is None or self.node is None or self.scene is None:
            return
        copy = clone(action)
        copy.id = Action().id
        index = self.node.actions.index(action) + 1
        self.scene.undo_stack.push(AddActionCommand(self.scene, self.node, copy, index))
        self.reload()
        self.select_action(copy.id)

    def delete_selected(self) -> None:
        action = self.current_action()
        if action is None or self.node is None or self.scene is None:
            return
        self.scene.undo_stack.push(RemoveActionCommand(self.scene, self.node, action))
        self.reload()

    def move_selected(self, delta: int) -> None:
        action = self.current_action()
        if action is None or self.node is None or self.scene is None:
            return
        old = self.node.actions.index(action)
        new = old + delta
        if not 0 <= new < len(self.node.actions):
            return
        self.scene.undo_stack.push(MoveActionCommand(self.scene, self.node, old, new))
        self.reload()
        self.select_action(action.id)

    # ------------------------------------------------------------ 이벤트

    def _on_rows_moved(self, _parent, start: int, _end: int, _dest, row: int) -> None:
        """드래그로 순서를 바꿨을 때 모델에 반영한다."""
        if self._syncing or self.node is None or self.scene is None:
            return
        target = row - 1 if row > start else row
        if target == start:
            self.reload()
            return
        self.scene.undo_stack.push(MoveActionCommand(self.scene, self.node, start, target))
        self.reload()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """체크박스로 액션을 켜고 끈다."""
        if self._syncing or self.node is None or self.scene is None:
            return
        action = self.node.action(item.data(ROLE_ACTION_ID))
        if action is None:
            return
        enabled = item.checkState() == Qt.CheckState.Checked
        if enabled != action.enabled:
            self.scene.undo_stack.push(
                SetAttrCommand(self.scene, action, "enabled", enabled, "액션 사용 전환")
            )
            self.reload()
            self.select_action(action.id)

    def _on_current_changed(self, current, _previous) -> None:
        self._update_enabled()
        if self._syncing:
            return
        self.action_selected.emit(self.node, self.current_action())

    def _context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            self._show_add_menu()
            return
        self.list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("속성 편집", lambda: self.action_selected.emit(self.node, self.current_action()))
        menu.addAction("복제", self.duplicate_selected)
        menu.addSeparator()
        menu.addAction("위로", lambda: self.move_selected(-1))
        menu.addAction("아래로", lambda: self.move_selected(1))
        menu.addSeparator()
        menu.addAction("삭제", self.delete_selected)
        menu.exec(self.list.mapToGlobal(pos))
