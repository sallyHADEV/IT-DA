"""플로우 캔버스 씬 테스트 — 편집과 되돌리기가 모델과 화면을 함께 유지하는지."""

from __future__ import annotations

from PyQt6.QtCore import QPointF

from itda.core.events import IDLE, OK, RUNNING
from itda.gui.commands import AddEdgeCommand, SetAttrCommand


def test_scene_mirrors_initial_flow(scene):
    assert len(scene.node_items) == len(scene.flow.nodes)
    assert len(scene.edge_items) == len(scene.flow.edges)


def test_add_node_creates_item_and_undoes(scene):
    before = len(scene.flow.nodes)
    node = scene.add_node("action_group", QPointF(100, 100))

    assert node is not None
    assert len(scene.flow.nodes) == before + 1
    assert node.id in scene.node_items

    scene.undo_stack.undo()
    assert len(scene.flow.nodes) == before
    assert node.id not in scene.node_items

    scene.undo_stack.redo()
    assert node.id in scene.node_items


def test_start_node_is_unique(scene):
    assert scene.flow.start_node() is not None
    assert scene.add_node("start", QPointF(0, 0)) is None


def test_dropping_action_creates_node_holding_that_action(scene):
    node = scene.add_action_node("image_search", QPointF(50, 50))

    assert node is not None
    assert node.type == "action_group"
    assert [a.type for a in node.actions] == ["image_search"]
    # 액션 파라미터가 스키마 기본값으로 채워져 있어야 속성 폼이 바로 열린다
    assert node.actions[0].params["mode"] == "any"


def test_delete_node_removes_attached_edges_and_undo_restores(scene):
    flow = scene.flow
    start = flow.start_node()
    middle = flow.nodes[1]
    tail = scene.add_node("end", QPointF(400, 0))
    edge = flow.connect(middle.id, "ok", tail.id)
    flow.edges.remove(edge)
    scene.undo_stack.push(AddEdgeCommand(scene, edge))

    scene.select_only(middle.id)
    scene.delete_selection()

    assert flow.node(middle.id) is None
    assert flow.edges == []
    assert scene.edge_items == {}

    scene.undo_stack.undo()

    assert flow.node(middle.id) is not None
    assert len(flow.edges) == 2  # start→middle, middle→tail 둘 다 복원
    assert len(scene.edge_items) == 2
    assert flow.node(start.id) is not None


def test_copy_paste_makes_independent_copies(scene):
    node = scene.flow.nodes[1]
    node.title = "원본"
    scene.select_only(node.id)

    payload = scene.copy_selection()
    pasted = scene.paste(payload, QPointF(300, 300))

    assert len(pasted) == 1
    copy = pasted[0]
    assert copy.id != node.id
    assert copy.title == "원본"

    copy.title = "사본"
    assert node.title == "원본"


def test_paste_rewires_internal_edges(scene):
    flow = scene.flow
    a = flow.nodes[1]
    b = scene.add_node("action_group", QPointF(300, 0))
    edge = flow.connect(a.id, "ok", b.id)
    flow.edges.remove(edge)
    scene.undo_stack.push(AddEdgeCommand(scene, edge))

    scene.clearSelection()
    for node in (a, b):
        scene.node_items[node.id].setSelected(True)

    pasted = scene.paste(scene.copy_selection(), QPointF(0, 400))
    new_ids = {n.id for n in pasted}

    internal = [e for e in flow.edges if e.src_node in new_ids and e.dst_node in new_ids]
    assert len(internal) == 1
    # 원본 노드로 새는 연결이 없어야 한다
    assert not [e for e in flow.edges if (e.src_node in new_ids) != (e.dst_node in new_ids)]


def test_pasted_start_node_becomes_action_group(scene):
    start = scene.flow.start_node()
    scene.select_only(start.id)
    pasted = scene.paste(scene.copy_selection(), QPointF(0, 300))
    assert pasted[0].type == "action_group"


def test_set_attr_command_merges_consecutive_edits(scene):
    node = scene.flow.nodes[1]
    count_before = scene.undo_stack.count()

    for text in ("로", "로그", "로그인"):
        scene.undo_stack.push(SetAttrCommand(scene, node, "title", text))

    assert node.title == "로그인"
    assert scene.undo_stack.count() == count_before + 1  # 한 번의 편집으로 합쳐짐

    scene.undo_stack.undo()
    assert node.title != "로그인"


def test_node_item_refresh_follows_port_changes(scene):
    node = scene.add_node("switch", QPointF(0, 0))
    item = scene.node_items[node.id]
    assert set(item.out_ports) == {"default"}

    node.params["cases"] = "성공, 실패, 취소"
    item.refresh()

    assert list(item.out_ports) == ["성공", "실패", "취소", "default"]


def test_auto_layout_spreads_nodes_and_is_undoable(scene):
    flow = scene.flow
    for i in range(3):
        scene.add_node("action_group", QPointF(0, 0))
    positions_before = [(n.x, n.y) for n in flow.nodes]

    scene.auto_layout()

    assert [(n.x, n.y) for n in flow.nodes] != positions_before
    assert len({(n.x, n.y) for n in flow.nodes}) == len(flow.nodes)  # 겹치지 않음

    scene.undo_stack.undo()
    assert [(n.x, n.y) for n in flow.nodes] == positions_before


