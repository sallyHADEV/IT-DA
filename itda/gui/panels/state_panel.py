"""상황(State) 편집 패널 — 이 도구의 간판 기능.

타겟 프로그램이 지금 어떤 화면인지 이름 붙여 정의하고(판정 조건), 그 화면들 사이를 어떻게
오가는지 적어 둔다(전이). 그러면 노드는 "이 동작은 설정창에서만" 이라고 선언하기만 하면 되고,
실행 엔진이 알아서 설정창으로 이동한 뒤 동작한다.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from itda.core import registry
from itda.core.model import Condition, State, Transition
from itda.gui import icons, style
from itda.gui.widgets.schema_form import FormContext, SchemaForm
from itda.gui.widgets.toggle_switch import SwitchRow

ROLE_ID = Qt.ItemDataRole.UserRole + 1
ROLE_COND = Qt.ItemDataRole.UserRole + 2

GROUP_LABELS = {"and": "모두 참 (AND)", "or": "하나라도 참 (OR)", "not": "아님 (NOT)"}


class StatePanel(QWidget):
    """상황 목록 + 판정 조건 트리 + 전이 편집."""

    states_changed = pyqtSignal()

    def __init__(self, project=None, context: FormContext | None = None, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.context = context or FormContext()
        self._current: State | None = None
        self._cond_form: SchemaForm | None = None
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_state_list())
        splitter.addWidget(self._build_detail())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)
        layout.addWidget(self._build_watcher())

        if project is not None:
            self.set_project(project)

    # ------------------------------------------------------------ 좌측: 상황 목록

    def _build_state_list(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(6)

        title = QLabel("상황")
        title.setProperty("role", "title")
        layout.addWidget(title)

        self.state_list = QListWidget()
        self.state_list.currentItemChanged.connect(self._on_state_selected)
        layout.addWidget(self.state_list, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        for icon_name, tip, slot in (
            ("plus", "상황 추가", self.add_state),
            ("edit", "이름 변경", self.rename_state),
            ("minus", "삭제", self.delete_state),
        ):
            button = QToolButton()
            button.setIcon(icons.icon(icon_name, style.TEXT))
            button.setIconSize(QSize(16, 16))
            button.setToolTip(tip)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return box

    # ------------------------------------------------------------ 우측: 상세

    def _build_detail(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_condition_tab(), "판정 조건")
        self.tabs.addTab(self._build_transition_tab(), "전이")
        return self.tabs

    def _build_condition_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        hint = QLabel("이 조건이 모두 맞으면 지금 화면을 이 상황으로 판정합니다.")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        head = QHBoxLayout()
        head.setSpacing(4)
        self.priority = QSpinBox()
        self.priority.setRange(-100, 100)
        self.priority.setToolTip("여러 상황이 동시에 참이면 우선순위가 큰 쪽으로 판정합니다.")
        self.priority.valueChanged.connect(self._on_priority_changed)
        head.addWidget(QLabel("우선순위"))
        head.addWidget(self.priority)
        head.addStretch(1)
        layout.addLayout(head)

        self.interrupt_row = SwitchRow(
            "bell",
            "끼어드는 화면",
            "광고·업데이트 팝업처럼 아무 때나 뜨는 화면입니다. 켜면 실행 중 이 화면이 감지될 때 "
            "하던 일을 멈추고 먼저 닫은 뒤, 원래 목표로 돌아갑니다. "
            "빠져나가는 전이(닫기 동작)를 반드시 등록하세요.",
        )
        self.interrupt_row.toggled.connect(self._on_interrupt_toggled)
        layout.addWidget(self.interrupt_row)

        self.cond_tree = QTreeWidget()
        self.cond_tree.setHeaderHidden(True)
        self.cond_tree.setIconSize(QSize(16, 16))
        self.cond_tree.currentItemChanged.connect(self._on_condition_selected)
        layout.addWidget(self.cond_tree, 2)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        for text, tip, slot in (
            ("조건 추가", "선택한 묶음 안에 조건을 추가합니다", self.add_condition),
            ("AND 묶음", "모두 참이어야 하는 묶음", lambda: self.add_group("and")),
            ("OR 묶음", "하나라도 참이면 되는 묶음", lambda: self.add_group("or")),
            ("삭제", "선택 항목 삭제", self.delete_condition),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.cond_type = QComboBox()
        for type_id, ct in registry.CONDITION_TYPES.items():
            self.cond_type.addItem(icons.condition_icon(type_id, style.TEXT), ct.LABEL, type_id)
        self.cond_type.currentIndexChanged.connect(self._on_condition_type_changed)

        self.cond_negate = QPushButton("결과 뒤집기 (NOT)")
        self.cond_negate.setCheckable(True)
        self.cond_negate.toggled.connect(self._on_negate_toggled)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("조건 종류"))
        type_row.addWidget(self.cond_type, 1)
        type_row.addWidget(self.cond_negate)
        layout.addLayout(type_row)

        self.cond_form_box = QGroupBox("조건 설정")
        self.cond_form_layout = QVBoxLayout(self.cond_form_box)
        self.cond_form_layout.setContentsMargins(10, 6, 10, 8)
        layout.addWidget(self.cond_form_box, 1)
        return page

    def _build_transition_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        hint = QLabel(
            "이 상황에서 다른 상황으로 가는 방법입니다. 실행 엔진이 최소 비용 경로를 찾아 "
            "필요한 화면으로 스스로 이동합니다."
        )
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.transition_list = QListWidget()
        self.transition_list.currentItemChanged.connect(self._on_transition_selected)
        self.transition_list.itemDoubleClicked.connect(lambda _: self.edit_transition_actions())
        layout.addWidget(self.transition_list, 1)

        form = QFormLayout()
        form.setSpacing(6)
        self.transition_target = QComboBox()
        self.transition_target.currentIndexChanged.connect(self._on_transition_changed)
        form.addRow("도착 상황", self.transition_target)

        self.transition_cost = QDoubleSpinBox()
        self.transition_cost.setRange(0.1, 1000.0)
        self.transition_cost.setSingleStep(0.5)
        self.transition_cost.setToolTip("여러 경로가 있을 때 비용이 낮은 쪽을 고릅니다.")
        self.transition_cost.valueChanged.connect(self._on_transition_changed)
        form.addRow("비용", self.transition_cost)

        self.transition_settle = QSpinBox()
        self.transition_settle.setRange(0, 600000)
        self.transition_settle.setSuffix(" ms")
        self.transition_settle.setToolTip("이동 후 화면이 바뀔 때까지 기다리는 시간")
        self.transition_settle.valueChanged.connect(self._on_transition_changed)
        form.addRow("정착 대기", self.transition_settle)

        self.transition_note = QLineEdit()
        self.transition_note.editingFinished.connect(self._on_transition_changed)
        form.addRow("메모", self.transition_note)
        layout.addLayout(form)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        add = QPushButton("＋ 전이 추가")
        add.clicked.connect(self.add_transition)
        remove = QPushButton("삭제")
        remove.clicked.connect(self.delete_transition)
        self.btn_edit_actions = QPushButton("이동 동작 편집…")
        self.btn_edit_actions.setProperty("accent", True)
        self.btn_edit_actions.clicked.connect(self.edit_transition_actions)
        bar.addWidget(add)
        bar.addWidget(remove)
        bar.addStretch(1)
        bar.addWidget(self.btn_edit_actions)
        layout.addLayout(bar)
        return page

    def _build_watcher(self) -> QWidget:
        box = QGroupBox("상황 감시")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(8)

        self.watch_enabled = QPushButton("주기 판별 사용")
        self.watch_enabled.setCheckable(True)
        self.watch_enabled.toggled.connect(self._on_watcher_changed)
        layout.addWidget(self.watch_enabled)

        layout.addWidget(QLabel("주기"))
        self.watch_interval = QSpinBox()
        self.watch_interval.setRange(50, 60000)
        self.watch_interval.setSuffix(" ms")
        self.watch_interval.valueChanged.connect(self._on_watcher_changed)
        layout.addWidget(self.watch_interval)

        layout.addWidget(QLabel("모르는 화면 이름"))
        self.watch_unknown = QLineEdit()
        self.watch_unknown.setMaximumWidth(140)
        self.watch_unknown.editingFinished.connect(self._on_watcher_changed)
        layout.addWidget(self.watch_unknown)

        layout.addWidget(QLabel("복구 플로우"))
        self.watch_recovery = QComboBox()
        self.watch_recovery.setMinimumWidth(120)
        self.watch_recovery.currentIndexChanged.connect(self._on_watcher_changed)
        layout.addWidget(self.watch_recovery)
        layout.addStretch(1)
        return box

    # ------------------------------------------------------------ 로드

    def set_project(self, project, context: FormContext | None = None) -> None:
        self.project = project
        if context is not None:
            self.context = context
        self.reload()

    def reload(self) -> None:
        if self.project is None:
            return
        self._loading = True

        current_id = self._current.id if self._current else None
        self.state_list.clear()
        for state in self.project.states.states:
            label = f"⚡ {state.name}" if state.interrupt else state.name
            item = QListWidgetItem(label)
            item.setData(ROLE_ID, state.id)
            item.setForeground(QColor(state.color or style.ACCENT.name()))
            count = len(self.project.states.transitions_from(state.id))
            kind = "끼어드는 화면 · " if state.interrupt else ""
            item.setToolTip(f"{kind}우선순위 {state.priority} · 나가는 전이 {count}개")
            self.state_list.addItem(item)
            if state.id == current_id:
                self.state_list.setCurrentItem(item)

        watcher = self.project.states.watcher
        self.watch_enabled.setChecked(watcher.enabled)
        self.watch_enabled.setText("주기 판별 사용" if watcher.enabled else "주기 판별 꺼짐")
        self.watch_interval.setValue(watcher.interval_ms)
        self.watch_unknown.setText(watcher.unknown_name)
        self.watch_recovery.clear()
        self.watch_recovery.addItem("(없음)", "")
        for key in self.project.flow_keys():
            self.watch_recovery.addItem(key, key)
        index = self.watch_recovery.findData(watcher.recovery_flow)
        self.watch_recovery.setCurrentIndex(max(0, index))

        self._loading = False
        if self.state_list.currentItem() is None:
            self._show_state(None)

    # ------------------------------------------------------------ 상황 편집

    def add_state(self) -> None:
        if self.project is None:
            return
        name, ok = QInputDialog.getText(self, "상황 추가", "이름 (예: 설정창):")
        if not ok or not name.strip():
            return
        state = State(name=name.strip())
        self.project.states.states.append(state)
        self._touch()
        self.reload()
        self.select_state(state.id)

    def rename_state(self) -> None:
        if self._current is None:
            return
        name, ok = QInputDialog.getText(self, "이름 변경", "이름:", text=self._current.name)
        if not ok or not name.strip():
            return
        self._current.name = name.strip()
        self._touch()
        self.reload()

    def delete_state(self) -> None:
        if self._current is None or self.project is None:
            return
        answer = QMessageBox.question(
            self,
            "상황 삭제",
            f"'{self._current.name}' 을 삭제할까요?\n이 상황을 쓰는 노드와 전이는 검사에서 경고로 표시됩니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        graph = self.project.states
        graph.states.remove(self._current)
        graph.transitions = [
            t for t in graph.transitions if self._current.id not in (t.src, t.dst)
        ]
        self._current = None
        self._touch()
        self.reload()

    def select_state(self, state_id: str) -> None:
        for i in range(self.state_list.count()):
            if self.state_list.item(i).data(ROLE_ID) == state_id:
                self.state_list.setCurrentRow(i)
                return

    def _on_state_selected(self, current, _previous) -> None:
        if self._loading or self.project is None:
            return
        state = self.project.states.state(current.data(ROLE_ID)) if current else None
        self._show_state(state)

    def _show_state(self, state: State | None) -> None:
        self._current = state
        self._loading = True
        enabled = state is not None
        for widget in (self.cond_tree, self.priority, self.cond_type, self.cond_negate,
                       self.interrupt_row, self.transition_list, self.transition_target,
                       self.transition_cost):
            widget.setEnabled(enabled)

        if state is None:
            self.cond_tree.clear()
            self.transition_list.clear()
            self._clear_condition_form()
            self._loading = False
            return

        self.priority.setValue(state.priority)
        self.interrupt_row.setChecked(state.interrupt)
        self._rebuild_condition_tree()
        self._rebuild_transitions()
        self._loading = False

    def _on_priority_changed(self, value: int) -> None:
        if self._loading or self._current is None:
            return
        self._current.priority = value
        self._touch()

    def _on_interrupt_toggled(self, checked: bool) -> None:
        if self._loading or self._current is None:
            return
        self._current.interrupt = checked
        self._touch()
        self.reload()

    # ------------------------------------------------------------ 조건 트리

    def _rebuild_condition_tree(self) -> None:
        self.cond_tree.clear()
        if self._current is None:
            return
        root_item = self._make_condition_item(self._current.condition, None)
        self.cond_tree.expandAll()
        self.cond_tree.setCurrentItem(root_item)

    def _make_condition_item(self, condition: Condition, parent) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent or self.cond_tree)
        item.setData(0, ROLE_COND, condition)
        self._label_condition(item, condition)
        for child in condition.items:
            self._make_condition_item(child, item)
        return item

    def _label_condition(self, item: QTreeWidgetItem, condition: Condition) -> None:
        if condition.op in GROUP_LABELS:
            text = GROUP_LABELS[condition.op]
            font = QFont()
            font.setBold(True)
            item.setFont(0, font)
            item.setForeground(0, style.TEXT_DIM)
            item.setIcon(0, icons.icon("layers", style.TEXT_DIM))
        else:
            text = registry.condition_summary(condition.type, condition.params)
            item.setForeground(0, style.TEXT)
            item.setIcon(
                0,
                icons.condition_icon(
                    condition.type, style.ACCENT if condition.negate else style.TEXT_DIM
                ),
            )
        if condition.negate:
            text = f"아님(NOT) · {text}"
            item.setForeground(0, QColor(style.ACCENT))
        item.setText(0, text)

    def _current_condition(self) -> tuple[Condition | None, QTreeWidgetItem | None]:
        item = self.cond_tree.currentItem()
        return (item.data(0, ROLE_COND) if item else None), item

    def _on_condition_selected(self, current, _previous) -> None:
        if self._loading:
            return
        condition = current.data(0, ROLE_COND) if current else None
        self._show_condition_form(condition)

    def _clear_condition_form(self) -> None:
        while self.cond_form_layout.count():
            widget = self.cond_form_layout.takeAt(0).widget()
            if widget is not None:
                # 숨긴 뒤에 떼어낸다 — 순서가 바뀌면 최상위 창으로 잠깐 깜빡인다
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._cond_form = None

    def _show_condition_form(self, condition: Condition | None) -> None:
        self._clear_condition_form()
        is_leaf = condition is not None and condition.op == "leaf"
        self.cond_type.setEnabled(is_leaf)
        self.cond_negate.setEnabled(condition is not None)

        if condition is None:
            return

        self._loading = True
        self.cond_negate.setChecked(condition.negate)
        if is_leaf:
            index = self.cond_type.findData(condition.type)
            self.cond_type.setCurrentIndex(max(0, index))
        self._loading = False

        if not is_leaf:
            hint = QLabel("묶음입니다. 안에 조건을 추가하세요.")
            hint.setProperty("role", "hint")
            self.cond_form_layout.addWidget(hint)
            return

        ct = registry.condition_type(condition.type)
        if ct is None:
            self.cond_form_layout.addWidget(QLabel(f"알 수 없는 조건: {condition.type}"))
            return

        form = SchemaForm(ct.PARAMS, self.context)
        form.load(condition.params)
        form.value_changed.connect(lambda name, value: self._on_condition_param(condition, name, value))
        self.cond_form_layout.addWidget(form)
        self._cond_form = form

    def _on_condition_param(self, condition: Condition, name: str, value) -> None:
        condition.params[name] = value
        item = self.cond_tree.currentItem()
        if item is not None:
            self._label_condition(item, condition)
        self._touch()

    def _on_condition_type_changed(self) -> None:
        if self._loading:
            return
        condition, item = self._current_condition()
        if condition is None or condition.op != "leaf":
            return
        type_id = self.cond_type.currentData()
        if type_id == condition.type:
            return
        ct = registry.condition_type(type_id)
        condition.type = type_id
        condition.params = {f.name: f.default for f in (ct.PARAMS if ct else [])}
        if item is not None:
            self._label_condition(item, condition)
        self._show_condition_form(condition)
        self._touch()

    def _on_negate_toggled(self, checked: bool) -> None:
        if self._loading:
            return
        condition, item = self._current_condition()
        if condition is None or condition.negate == checked:
            return
        condition.negate = checked
        if item is not None:
            self._label_condition(item, condition)
        self._touch()

    def _insertion_target(self) -> tuple[Condition, QTreeWidgetItem | None]:
        """선택 위치를 기준으로 새 항목을 넣을 묶음을 고른다."""
        condition, item = self._current_condition()
        if condition is not None and condition.op != "leaf":
            return condition, item
        if item is not None and item.parent() is not None:
            return item.parent().data(0, ROLE_COND), item.parent()
        return self._current.condition, self.cond_tree.topLevelItem(0)

    def add_condition(self) -> None:
        if self._current is None:
            return
        parent, parent_item = self._insertion_target()
        type_id = self.cond_type.currentData() or "object_visible"
        ct = registry.condition_type(type_id)
        condition = Condition(
            op="leaf", type=type_id, params={f.name: f.default for f in (ct.PARAMS if ct else [])}
        )
        parent.items.append(condition)
        new_item = self._make_condition_item(condition, parent_item)
        if parent_item is not None:
            parent_item.setExpanded(True)
        self.cond_tree.setCurrentItem(new_item)
        self._touch()

    def add_group(self, op: str) -> None:
        if self._current is None:
            return
        parent, parent_item = self._insertion_target()
        group = Condition(op=op)
        parent.items.append(group)
        new_item = self._make_condition_item(group, parent_item)
        if parent_item is not None:
            parent_item.setExpanded(True)
        self.cond_tree.setCurrentItem(new_item)
        self._touch()

    def delete_condition(self) -> None:
        condition, item = self._current_condition()
        if condition is None or item is None or item.parent() is None:
            return  # 최상위 묶음은 지우지 않는다
        parent = item.parent().data(0, ROLE_COND)
        if condition in parent.items:
            parent.items.remove(condition)
        item.parent().removeChild(item)
        self._touch()

    # ------------------------------------------------------------ 전이

    def _rebuild_transitions(self) -> None:
        self.transition_list.clear()
        if self._current is None or self.project is None:
            return
        graph = self.project.states
        for transition in graph.transitions_from(self._current.id):
            target = graph.state(transition.dst)
            item = QListWidgetItem(
                f"→ {target.name if target else '(없는 상황)'}"
                f"   비용 {transition.cost:g} · 동작 {len(transition.actions)}개"
            )
            item.setData(ROLE_ID, transition.id)
            self.transition_list.addItem(item)
        self._refresh_target_combo()
        self._update_transition_widgets()

    def _refresh_target_combo(self) -> None:
        if self.project is None:
            return
        self._loading = True
        current = self.transition_target.currentData()
        self.transition_target.clear()
        for state in self.project.states.states:
            self.transition_target.addItem(state.name, state.id)
        index = self.transition_target.findData(current)
        if index >= 0:
            self.transition_target.setCurrentIndex(index)
        self._loading = False

    def current_transition(self) -> Transition | None:
        item = self.transition_list.currentItem()
        if item is None or self.project is None:
            return None
        return next(
            (t for t in self.project.states.transitions if t.id == item.data(ROLE_ID)), None
        )

    def _update_transition_widgets(self) -> None:
        transition = self.current_transition()
        enabled = transition is not None
        for widget in (self.transition_target, self.transition_cost, self.transition_settle,
                       self.transition_note, self.btn_edit_actions):
            widget.setEnabled(enabled)
        if transition is None:
            return
        self._loading = True
        index = self.transition_target.findData(transition.dst)
        self.transition_target.setCurrentIndex(max(0, index))
        self.transition_cost.setValue(transition.cost)
        self.transition_settle.setValue(transition.settle_ms)
        self.transition_note.setText(transition.note)
        self._loading = False

    def _on_transition_selected(self, _current, _previous) -> None:
        if self._loading:
            return
        self._update_transition_widgets()

    def _on_transition_changed(self) -> None:
        if self._loading:
            return
        transition = self.current_transition()
        if transition is None:
            return
        transition.dst = self.transition_target.currentData() or ""
        transition.cost = round(self.transition_cost.value(), 2)
        transition.settle_ms = self.transition_settle.value()
        transition.note = self.transition_note.text()
        self._touch()
        self._rebuild_transitions()

    def add_transition(self) -> None:
        if self._current is None or self.project is None:
            return
        others = [s for s in self.project.states.states if s.id != self._current.id]
        if not others:
            QMessageBox.information(self, "상황이 더 필요합니다", "도착할 상황을 먼저 만드세요.")
            return
        transition = Transition(src=self._current.id, dst=others[0].id)
        self.project.states.transitions.append(transition)
        self._touch()
        self._rebuild_transitions()
        for i in range(self.transition_list.count()):
            if self.transition_list.item(i).data(ROLE_ID) == transition.id:
                self.transition_list.setCurrentRow(i)
                break

    def delete_transition(self) -> None:
        transition = self.current_transition()
        if transition is None or self.project is None:
            return
        self.project.states.transitions.remove(transition)
        self._touch()
        self._rebuild_transitions()

    def edit_transition_actions(self) -> None:
        transition = self.current_transition()
        if transition is None or self.project is None:
            return
        from itda.gui.dialogs.action_editor_dialog import ActionEditorDialog

        graph = self.project.states
        src = graph.state(transition.src)
        dst = graph.state(transition.dst)
        title = f"이동 동작 — {src.name if src else '?'} → {dst.name if dst else '?'}"
        dialog = ActionEditorDialog(transition, self.project, self.context, title, self)
        dialog.exec()
        self._touch()
        self._rebuild_transitions()

    # ------------------------------------------------------------ 워처

    def _on_watcher_changed(self) -> None:
        if self._loading or self.project is None:
            return
        watcher = self.project.states.watcher
        watcher.enabled = self.watch_enabled.isChecked()
        watcher.interval_ms = self.watch_interval.value()
        watcher.unknown_name = self.watch_unknown.text().strip() or "UNKNOWN"
        watcher.recovery_flow = self.watch_recovery.currentData() or ""
        self.watch_enabled.setText("주기 판별 사용" if watcher.enabled else "주기 판별 꺼짐")
        self._touch()

    # ------------------------------------------------------------

    def _touch(self) -> None:
        if self.project is not None:
            self.project.mark_dirty()
        self.states_changed.emit()
