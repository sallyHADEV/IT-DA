"""플로우 캔버스 씬.

모델(Flow)과 그래픽 아이템을 잇는 계층. 편집은 전부 QUndoStack 을 통해서만 일어난다.
실행 시각화 API(:meth:`set_node_status`, :meth:`fire_edge`)를 여기서 미리 정의해 두고,
2차의 실행 엔진은 이벤트 버스로 이 함수들만 호출하면 된다.
"""

from __future__ import annotations

import json

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPixmap, QUndoStack
from PyQt6.QtWidgets import QGraphicsPathItem, QGraphicsScene

from itda.core import registry
from itda.core.events import IDLE
from itda.core.model import Action, Edge, Flow, Node
from itda.core.serde import from_dict, to_dict
from itda.gui import style
from itda.gui.canvas.edge_item import EdgeItem
from itda.gui.canvas.layout import compute_positions
from itda.gui.canvas.node_item import NodeItem, PortItem
from itda.gui.commands import (
    AddEdgeCommand,
    AddNodeCommand,
    MoveNodesCommand,
    RemoveItemsCommand,
)

GRID = 10
CLIP_MIME = "application/x-itda-nodes"
#: 이 배율보다 작으면 포트를 감춘다 (점으로만 보여 의미가 없다)
PORT_DETAIL = 0.5