def test_snap_rounds_to_grid(scene):
    assert scene.snap(QPointF(103, 97)) == QPointF(100, 100)
    scene.snap_enabled = False
    assert scene.snap(QPointF(103, 97)) == QPointF(103, 97)


def test_runtime_visualization_api(scene):
    node_id = scene.flow.nodes[0].id
    scene.set_node_status(node_id, RUNNING)
    assert scene.node_items[node_id].status == RUNNING

    scene.set_node_status(node_id, OK)
    assert scene.node_items[node_id].status == OK

    scene.clear_statuses()
    assert all(i.status == IDLE for i in scene.node_items.values())


def test_ports_are_hidden_when_zoomed_far_out(scene):
    """노드 300개면 포트가 900개다 — 축소 상태에서 점으로만 보이는 것을 그리느라 줌이 느려진다."""
    from itda.gui.canvas.scene import PORT_DETAIL

    node = scene.flow.nodes[1]
    ports = list(scene.node_items[node.id].out_ports.values())
    assert ports and all(p.isVisible() for p in ports)

    scene.apply_detail(PORT_DETAIL / 2)
    assert not any(p.isVisible() for p in ports)

    scene.apply_detail(1.0)
    assert all(p.isVisible() for p in ports)


def test_apply_detail_does_nothing_when_state_is_unchanged(scene):
    """줌할 때마다 900개 위젯을 건드리면 최적화가 아니라 부담이 된다."""
    from itda.gui.canvas.scene import PORT_DETAIL

    scene.apply_detail(PORT_DETAIL / 2)
    touched = []
    for item in scene.node_items.values():
        for port in item.out_ports.values():
            port.setVisible = lambda *_a, _p=port: touched.append(_p)

    scene.apply_detail(PORT_DETAIL / 3)  # 여전히 '숨김' 상태

    assert touched == []


def test_view_zoom_applies_detail(scene, qapp):
    from itda.gui.canvas.view import FlowView

    view = FlowView(scene)
    view.resize(800, 600)
    node = scene.flow.nodes[1]
    ports = list(scene.node_items[node.id].out_ports.values())

    for _ in range(12):
        view.zoom_by(1 / 1.15)  # 많이 축소
    assert not any(p.isVisible() for p in ports)

    for _ in range(12):
        view.zoom_by(1.15)
    assert all(p.isVisible() for p in ports)


def test_large_flow_builds_and_lays_out(qapp, project):
    """노드가 많아도 씬 구축과 자동 정렬이 끝나야 한다 (겹침 없이)."""
    from itda.core.model import Node
    from itda.gui.canvas.scene import FlowScene

    flow = project.flow("main")
    previous = flow.nodes[1]
    for i in range(200):
        node = flow.add_node(Node(type="action_group", title=f"노드 {i}"))
        flow.connect(previous.id, "ok", node.id)
        previous = node

    scene = FlowScene(project, flow, "main")
    assert len(scene.node_items) == len(flow.nodes)

    scene.auto_layout()
    positions = {(n.x, n.y) for n in flow.nodes}
    assert len(positions) == len(flow.nodes)


def test_editing_marks_project_dirty(scene):
    scene.project.mark_dirty(False)
    scene.add_node("action_group", QPointF(10, 10))
    assert scene.project.dirty


def test_multiple_out_ports_do_not_collide(scene):
    """출구가 여럿이면 라벨이 겹치지 않을 만큼 노드가 커져야 한다.

    기본 높이(62px)에 출구 2개를 넣으면 간격이 8px 밖에 안 나와, 7pt 라벨(글자 높이 9px)
    이 서로 위에 찍혔다 — 화면으로 확인한 실제 버그다.
    """
    from itda.gui.canvas.node_item import PORT_SPACING

    for node in scene.flow.nodes:
        item = scene.node_items[node.id]
        ys = sorted(port.pos().y() for port in item.out_ports.values())
        gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
        assert all(gap >= PORT_SPACING - 0.01 for gap in gaps), (node.type, gaps)


def test_many_out_ports_grow_the_node(scene):
    from PyQt6.QtCore import QPointF

    from itda.gui.canvas.node_item import PORT_SPACING

    node = scene.add_node("switch", QPointF(0, 0))
    node.params["cases"] = "가, 나, 다, 라"
    item = scene.node_items[node.id]
    item.refresh()

    ys = sorted(port.pos().y() for port in item.out_ports.values())
    assert len(ys) == 5  # 4 갈래 + default
    assert all(ys[i + 1] - ys[i] >= PORT_SPACING - 0.01 for i in range(len(ys) - 1))
    assert item.height() > 62.0  # 기본 높이보다 커졌다


def test_single_out_port_keeps_the_compact_height(scene):
    """출구가 하나면 겹칠 일이 없으니 노드를 키우지 않는다."""
    start = scene.node_items[scene.flow.start_node().id]
    assert len(start.out_ports) == 1
    assert start.height() == 62.0
