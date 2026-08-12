"""속성 패널.

선택된 노드나 액션의 속성을 보여준다. 액션 파라미터 폼은 레지스트리의 스키마로 자동
생성되므로, 액션을 새로 만들어도 이 파일은 손대지 않는다.

노드 자체의 속성(제목·상황·타이밍·예외처리)도 같은 폼 엔진을 쓴다. 다만 값이 params
딕셔너리가 아니라 데이터클래스 속성에 있으므로 ``"pre.inherit"`` 같은 점 표기 경로로
읽고 쓴다.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from itda.core import registry
from itda.core.model import Action, Node
from itda.core.schema import Field
from itda.core.timing import describe
from itda.gui import icons, style
from itda.gui.commands import SetAttrCommand, SetParamCommand
from itda.gui.widgets.schema_form import FormContext, SchemaForm

# ---------------------------------------------------------------- 노드 공통 스키마
# 이름이 곧 대상 속성의 경로다. "pre.inherit" 은 node.pre.inherit 을 가리킨다.

NODE_BASIC = [
    Field("title", "str", "제목"),
    Field("note", "text", "메모"),
]

NODE_STATE = [
    Field("required_state", "state_ref", "필요 상황",
          help="이 상황에서만 노드를 실행합니다. 비우면 상황을 따지지 않습니다."),
    Field(
        "on_wrong_state",
        "enum",
        "상황이 다르면",
        "navigate",
        options=[
            ("navigate", "전이 경로로 이동 후 실행"),
            ("wait", "그 상황이 될 때까지 대기"),
            ("skip", "이 노드를 건너뜀"),
            ("fail", "실패로 처리"),
        ],
    ),
    Field("state_timeout_ms", "int", "제한시간", 10000, minimum=0, maximum=600000, suffix=" ms"),
]

NODE_TIMING = [
    Field("pre.inherit", "bool", "선딜레이 프로파일 상속", True),
    Field("pre.pre_ms", "int", "동작 전 대기", 0, minimum=0, maximum=600000, suffix=" ms",
          depends_on=("pre.inherit", False)),
    Field("post.inherit", "bool", "후딜레이 프로파일 상속", True),
    Field("post.post_ms", "int", "동작 후 대기", 0, minimum=0, maximum=600000, suffix=" ms",
          depends_on=("post.inherit", False)),
]

NODE_ERROR = [
    Field("retry.count", "int", "노드 재시도 횟수", 0, minimum=0, maximum=100,
          help="노드 안의 모든 동작이 실패했을 때 노드 전체를 처음부터 다시 실행하는 횟수입니다."),
    Field("retry.interval_ms", "int", "노드 재시도 간격", 500, minimum=0, maximum=600000, suffix=" ms",
          help="노드 전체 재실행 사이의 대기 시간입니다. 이미지 찾기 내부 재시도와는 별개입니다."),
    Field(
        "on_error.mode",
        "enum",
        "에러가 나면",
        "fail_port",
        options=[
            ("fail_port", "실패 출구로 진행"),
            ("goto", "지정 노드로 이동"),
            ("continue", "무시하고 계속"),
            ("stop", "이 플로우 중단"),
            ("raise_up", "상위 플로우로 전달"),
        ],
    ),
    Field("on_error.target", "node_ref", "이동할 노드", "", depends_on=("on_error.mode", "goto")),
    Field("on_error.capture_screenshot", "bool", "화면 저장", False),
    Field("on_error.message", "str", "로그 메시지", ""),
]

ACTION_TIMING = [
    Field("timing.inherit", "bool", "타이밍 프로파일 상속", True),
    Field("timing.pre_ms", "int", "동작 전 대기", 0, minimum=0, maximum=600000, suffix=" ms",
          depends_on=("timing.inherit", False)),
    Field("timing.post_ms", "int", "동작 후 대기", 0, minimum=0, maximum=600000, suffix=" ms",
          depends_on=("timing.inherit", False)),
]


def get_path(target: Any, path: str) -> Any:
    obj = target
    for part in path.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def owner_of(target: Any, path: str) -> tuple[Any, str]:
    """``"pre.inherit"`` → (node.pre, "inherit")."""
    parts = path.split(".")
    obj = target
    for part in parts[:-1]:
        obj = getattr(obj, part)
    return obj, parts[-1]


class PropertyPanel(QWidget):
    """노드 / 액션 속성 편집기."""

    #: 편집 결과로 캔버스를 갱신해야 할 때
    edited = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.scene = None
        self.context = FormContext()
        self.node: Node | None = None
        self.action: Action | None = None
        self._forms: list[SchemaForm] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QLabel("선택 없음")
        self.header.setProperty("role", "title")
        self.header.setContentsMargins(10, 8, 10, 6)
        self.header.setWordWrap(True)
        outer.addWidget(self.header)

        self.back_bar = QWidget()
        back_layout = QHBoxLayout(self.back_bar)
        back_layout.setContentsMargins(10, 0, 10, 6)
        self.back_button = QPushButton("← 노드 속성으로")
        self.back_button.clicked.connect(self._back_to_node)
        back_layout.addWidget(self.back_button)
        back_layout.addStretch(1)
        self.back_bar.hide()
        outer.addWidget(self.back_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(self.scroll, 1)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 4, 10, 14)
        self.body_layout.setSpacing(6)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(self.body)

        self.show_none()

    # ------------------------------------------------------------ 연결

    def set_scene(self, scene, context: FormContext) -> None:
        self.scene = scene
        self.context = context
        self.show_none()

    # ------------------------------------------------------------ 표시

    def _clear(self) -> None:
        self._forms.clear()
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # 순서가 중요하다.
                #  hide()          — 아직 처리되지 않은 Show 이벤트를 취소한다. 이걸 빼면
                #                    부모를 잃은 위젯에게 뒤늦게 Show 가 도착해 **흰 창이
                #                    떴다 사라진다**(액션을 고를 때마다 반복됐다).
                #  setParent(None) — deleteLater 만으로는 삭제가 이벤트 루프까지 밀려
                #                    이전 화면이 새 내용 위에 겹쳐 그려진다.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _section(self, title: str, fields: list[Field], values: dict[str, Any],
                 on_change) -> SchemaForm:
        # 부모를 **만들 때** 준다. 부모 없이 만들면 레이아웃에 넣기 전까지 최상위 위젯이라,
        # 부모가 화면에 있는 상태에서는 흰 창이 잠깐 떴다 사라진다.
        box = QGroupBox(title, self.body)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 6, 10, 8)
        form = SchemaForm(fields, self.context, box)
        form.load(values)
        form.value_changed.connect(on_change)
        layout.addWidget(form)
        self.body_layout.addWidget(box)
        self._forms.append(form)
        return form

    def show_none(self) -> None:
        self.node = None
        self.action = None
        self._clear()
        self.back_bar.hide()
        self.header.setText("선택 없음")
        hint = QLabel("캔버스에서 노드를 선택하거나, 팔레트에서 노드를 끌어다 놓으세요.", self.body)
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body_layout.addWidget(hint)
        self.body_layout.addStretch(1)

    def show_node(self, node: Node) -> None:
        self.node = node
        self.action = None
        self._clear()
        self.back_bar.hide()

        spec = registry.node_type(node.type)
        color = style.node_color(node.type, spec.color if spec else "#4a6fa5")
        self.header.setText(
            f"<span style='color:{color.name()}'>{spec.icon if spec else '▢'}</span> "
            f"{node.title or (spec.label if spec else node.type)}"
            f"<br><span style='color:{style.TEXT_FAINT.name()};font-size:11px'>"
            f"{spec.label if spec else node.type} · {node.id}</span>"
        )

        values = {f.name: get_path(node, f.name) for f in NODE_BASIC}
        self._section("기본", NODE_BASIC, values, self._on_node_attr)

        if spec and spec.params:
            form = self._section("설정", spec.params, node.params, self._on_node_param)
            if node.type == "window":
                self._add_window_picker(form, self._apply_window_pick_to_node)

        if spec is None or spec.allows_state:
            state_values = {f.name: get_path(node, f.name) for f in NODE_STATE}
            self._section("상황 조건", NODE_STATE, state_values, self._on_node_attr)

        if spec is None or spec.allows_actions:
            timing_values = {f.name: get_path(node, f.name) for f in NODE_TIMING}
            form = self._section("타이밍", NODE_TIMING, timing_values, self._on_node_attr)
            self._add_hint(form, self._timing_hint())

            error_values = {f.name: get_path(node, f.name) for f in NODE_ERROR}
            self._section("예외 처리", NODE_ERROR, error_values, self._on_node_attr)

        self.body_layout.addStretch(1)

    def show_action(self, node: Node, action: Action) -> None:
        self.node = node
        self.action = action
        self._clear()
        self.back_bar.show()

        at = registry.action_type(action.type)
        color = QColor(at.COLOR if at else "#7a8ba6")
        self.header.setText(
            f"<span style='color:{color.name()}'>{at.ICON if at else '•'}</span> "
            f"{action.title or (at.LABEL if at else action.type)}"
            f"<br><span style='color:{style.TEXT_FAINT.name()};font-size:11px'>"
            f"{getattr(node, 'title', '') or '전이'} 안의 액션</span>"
        )

        if at is None:
            warn = QLabel(f"등록되지 않은 액션 타입입니다: {action.type}", self.body)
            warn.setStyleSheet(f"color: {style.LEVEL_COLORS['error'].name()}")
            warn.setWordWrap(True)
            self.body_layout.addWidget(warn)
            self.body_layout.addStretch(1)
            return

        if at.HELP:
            # 설명은 맨 위에 둔다 — 무슨 액션인지 먼저 읽고 설정으로 내려가는 순서가 자연스럽다
            hint = QLabel(at.HELP, self.body)
            hint.setProperty("role", "hint")
            hint.setWordWrap(True)
            self.body_layout.addWidget(hint)

        head_fields = [
            Field("title", "str", "이름", help="비우면 액션 종류 이름을 씁니다."),
            Field("enabled", "bool", "사용", True),
        ]
        if at.HAS_OUTPUT:
            head_fields.append(
                Field("out_var", "var", "결과를 담을 변수",
                      help="비우면 결과를 저장하지 않습니다.")
            )
        head_values = {f.name: getattr(action, f.name, None) for f in head_fields}
        self._section("액션", head_fields, head_values, self._on_action_attr)

        if at.PARAMS:
            form = self._section("파라미터", at.PARAMS, action.params, self._on_action_param)
            if action.type == "window":
                self._add_window_picker(form, self._apply_window_pick_to_action)

        timing_values = {f.name: get_path(action, f.name) for f in ACTION_TIMING}
        form = self._section("타이밍", ACTION_TIMING, timing_values, self._on_action_attr)
        self._add_hint(form, self._timing_hint())

        self.body_layout.addStretch(1)

    def _add_hint(self, form: SchemaForm, text: str) -> None:
        label = QLabel(text, form.parentWidget())
        label.setProperty("role", "hint")
        label.setWordWrap(True)
        parent_layout = form.parentWidget().layout()
        parent_layout.addWidget(label)

    def _add_window_picker(self, form: SchemaForm, apply_fn) -> None:
        """제목·좌표·크기를 한 번에 채우는 "창 선택" 버튼을 섹션 맨 위에 끼워 넣는다.

        스크린샷 도구처럼 화면을 얼리고 창을 호버링하면 붉은 테두리로 보여 주다가,
        클릭한 창의 정보를 가져온다(:mod:`itda.gui.tools.window_picker`). 필드 하나가
        아니라 제목·일치방식·위치·크기 네 칸을 한꺼번에 바꾸므로, 스키마가 자동 생성하는
        낱개 편집기로는 안 되고 패널이 직접 만든다.
        """
        button = QPushButton("창 선택 — 화면에서 호버 후 클릭")
        button.setIcon(icons.icon("window", style.TEXT))
        button.setToolTip(
            "열려 있는 창 위에 마우스를 올리면 빨간 테두리로 표시됩니다.\n"
            "클릭하면 그 창의 이름·위치·크기를 제목·좌표·크기 칸에 채웁니다."
        )
        # 도구가 주입되지 않았으면 눌러도 아무 일이 없다 — 다른 도구 버튼과 같이 꺼 둔다
        button.setEnabled(self.context.pick_window is not None)
        button.clicked.connect(lambda: self._pick_window(apply_fn))
        layout = form.parentWidget().layout()
        layout.insertWidget(0, button)

    def _pick_window(self, apply_fn) -> None:
        if self.context.pick_window is None:
            return
        picked = self.context.pick_window()
        if picked is None:
            return
        apply_fn(*picked)

    def _apply_window_pick_to_node(self, title: str, x: int, y: int, w: int, h: int) -> None:
        if self.node is None:
            return
        self._push_window_pick(self.node, title, x, y, w, h)
        self.show_node(self.node)  # 새 값으로 폼을 다시 그린다 (헤더의 제목도 함께)

    def _apply_window_pick_to_action(self, title: str, x: int, y: int, w: int, h: int) -> None:
        if self.action is None or self.node is None:
            return
        self._push_window_pick(self.action, title, x, y, w, h)
        self.show_action(self.node, self.action)

    def _push_window_pick(self, owner, title: str, x: int, y: int, w: int, h: int) -> None:
        """제목·일치방식·위치·크기를 되돌리기 한 번으로 묶어 넣는다."""
        if self.scene is None:
            return
        stack = self.scene.undo_stack
        stack.beginMacro("창 선택으로 채우기")
        try:
            for key, value in (
                ("title", title),
                ("match", "exact"),  # 그대로 가져온 제목이니 정확히 일치가 안전하다
                ("point", [x, y]),
                ("size", [w, h]),
            ):
                stack.push(SetParamCommand(self.scene, owner, key, value, f"{key} 변경"))
        finally:
            stack.endMacro()
        self.edited.emit()

    def _timing_hint(self) -> str:
        if self.scene is None:
            return ""
        profile = self.scene.project.settings.timing
        target = self.action.timing if self.action else (self.node.pre if self.node else None)
        return "현재 적용값 — " + describe(target, profile)

    def _back_to_node(self) -> None:
        if self.node is not None:
            self.show_node(self.node)

    def refresh_choices(self) -> None:
        for form in self._forms:
            form.refresh_choices()

    # ------------------------------------------------------------ 편집 반영

    def _push(self, command) -> None:
        if self.scene is not None:
            self.scene.undo_stack.push(command)
        self.edited.emit()

    def _on_node_attr(self, path: str, value: Any) -> None:
        if self.node is None:
            return
        owner, attr = owner_of(self.node, path)
        self._push(SetAttrCommand(self.scene, owner, attr, value, f"노드 {attr} 변경"))
        if path == "title":
            self.header.setText(self.header.text())  # 헤더는 다음 선택 때 갱신된다

    def _on_node_param(self, name: str, value: Any) -> None:
        if self.node is None:
            return
        self._push(SetParamCommand(self.scene, self.node, name, value, f"노드 설정 {name} 변경"))

    def _on_action_attr(self, path: str, value: Any) -> None:
        if self.action is None:
            return
        owner, attr = owner_of(self.action, path)
        self._push(SetAttrCommand(self.scene, owner, attr, value, f"액션 {attr} 변경"))

    def _on_action_param(self, name: str, value: Any) -> None:
        if self.action is None:
            return
        self._push(SetParamCommand(self.scene, self.action, name, value, f"액션 {name} 변경"))
