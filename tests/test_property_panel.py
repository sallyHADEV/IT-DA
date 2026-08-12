"""스키마 폼 / 속성 패널 / 액션 목록 테스트."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QObject, QPointF, Qt
from PyQt6.QtWidgets import QWidget

from itda.core import registry
from itda.core.model import Action
from itda.core.schema import Field
from itda.gui.panels.action_list import ActionListPanel
from itda.gui.panels.property_panel import PropertyPanel, get_path, owner_of
from itda.gui.widgets.schema_form import FormContext, SchemaForm


@pytest.fixture
def context(project):
    return FormContext(
        objects=lambda: [o.name for o in project.objects.objects],
        flows=lambda: project.flow_keys(),
        states=lambda: [s.name for s in project.states.states],
        nodes=lambda: [(n.id, n.title) for n in project.flow("main").nodes],
    )


# ---------------------------------------------------------------- 스키마 폼


def test_form_builds_for_every_registered_action(qapp, context):
    """액션을 새로 등록해도 UI 코드를 고치지 않아도 된다는 약속을 지키는지."""
    for type_id, at in registry.ACTION_TYPES.items():
        form = SchemaForm(at.PARAMS, context)
        form.load(at.defaults())
        assert set(form.editors) == {f.name for f in at.PARAMS}, type_id


def test_form_builds_for_every_node_and_condition_type(qapp, context):
    for spec in registry.NODE_TYPES.values():
        SchemaForm(spec.params, context).load(spec.defaults())
    for ct in registry.CONDITION_TYPES.values():
        SchemaForm(ct.PARAMS, context).load({f.name: f.default for f in ct.PARAMS})


def test_form_roundtrips_values(qapp, context):
    fields = [
        Field("count", "int", default=3),
        Field("ratio", "float", default=0.5),
        Field("name", "str", default="가"),
        Field("flag", "bool", default=False),
        Field("mode", "enum", default="b", options=[("a", "A"), ("b", "B")]),
        Field("point", "point"),
        Field("region", "rect"),
        Field("targets", "object_ref_list"),
        Field("path", "point_list"),
    ]
    form = SchemaForm(fields, context)
    form.load(
        {
            "count": 7,
            "ratio": 1.25,
            "name": "테스트",
            "flag": True,
            "mode": "a",
            "point": [10, 20],
            "region": [1, 2, 3, 4],
            "targets": ["버튼A", "버튼B"],
            "path": [[1, 2], [3, 4]],
        }
    )
    values = {name: editor.value() for name, editor in form.editors.items()}
    assert values["count"] == 7
    assert values["ratio"] == 1.25
    assert values["name"] == "테스트"
    assert values["flag"] is True
    assert values["mode"] == "a"
    assert values["point"] == [10, 20]
    assert values["region"] == [1, 2, 3, 4]
    assert values["targets"] == ["버튼A", "버튼B"]
    assert values["path"] == [[1, 2], [3, 4]]


def test_depends_on_hides_and_shows_fields(qapp, context):
    spec = registry.node_type("loop")
    form = SchemaForm(spec.params, context)
    form.load({**spec.defaults(), "mode": "count"})

    assert form.editors["count"].isVisibleTo(form)
    assert not form.editors["expr"].isVisibleTo(form)

    form.editors["mode"].combo.setCurrentIndex(1)  # while

    assert not form.editors["count"].isVisibleTo(form)
    assert form.editors["expr"].isVisibleTo(form)


def test_form_emits_changed_value(qapp, context):
    seen = []
    form = SchemaForm([Field("count", "int", default=1)], context)
    form.load({"count": 1})
    form.value_changed.connect(lambda name, value: seen.append((name, value)))

    form.editors["count"].spin.setValue(5)

    assert seen == [("count", 5)]


def test_loading_does_not_emit(qapp, context):
    seen = []
    form = SchemaForm([Field("name", "str")], context)
    form.value_changed.connect(lambda *a: seen.append(a))
    form.load({"name": "값"})
    assert seen == []


def test_ref_editors_offer_project_choices(qapp, project, context):
    from itda.core.model import State, TargetObject

    project.add_object(TargetObject(name="확인 버튼"))
    project.states.states.append(State(name="설정창"))

    form = SchemaForm(
        [Field("objects", "object_ref_list"), Field("target_state", "state_ref")], context
    )
    form.load({"objects": [], "target_state": ""})

    assert "확인 버튼" in [
        form.editors["objects"].combo.itemText(i)
        for i in range(form.editors["objects"].combo.count())
    ]
    assert "설정창" in [
        form.editors["target_state"].combo.itemText(i)
        for i in range(form.editors["target_state"].combo.count())
    ]


def test_node_ref_editor_stores_id_but_shows_title(qapp, project, context):
    node = project.flow("main").nodes[1]
    node.title = "로그인 시도"
    form = SchemaForm([Field("target", "node_ref")], context)
    form.load({"target": node.id})

    editor = form.editors["target"]
    assert editor.value() == node.id
    assert editor.combo.currentText() == "로그인 시도"


def test_node_ref_editor_keeps_dangling_reference_visible(qapp, context):
    form = SchemaForm([Field("target", "node_ref")], context)
    form.load({"target": "n_없어진노드"})
    assert form.editors["target"].value() == "n_없어진노드"
    assert "없는 노드" in form.editors["target"].combo.currentText()


def test_node_ref_editor_keeps_dangling_reference_through_a_refresh(qapp, context):
    """목록을 새로 고칠 때도 선택을 버리면 안 된다.

    노드가 바뀔 때마다 목록을 다시 채우는데, 여기서 '(없음)' 으로 돌려 버리면 사용자가
    손대지도 않은 예외 처리 이동 대상이 조용히 사라진다.
    """
    form = SchemaForm([Field("target", "node_ref")], context)
    form.load({"target": "n_없어진노드"})

    form.editors["target"].refresh_choices()

    assert form.editors["target"].value() == "n_없어진노드"
    assert "없는 노드" in form.editors["target"].combo.currentText()


# ---------------------------------------------------------------- 좌표 목록


def test_point_list_keeps_coordinates_while_a_line_is_being_typed(qapp, context):
    """'120, 340' 을 고치는 도중 '1' 만 남는 순간에 그 좌표를 잃으면 안 된다."""
    form = SchemaForm([Field("path", "point_list")], context)
    form.load({"path": [[120, 340], [50, 60]]})
    editor = form.editors["path"]

    editor.list.item(0).setText("1")  # 지우고 다시 치는 중

    assert editor.value() == [[120, 340], [50, 60]]  # 값은 그대로
    assert editor.list.item(0).toolTip()  # 형식이 틀렸다고 알려는 준다


def test_point_list_takes_the_new_value_once_it_parses(qapp, context):
    form = SchemaForm([Field("path", "point_list")], context)
    form.load({"path": [[120, 340]]})
    editor = form.editors["path"]

    editor.list.item(0).setText("11, 22")

    assert editor.value() == [[11, 22]]
    assert not editor.list.item(0).toolTip()


# ---------------------------------------------------------------- 일치 임계값 슬라이더


def _threshold_form(qapp, context, default: float = 0.0):
    from itda.gui.widgets.schema_form import MatchThresholdEditor

    field = Field("threshold", "match_threshold", "일치 임계값", default)
    form = SchemaForm([field], context)
    form.load({"threshold": default})
    editor = form.editors["threshold"]
    assert isinstance(editor, MatchThresholdEditor)
    return editor


def test_default_value_checks_the_box_and_locks_the_slider(qapp, context):
    editor = _threshold_form(qapp, context, 0.0)

    assert editor.checkbox.isChecked() is True
    assert editor.slider.isEnabled() is False
    assert editor.value() == 0.0


def test_custom_value_unchecks_and_positions_the_slider(qapp, context):
    editor = _threshold_form(qapp, context, 0.75)

    assert editor.checkbox.isChecked() is False
    assert editor.slider.isEnabled() is True
    assert editor.slider.value() == 75
    assert editor.value() == 0.75


def test_unchecking_the_default_box_reveals_a_usable_slider(qapp, context):
    """체크를 풀면 슬라이더가 살아나고, 그 위치가 곧 저장될 값이어야 한다."""
    editor = _threshold_form(qapp, context, 0.0)

    editor.checkbox.setChecked(False)

    assert editor.slider.isEnabled() is True
    assert editor.value() == round(editor.slider.value() / 100, 2)
    assert editor.value() != 0.0


def test_checking_the_default_box_ignores_the_slider_position(qapp, context):
    editor = _threshold_form(qapp, context, 0.6)
    assert editor.value() == 0.6

    editor.checkbox.setChecked(True)

    assert editor.slider.isEnabled() is False
    assert editor.value() == 0.0  # 슬라이더 위치와 무관하게 상속을 뜻한다


def test_moving_the_slider_emits_the_new_value(qapp, context):
    editor = _threshold_form(qapp, context, 0.5)
    seen = []
    editor.edited.connect(seen.append)

    editor.slider.setValue(93)

    assert seen == [0.93]


def test_moving_the_slider_while_default_is_checked_does_not_emit(qapp, context):
    """잠긴 슬라이더는 값에 영향을 주면 안 된다 — 실수로 만져도 여전히 상속이다."""
    editor = _threshold_form(qapp, context, 0.0)
    seen = []
    editor.edited.connect(seen.append)

    editor.slider.setEnabled(True)  # 테스트에서 강제로 만졌다고 가정
    editor.slider.setValue(40)

    assert seen == []
    assert editor.value() == 0.0


def test_unchecking_then_rechecking_restores_the_previous_custom_value(qapp, context):
    editor = _threshold_form(qapp, context, 0.72)

    editor.checkbox.setChecked(True)
    assert editor.value() == 0.0

    editor.checkbox.setChecked(False)
    assert editor.value() == 0.72  # 이전에 고른 값을 잊지 않는다


def test_default_label_reads_the_project_profile_not_a_hardcoded_number(qapp):
    """프로파일을 바꾸면 "기본값 사용 (n%)" 도 따라가야 한다 — 안 그러면 라벨이 거짓말한다."""
    ctx = FormContext(match_default=lambda: 0.95)
    field = Field("threshold", "match_threshold", "일치 임계값", 0.0)
    form = SchemaForm([field], ctx)
    form.load({"threshold": 0.0})

    assert "95%" in form.editors["threshold"].checkbox.text()


def test_default_label_falls_back_to_the_profile_default(qapp, context):
    """도구가 주입되지 않아도 TimingProfile 기본값(0.88)을 쓴다."""
    from itda.core.timing import TimingProfile

    field = Field("threshold", "match_threshold", "일치 임계값", 0.0)
    form = SchemaForm([field], context)
    form.load({"threshold": 0.0})

    expected = round(TimingProfile.match_threshold * 100)
    assert f"{expected}%" in form.editors["threshold"].checkbox.text()


def test_unchecking_starts_from_the_profile_default(qapp):
    """체크를 풀면 슬라이더가 프로파일 값에서 시작해야 자연스럽다."""
    ctx = FormContext(match_default=lambda: 0.95)
    field = Field("threshold", "match_threshold", "일치 임계값", 0.0)
    form = SchemaForm([field], ctx)
    form.load({"threshold": 0.0})
    editor = form.editors["threshold"]

    editor.checkbox.setChecked(False)

    assert editor.value() == 0.95


def test_image_search_action_uses_the_threshold_slider(qapp, context):
    at = registry.action_type("image_search")
    form = SchemaForm(at.PARAMS, context)
    form.load(at.defaults())

    from itda.gui.widgets.schema_form import MatchThresholdEditor

    assert isinstance(form.editors["threshold"], MatchThresholdEditor)
    assert form.editors["threshold"].value() == 0.0  # 기본값은 여전히 0.88 로 상속


def test_object_visible_condition_uses_the_threshold_slider(qapp, context):
    ct = registry.condition_type("object_visible")
    form = SchemaForm(ct.PARAMS, context)
    form.load({f.name: f.default for f in ct.PARAMS})

    from itda.gui.widgets.schema_form import MatchThresholdEditor

    assert isinstance(form.editors["threshold"], MatchThresholdEditor)


# ---------------------------------------------------------------- 경로 헬퍼


def test_dotted_paths_read_and_locate_owner(project):
    node = project.flow("main").nodes[1]
    node.pre.pre_ms = 250
    assert get_path(node, "pre.pre_ms") == 250

    owner, attr = owner_of(node, "retry.count")
    assert owner is node.retry and attr == "count"


# ---------------------------------------------------------------- 속성 패널


@pytest.fixture
def panel(qapp, scene, context):
    p = PropertyPanel()
    p.set_scene(scene, context)
    return p


def test_panel_shows_node_sections(panel, scene):
    node = scene.flow.nodes[1]
    panel.show_node(node)
    assert panel.node is node
    assert len(panel._forms) >= 3  # 기본 / 상황 / 타이밍 / 예외


def test_editing_node_title_pushes_undoable_command(panel, scene):
    node = scene.flow.nodes[1]
    panel.show_node(node)
    basic = panel._forms[0]

    basic.editors["title"].edit.setText("바뀐 제목")
    basic.editors["title"].edited.emit("바뀐 제목")

    assert node.title == "바뀐 제목"
    scene.undo_stack.undo()
    assert node.title != "바뀐 제목"


def test_editing_nested_timing_attribute(panel, scene):
    node = scene.flow.nodes[1]
    panel.show_node(node)
    assert node.pre.inherit is True

    panel._on_node_attr("pre.inherit", False)
    panel._on_node_attr("pre.pre_ms", 300)

    assert node.pre.inherit is False
    assert node.pre.pre_ms == 300


def test_action_params_edit_through_panel(panel, scene):
    node = scene.flow.nodes[1]
    action = Action(type="click", params=registry.action_params("click", None))
    node.actions.append(action)

    panel.show_action(node, action)
    panel._on_action_param("button", "right")

    assert action.params["button"] == "right"
    scene.undo_stack.undo()
    assert action.params["button"] == "left"


def test_switching_target_removes_previous_sections(panel, scene):
    """이전 화면의 위젯이 남아 새 내용 위에 겹쳐 그려지면 안 된다."""
    from PyQt6.QtWidgets import QGroupBox

    node = scene.flow.nodes[1]
    panel.show_node(node)
    assert "예외 처리" in {box.title() for box in panel.body.findChildren(QGroupBox)}

    action = Action(type="click", params=registry.action_params("click", None))
    node.actions.append(action)
    panel.show_action(node, action)

    titles = {box.title() for box in panel.body.findChildren(QGroupBox)}
    assert "예외 처리" not in titles  # 노드 전용 구획이 남아 있으면 안 된다
    assert "파라미터" in titles

    panel.show_none()
    assert not panel.body.findChildren(QGroupBox)


# ---------------------------------------------------------------- 창 선택 버튼


def _picker_button(panel):
    from PyQt6.QtWidgets import QPushButton

    for button in panel.body.findChildren(QPushButton):
        if button.text().startswith("창 선택"):
            return button
    return None


def test_window_picker_button_appears_only_for_the_window_node(panel, scene):
    from PyQt6.QtCore import QPointF

    other = scene.flow.nodes[1]
    panel.show_node(other)
    assert _picker_button(panel) is None  # 다른 노드 타입엔 없어야 한다

    window_node = scene.add_node("window", QPointF(0, 0))
    panel.show_node(window_node)
    assert _picker_button(panel) is not None


def test_window_picker_button_appears_only_for_the_window_action(panel, scene):
    node = scene.flow.nodes[1]

    click = Action(type="click", params=registry.action_params("click", None))
    node.actions.append(click)
    panel.show_action(node, click)
    assert _picker_button(panel) is None

    window_action = Action(type="window", params=registry.action_params("window", None))
    node.actions.append(window_action)
    panel.show_action(node, window_action)
    assert _picker_button(panel) is not None


def test_picking_a_window_fills_four_fields_as_one_undo_step(qapp, scene):
    from PyQt6.QtCore import QPointF

    context = FormContext(
        nodes=lambda: [(n.id, n.title) for n in scene.flow.nodes],
        pick_window=lambda: ("메모장", 100, 200, 800, 600),
    )
    panel = PropertyPanel()
    panel.set_scene(scene, context)

    node = scene.add_node("window", QPointF(0, 0))
    panel.show_node(node)
    before = scene.undo_stack.count()

    button = _picker_button(panel)
    assert button is not None
    button.click()

    assert node.params["title"] == "메모장"
    assert node.params["match"] == "exact"
    assert node.params["point"] == [100, 200]
    assert node.params["size"] == [800, 600]
    assert scene.undo_stack.count() == before + 1  # 네 칸이 되돌리기 한 번으로 묶임

    scene.undo_stack.undo()
    assert node.params["title"] == ""
    assert node.params["point"] == [0, 0]
    assert node.params["size"] == [0, 0]


def test_cancelling_the_picker_changes_nothing(qapp, scene):
    from PyQt6.QtCore import QPointF

    context = FormContext(
        nodes=lambda: [(n.id, n.title) for n in scene.flow.nodes],
        pick_window=lambda: None,  # ESC 로 취소
    )
    panel = PropertyPanel()
    panel.set_scene(scene, context)

    node = scene.add_node("window", QPointF(0, 0))
    panel.show_node(node)
    before = scene.undo_stack.count()

    _picker_button(panel).click()

    assert node.params["title"] == ""
    assert scene.undo_stack.count() == before


def test_picker_button_is_disabled_without_a_pick_window_callback(panel, scene):
    """도구가 주입되지 않았으면 눌러도 아무 일이 없다 — 다른 도구 버튼처럼 꺼 둔다."""
    from PyQt6.QtCore import QPointF

    node = scene.add_node("window", QPointF(0, 0))
    panel.show_node(node)
    before = scene.undo_stack.count()

    button = _picker_button(panel)  # panel 의 context 는 pick_window=None
    assert button.isEnabled() is False

    button.click()
    assert scene.undo_stack.count() == before


def test_picker_button_is_enabled_once_the_tool_is_injected(qapp, scene):
    from PyQt6.QtCore import QPointF

    ctx = FormContext(pick_window=lambda: ("메모장", 1, 2, 3, 4))
    panel = PropertyPanel()
    panel.set_scene(scene, ctx)

    node = scene.add_node("window", QPointF(0, 0))
    panel.show_node(node)

    assert _picker_button(panel).isEnabled() is True


class WindowSpy(QObject):
    """최상위 창으로 표시되는 위젯을 잡아낸다.

    부모 없이 만든 위젯은 레이아웃에 들어가기 전까지 최상위 위젯이다. 부모가 이미 화면에 있으면
    그 짧은 순간에 **흰 창이 떴다 사라진다** — 액션을 고를 때마다 반복돼 눈에 거슬린다.
    """

    def __init__(self) -> None:
        super().__init__()
        self.shown: list[str] = []

    def eventFilter(self, obj, event) -> bool:
        if (
            event.type() == QEvent.Type.Show
            and isinstance(obj, QWidget)
            and obj.isWindow()
        ):
            from PyQt6.QtWidgets import QGroupBox

            title = obj.title() if isinstance(obj, QGroupBox) else obj.windowTitle()
            self.shown.append(f"{type(obj).__name__}({title!r}, 부모없음={obj.parent() is None})")
        return False


def test_switching_targets_never_flashes_a_window(panel, scene, qapp):
    node = scene.flow.nodes[1]
    first = Action(type="click", params=registry.action_params("click", None))
    second = Action(type="image_search", params=registry.action_params("image_search", None))
    node.actions += [first, second]

    panel.show()
    panel.show_node(node)
    qapp.processEvents()

    spy = WindowSpy()
    qapp.installEventFilter(spy)
    try:
        for _ in range(3):
            panel.show_action(node, first)
            qapp.processEvents()
            panel.show_action(node, second)
            qapp.processEvents()
            panel.show_node(node)
            qapp.processEvents()
    finally:
        qapp.removeEventFilter(spy)

    assert spy.shown == [], f"창으로 표시된 위젯: {spy.shown}"


def test_node_editor_selection_never_flashes_a_window(qapp, scene):
    """실제로 보고된 증상 — 노드 편집 창에서 액션을 고를 때 흰 창이 깜빡였다."""
    from itda.gui.dialogs.node_editor_dialog import NodeEditorDialog

    node = scene.flow.nodes[1]
    node.actions = [
        Action(type=type_id, params=registry.action_params(type_id, None))
        for type_id in ("click", "type_text", "sleep")
    ]

    dialog = NodeEditorDialog(scene, node, FormContext())
    dialog.show()
    qapp.processEvents()

    spy = WindowSpy()
    qapp.installEventFilter(spy)
    try:
        for action in node.actions:
            dialog.sequence.select_action(action)
            qapp.processEvents()
    finally:
        qapp.removeEventFilter(spy)
        dialog.close()

    assert spy.shown == [], f"창으로 표시된 위젯: {spy.shown}"


def test_unknown_action_type_does_not_crash_panel(panel, scene):
    node = scene.flow.nodes[1]
    action = Action(type="존재하지않는액션")
    node.actions.append(action)
    panel.show_action(node, action)  # 예외 없이 경고만 표시


# ---------------------------------------------------------------- 액션 목록


@pytest.fixture
def action_panel(qapp, scene):
    p = ActionListPanel()
    p.set_scene(scene)
    p.set_node(scene.flow.nodes[1])
    return p


def test_add_action_inserts_after_selection(action_panel, scene):
    node = action_panel.node
    action_panel.add_action("click")
    action_panel.add_action("type_text")

    assert [a.type for a in node.actions] == ["click", "type_text"]
    assert action_panel.list.count() == 2


def test_action_list_shows_summary(action_panel):
    action_panel.add_action("sleep")
    assert "대기" in action_panel.list.item(0).text()


def test_move_action_reorders_and_undoes(action_panel, scene):
    node = action_panel.node
    for type_id in ("click", "type_text", "beep"):
        action_panel.add_action(type_id)

    action_panel.select_action(node.actions[2].id)
    action_panel.move_selected(-1)

    assert [a.type for a in node.actions] == ["click", "beep", "type_text"]
    scene.undo_stack.undo()
    assert [a.type for a in node.actions] == ["click", "type_text", "beep"]


def test_duplicate_action_makes_new_id(action_panel):
    node = action_panel.node
    action_panel.add_action("click")
    node.actions[0].params["point"] = [5, 6]
    action_panel.select_action(node.actions[0].id)

    action_panel.duplicate_selected()

    assert len(node.actions) == 2
    assert node.actions[0].id != node.actions[1].id
    assert node.actions[1].params["point"] == [5, 6]
    node.actions[1].params["point"] = [9, 9]
    assert node.actions[0].params["point"] == [5, 6]  # 깊은 복사


def test_delete_action_and_undo(action_panel, scene):
    node = action_panel.node
    action_panel.add_action("click")
    action_panel.select_action(node.actions[0].id)

    action_panel.delete_selected()
    assert node.actions == []

    scene.undo_stack.undo()
    assert len(node.actions) == 1


def test_checkbox_toggles_enabled(action_panel, scene):
    node = action_panel.node
    action_panel.add_action("click")
    item = action_panel.list.item(0)

    item.setCheckState(Qt.CheckState.Unchecked)

    assert node.actions[0].enabled is False
    scene.undo_stack.undo()
    assert node.actions[0].enabled is True


def test_panel_refuses_actions_on_nodes_that_cannot_hold_them(action_panel, scene):
    gate = scene.add_node("state_gate", QPointF(0, 0))
    action_panel.set_node(gate)
    assert not action_panel.btn_add.isEnabled()
    assert "담지 않습니다" in action_panel.title.text()


def test_refresh_labels_keeps_selection(action_panel):
    node = action_panel.node
    action_panel.add_action("click")
    action_panel.add_action("beep")
    action_panel.select_action(node.actions[0].id)

    node.actions[0].params["button"] = "right"
    action_panel.refresh_labels()

    assert action_panel.current_action() is node.actions[0]
    assert action_panel.list.count() == 2