class FlowScene(QGraphicsScene):
    """플로우 하나를 그리는 씬."""

    #: 선택이 바뀜 — (종류, 대상). 종류: node | edge | none
    selection_changed = pyqtSignal(str, object)
    #: 노드 더블클릭 (노드 id)
    node_double_clicked = pyqtSignal(str)
    #: 모델이 바뀜 (저장 필요 표시용)
    model_changed = pyqtSignal()

    def __init__(self, project, flow: Flow, flow_key: str, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.flow = flow
        self.flow_key = flow_key
        self.undo_stack = QUndoStack(self)
        self.node_items: dict[str, NodeItem] = {}
        self.edge_items: dict[str, EdgeItem] = {}
        self.snap_enabled = True

        self._connecting: PortItem | None = None
        self._temp_edge: QGraphicsPathItem | None = None
        self._move_origin: dict[str, tuple[float, float]] = {}
        self._grid_brush_cache: QBrush | None = None
        self._ports_hidden = False

        self.setBackgroundBrush(style.CANVAS_BG)
        self.setSceneRect(-6000, -6000, 12000, 12000)
        self.selectionChanged.connect(self._emit_selection)
        self.rebuild()

    # ------------------------------------------------------------ 구축

    def rebuild(self) -> None:
        self.clear()
        self.node_items.clear()
        self.edge_items.clear()
        for node in self.flow.nodes:
            self.create_node_item(node)
        for edge in self.flow.edges:
            self.create_edge_item(edge)

    def create_node_item(self, node: Node) -> NodeItem:
        item = NodeItem(node, self)
        item.geometry_changed.connect(lambda nid=node.id: self.sync_edges_of(nid))
        self.addItem(item)
        self.node_items[node.id] = item
        self.sync_edges_of(node.id)
        return item

    def destroy_node_item(self, node_id: str) -> None:
        item = self.node_items.pop(node_id, None)
        if item is not None:
            self.removeItem(item)

    def create_edge_item(self, edge: Edge) -> EdgeItem:
        item = EdgeItem(edge, self)
        self.addItem(item)
        self.edge_items[edge.id] = item
        item.sync()
        return item

    def destroy_edge_item(self, edge_id: str) -> None:
        item = self.edge_items.pop(edge_id, None)
        if item is not None:
            self.removeItem(item)

    # ------------------------------------------------------------ 동기화

    def sync_node_position(self, node_id: str) -> None:
        node = self.flow.node(node_id)
        item = self.node_items.get(node_id)
        if node and item:
            item.setPos(node.x, node.y)
            self.sync_edges_of(node_id)

    def sync_edges_of(self, node_id: str) -> None:
        for edge in self.flow.edges:
            if node_id in (edge.src_node, edge.dst_node):
                item = self.edge_items.get(edge.id)
                if item:
                    item.sync()

    def sync_edge(self, edge_id: str) -> None:
        item = self.edge_items.get(edge_id)
        if item:
            item.sync()

    def notify_edited(self, target) -> None:
        """속성 편집 후 관련 노드 아이템을 갱신한다."""
        node_id = None
        if isinstance(target, Node):
            node_id = target.id
        elif isinstance(target, Action):
            for n in self.flow.nodes:
                if target in n.actions:
                    node_id = n.id
                    break
        if node_id and node_id in self.node_items:
            self.node_items[node_id].refresh()
            self.sync_edges_of(node_id)
        self.model_changed.emit()

    def mark_changed(self) -> None:
        self.project.mark_dirty()
        self.model_changed.emit()

    # ------------------------------------------------------------ 선택

    def _emit_selection(self) -> None:
        items = self.selectedItems()
        if len(items) == 1:
            item = items[0]
            if isinstance(item, NodeItem):
                self.selection_changed.emit("node", item.node)
                return
            if isinstance(item, EdgeItem):
                self.selection_changed.emit("edge", item.edge)
                return
        self.selection_changed.emit("none", None)

    def select_only(self, node_id: str) -> None:
        self.clearSelection()
        item = self.node_items.get(node_id)
        if item:
            item.setSelected(True)

    def selected_nodes(self) -> list[Node]:
        return [i.node for i in self.selectedItems() if isinstance(i, NodeItem)]

    # ------------------------------------------------------------ 배경 격자

    def _grid_brush(self) -> QBrush:
        """격자 한 칸을 그린 타일을 브러시로 캐싱한다.

        프레임마다 QLineF 수백 개를 만들어 그리면 줌/팬 때 눈에 띄게 느려진다.
        타일 하나만 그려 두고 브러시로 채우면 프레임당 비용이 거의 사라진다.
        """
        if self._grid_brush_cache is None:
            tile = GRID * 2 * 5  # 굵은 선 간격
            pixmap = QPixmap(tile, tile)
            pixmap.fill(style.CANVAS_BG)
            painter = QPainter(pixmap)
            painter.setPen(QPen(style.GRID_MINOR, 1))
            for i in range(0, tile, GRID * 2):
                painter.drawLine(i, 0, i, tile)
                painter.drawLine(0, i, tile, i)
            painter.setPen(QPen(style.GRID_MAJOR, 1))
            painter.drawLine(0, 0, tile, 0)
            painter.drawLine(0, 0, 0, tile)
            painter.end()
            self._grid_brush_cache = QBrush(pixmap)
        return self._grid_brush_cache

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, style.CANVAS_BG)
        # 많이 축소한 상태에서는 격자가 노이즈로만 보이므로 그리지 않는다.
        views = self.views()
        if views and views[0].transform().m11() < 0.45:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._grid_brush())
        painter.drawRect(rect)

    def apply_detail(self, scale: float) -> None:
        """배율에 따라 자잘한 것을 감춘다.

        노드 300개면 포트가 900개가 넘는다. 측정해 보면 줌 비용의 3분의 1이 포트였다.
        많이 축소한 상태에서는 어차피 점으로만 보이므로 숨긴다. 상태가 바뀔 때만 손대서
        평소 줌에는 비용이 들지 않게 한다.
        """
        hide = scale < PORT_DETAIL
        if hide == self._ports_hidden:
            return
        self._ports_hidden = hide
        for item in self.node_items.values():
            for port in (*item.in_ports.values(), *item.out_ports.values()):
                port.setVisible(not hide)

    def snap(self, pos: QPointF) -> QPointF:
        if not self.snap_enabled:
            return pos
        return QPointF(round(pos.x() / GRID) * GRID, round(pos.y() / GRID) * GRID)

    # ------------------------------------------------------------ 이동 커밋

    def mousePressEvent(self, event) -> None:
        self._move_origin = {
            item.node.id: (item.node.x, item.node.y)
            for item in self.selectedItems()
            if isinstance(item, NodeItem)
        }
        item = self.itemAt(event.scenePos(), self.views()[0].transform()) if self.views() else None
        if isinstance(item, NodeItem) and item.node.id not in self._move_origin:
            self._move_origin[item.node.id] = (item.node.x, item.node.y)
        super().mousePressEvent(event)

    def commit_move(self) -> None:
        moves = {}
        for node_id, old in self._move_origin.items():
            node = self.flow.node(node_id)
            if node is None:
                continue
            new = (node.x, node.y)
            if (round(old[0], 2), round(old[1], 2)) != (round(new[0], 2), round(new[1], 2)):
                moves[node_id] = (old, new)
        self._move_origin = {}
        if moves:
            self.undo_stack.push(MoveNodesCommand(self, moves))

    # ------------------------------------------------------------ 연결 드래그

    def begin_connection(self, port: PortItem) -> None:
        self._connecting = port
        self._temp_edge = QGraphicsPathItem()
        pen = QPen(QColor(style.ACCENT), 2, Qt.PenStyle.DashLine)
        pen.setDashPattern([4, 4])
        self._temp_edge.setPen(pen)
        self._temp_edge.setZValue(5)
        self.addItem(self._temp_edge)

    def mouseMoveEvent(self, event) -> None:
        if self._connecting is not None and self._temp_edge is not None:
            src = self._connecting.scene_pos()
            dst = event.scenePos()
            reach = max(50.0, min(abs(dst.x() - src.x()) * 0.6, 200.0))
            path = QPainterPath(src)
            path.cubicTo(QPointF(src.x() + reach, src.y()), QPointF(dst.x() - reach, dst.y()), dst)
            self._temp_edge.setPath(path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._connecting is not None:
            src_port = self._connecting
            self._cancel_connection()
            target = self._node_at(event.scenePos())
            if target is not None and target is not src_port.node_item:
                dst_port = target.port_at(event.scenePos(), is_output=False)
                edge = self.flow.connect(
                    src_port.node_item.node.id,
                    src_port.name,
                    target.node.id,
                    dst_port.name if dst_port else "in",
                )
                if edge is not None:
                    self.flow.edges.remove(edge)  # 커맨드가 다시 넣는다
                    self.undo_stack.push(AddEdgeCommand(self, edge))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _cancel_connection(self) -> None:
        if self._temp_edge is not None:
            self.removeItem(self._temp_edge)
        self._temp_edge = None
        self._connecting = None

    def _node_at(self, pos: QPointF) -> NodeItem | None:
        for item in self.items(pos):
            if isinstance(item, NodeItem):
                return item
            if isinstance(item, PortItem):
                return item.node_item
        return None

    # ------------------------------------------------------------ 편집 명령

    def add_node(self, type_id: str, pos: QPointF, title: str = "") -> Node | None:
        spec = registry.node_type(type_id)
        if spec is None:
            return None
        if spec.unique and any(n.type == type_id for n in self.flow.nodes):
            return None
        pos = self.snap(pos)
        node = Node(
            type=type_id,
            title=title or spec.label,
            x=pos.x(),
            y=pos.y(),
            params=spec.defaults(),
        )
        self.undo_stack.push(AddNodeCommand(self, node, f"{spec.label} 노드 추가"))
        return node

    def add_action_node(self, action_type_id: str, pos: QPointF) -> Node | None:
        """액션을 캔버스에 떨어뜨리면 그 액션 하나를 담은 동작 노드를 만든다."""
        at = registry.action_type(action_type_id)
        if at is None:
            return None
        pos = self.snap(pos)
        node = Node(
            type="action_group",
            title=at.LABEL,
            x=pos.x(),
            y=pos.y(),
            params=registry.node_params("action_group", None),
            actions=[Action(type=action_type_id, params=at.defaults())],
        )
        self.undo_stack.push(AddNodeCommand(self, node, f"{at.LABEL} 노드 추가"))
        return node

    def delete_selection(self) -> None:
        node_ids = [i.node.id for i in self.selectedItems() if isinstance(i, NodeItem)]
        edge_ids = [i.edge.id for i in self.selectedItems() if isinstance(i, EdgeItem)]
        if node_ids or edge_ids:
            self.undo_stack.push(RemoveItemsCommand(self, node_ids, edge_ids))

    def copy_selection(self) -> str:
        """선택한 노드와 그 사이의 엣지를 JSON 문자열로."""
        nodes = self.selected_nodes()
        if not nodes:
            return ""
        ids = {n.id for n in nodes}
        payload = {
            "nodes": [to_dict(n) for n in nodes],
            "edges": [
                to_dict(e)
                for e in self.flow.edges
                if e.src_node in ids and e.dst_node in ids
            ],
        }
        return json.dumps(payload, ensure_ascii=False)

    def paste(self, text: str, pos: QPointF | None = None) -> list[Node]:
        try:
            payload = json.loads(text or "")
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, dict) or "nodes" not in payload:
            return []

        id_map: dict[str, str] = {}
        new_nodes: list[Node] = []
        raw_nodes = payload.get("nodes") or []
        if not raw_nodes:
            return []

        base_x = min(n.get("x", 0) for n in raw_nodes)
        base_y = min(n.get("y", 0) for n in raw_nodes)
        target = self.snap(pos) if pos is not None else QPointF(base_x + 30, base_y + 30)

        for raw in raw_nodes:
            node = from_dict(Node, raw)
            old_id = node.id
            node.id = Node().id
            id_map[old_id] = node.id
            node.x = target.x() + (raw.get("x", 0) - base_x)
            node.y = target.y() + (raw.get("y", 0) - base_y)
            for action in node.actions:
                action.id = Action().id
            if node.type == "start" and self.flow.start_node() is not None:
                node.type = "action_group"  # 시작 노드는 하나뿐
            new_nodes.append(node)

        self.undo_stack.beginMacro(f"{len(new_nodes)}개 붙여넣기")
        for node in new_nodes:
            self.undo_stack.push(AddNodeCommand(self, node))
        for raw in payload.get("edges") or []:
            edge = from_dict(Edge, raw)
            if edge.src_node in id_map and edge.dst_node in id_map:
                edge.id = Edge().id
                edge.src_node = id_map[edge.src_node]
                edge.dst_node = id_map[edge.dst_node]
                self.undo_stack.push(AddEdgeCommand(self, edge))
        self.undo_stack.endMacro()

        self.clearSelection()
        for node in new_nodes:
            item = self.node_items.get(node.id)
            if item:
                item.setSelected(True)
        return new_nodes

    def duplicate_selection(self) -> None:
        text = self.copy_selection()
        if text:
            self.paste(text)

    def auto_layout(self) -> None:
        """계층적 자동 정렬. 분기·합류·되돌아오는 연결이 있어도 선이 덜 꼬인다."""
        if not self.flow.nodes:
            return

        start = self.flow.start_node()
        positions = compute_positions(
            [n.id for n in self.flow.nodes],
            [(e.src_node, e.dst_node) for e in self.flow.edges],
            start_id=start.id if start else None,
        )

        moves = {}
        for node in self.flow.nodes:
            new = positions.get(node.id)
            if new is None:
                continue
            if (round(node.x, 2), round(node.y, 2)) != (round(new[0], 2), round(new[1], 2)):
                moves[node.id] = ((node.x, node.y), new)

        if moves:
            command = MoveNodesCommand(self, moves)
            command.setText("자동 정렬")
            self.undo_stack.push(command)

    # ------------------------------------------------------------ 실행 시각화 API

    def set_node_status(self, node_id: str, status: str) -> None:
        item = self.node_items.get(node_id)
        if item:
            item.set_status(status)

    def fire_edge(self, edge_id: str) -> None:
        item = self.edge_items.get(edge_id)
        if item:
            item.flash()

    def clear_statuses(self) -> None:
        for item in self.node_items.values():
            item.set_status(IDLE)
