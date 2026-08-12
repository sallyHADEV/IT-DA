"""되돌리기(Undo) 커맨드.

플로우 캔버스와 속성 패널의 모든 편집은 여기를 거친다. 각 플로우 탭이 자기 QUndoStack 을
갖는다. 커맨드는 모델 객체를 직접 참조한다 — 노드를 지웠다 되살려도 같은 객체가 돌아오므로
참조가 계속 유효하다.
"""

from __future__ import annotations

import time
from typing import Any

from PyQt6.QtGui import QUndoCommand

from PyQt6.QtGui import QUndoStack

from itda.core.model import Action, Edge, Node

# mergeWith 용 커맨드 id. 같은 대상에 연속으로 들어오는 값 편집을 하나로 합친다.
_ID_SET_ATTR = 1001
_ID_SET_PARAM = 1002
_ID_MOVE = 1003

#: 이 시간(초) 안에 같은 대상을 또 고치면 한 번의 편집으로 본다.
MERGE_WINDOW = 1.2


class EditHost:
    """캔버스 밖에서 커맨드를 쓰기 위한 최소 호스트.

    커맨드와 속성/액션 패널은 ``project``, ``undo_stack``, ``mark_changed()``,
    ``notify_edited()`` 네 가지만 있으면 동작한다. :class:`~itda.gui.canvas.scene.FlowScene`
    이 그 인터페이스를 이미 만족하므로, 상황(State) 전이의 액션 시퀀스처럼 플로우에 속하지
    않는 편집에는 이 가벼운 대역을 쓴다.
    """

    def __init__(self, project, on_changed=None) -> None:
        self.project = project
        self.undo_stack = QUndoStack()
        self._on_changed = on_changed

    def mark_changed(self) -> None:
        if self.project is not None:
            self.project.mark_dirty()
        if self._on_changed is not None:
            self._on_changed()

    def notify_edited(self, _target) -> None:
        if self._on_changed is not None:
            self._on_changed()


class _SceneCommand(QUndoCommand):
    """공통: 실행 후 씬을 갱신하고 프로젝트를 더티로 표시한다."""

    def __init__(self, scene, text: str) -> None:
        super().__init__(text)
        self.scene = scene

    def touch(self) -> None:
        self.scene.mark_changed()


# ---------------------------------------------------------------- 노드 / 엣지


class AddNodeCommand(_SceneCommand):
    def __init__(self, scene, node: Node, text: str = "노드 추가") -> None:
        super().__init__(scene, text)
        self.node = node

    def redo(self) -> None:
        self.scene.flow.nodes.append(self.node)
        self.scene.create_node_item(self.node)
        self.scene.select_only(self.node.id)
        self.touch()

    def undo(self) -> None:
        self.scene.destroy_node_item(self.node.id)
        if self.node in self.scene.flow.nodes:
            self.scene.flow.nodes.remove(self.node)
        self.touch()


class RemoveItemsCommand(_SceneCommand):
    """선택한 노드와 엣지를 지운다. 노드에 붙은 엣지도 함께 사라진다."""

    def __init__(self, scene, node_ids: list[str], edge_ids: list[str]) -> None:
        flow = scene.flow
        self.nodes: list[tuple[int, Node]] = [
            (i, n) for i, n in enumerate(flow.nodes) if n.id in set(node_ids)
        ]
        doomed = set(node_ids)
        self.edges: list[tuple[int, Edge]] = [
            (i, e)
            for i, e in enumerate(flow.edges)
            if e.id in set(edge_ids) or e.src_node in doomed or e.dst_node in doomed
        ]
        count = len(self.nodes) + len(self.edges)
        super().__init__(scene, f"{count}개 삭제" if count > 1 else "삭제")

    def redo(self) -> None:
        flow = self.scene.flow
        for _, e in self.edges:
            if e in flow.edges:
                flow.edges.remove(e)
                self.scene.destroy_edge_item(e.id)
        for _, n in self.nodes:
            if n in flow.nodes:
                flow.nodes.remove(n)
                self.scene.destroy_node_item(n.id)
        self.touch()

    def undo(self) -> None:
        flow = self.scene.flow
        for i, n in self.nodes:
            flow.nodes.insert(min(i, len(flow.nodes)), n)
            self.scene.create_node_item(n)
        for i, e in self.edges:
            flow.edges.insert(min(i, len(flow.edges)), e)
            self.scene.create_edge_item(e)
        self.touch()


class MoveNodesCommand(_SceneCommand):
    """노드 이동. 드래그 중 여러 번 들어와도 하나로 합친다."""

    def __init__(self, scene, moves: dict[str, tuple[tuple[float, float], tuple[float, float]]]) -> None:
        super().__init__(scene, "노드 이동" if len(moves) == 1 else f"{len(moves)}개 이동")
        self.moves = dict(moves)
        self.stamp = time.time()

    def id(self) -> int:
        return _ID_MOVE

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, MoveNodesCommand):
            return False
        if set(other.moves) != set(self.moves) or other.stamp - self.stamp > MERGE_WINDOW:
            return False
        for key, (_, new) in other.moves.items():
            old = self.moves[key][0]
            self.moves[key] = (old, new)
        self.stamp = other.stamp
        return True

    def _apply(self, index: int) -> None:
        for node_id, pair in self.moves.items():
            node = self.scene.flow.node(node_id)
            if node is None:
                continue
            node.x, node.y = pair[index]
            self.scene.sync_node_position(node_id)
        self.touch()

    def redo(self) -> None:
        self._apply(1)

    def undo(self) -> None:
        self._apply(0)


class AddEdgeCommand(_SceneCommand):
    def __init__(self, scene, edge: Edge) -> None:
        super().__init__(scene, "연결")
        self.edge = edge

    def redo(self) -> None:
        self.scene.flow.edges.append(self.edge)
        self.scene.create_edge_item(self.edge)
        self.touch()

    def undo(self) -> None:
        if self.edge in self.scene.flow.edges:
            self.scene.flow.edges.remove(self.edge)
        self.scene.destroy_edge_item(self.edge.id)
        self.touch()


class ReconnectEdgeCommand(_SceneCommand):
    """이미 있는 엣지의 끝을 다른 노드로 옮긴다."""

    def __init__(self, scene, edge: Edge, dst_node: str, dst_port: str) -> None:
        super().__init__(scene, "연결 변경")
        self.edge = edge
        self.before = (edge.dst_node, edge.dst_port)
        self.after = (dst_node, dst_port)

    def _set(self, value: tuple[str, str]) -> None:
        self.edge.dst_node, self.edge.dst_port = value
        self.scene.sync_edge(self.edge.id)
        self.touch()

    def redo(self) -> None:
        self._set(self.after)

    def undo(self) -> None:
        self._set(self.before)


# ---------------------------------------------------------------- 값 편집


class SetAttrCommand(_SceneCommand):
    """데이터클래스 속성 하나를 바꾼다 (노드 제목, 재시도 횟수 등)."""

    def __init__(self, scene, target: Any, attr: str, value: Any, text: str = "") -> None:
        super().__init__(scene, text or f"{attr} 변경")
        self.target = target
        self.attr = attr
        self.before = getattr(target, attr)
        self.after = value
        self.stamp = time.time()

    def id(self) -> int:
        return _ID_SET_ATTR

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, SetAttrCommand):
            return False
        if other.target is not self.target or other.attr != self.attr:
            return False
        if other.stamp - self.stamp > MERGE_WINDOW:
            return False
        self.after = other.after
        self.stamp = other.stamp
        return True

    def redo(self) -> None:
        setattr(self.target, self.attr, self.after)
        self.scene.notify_edited(self.target)
        self.touch()

    def undo(self) -> None:
        setattr(self.target, self.attr, self.before)
        self.scene.notify_edited(self.target)
        self.touch()


class SetParamCommand(_SceneCommand):
    """params 딕셔너리의 키 하나를 바꾼다 (액션 파라미터)."""

    def __init__(self, scene, owner: Any, key: str, value: Any, text: str = "") -> None:
        super().__init__(scene, text or f"{key} 변경")
        self.owner = owner  # Action 또는 Node — params 딕셔너리를 가진 객체
        self.key = key
        self.before = owner.params.get(key)
        self.after = value
        self.stamp = time.time()

    def id(self) -> int:
        return _ID_SET_PARAM

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, SetParamCommand):
            return False
        if other.owner is not self.owner or other.key != self.key:
            return False
        if other.stamp - self.stamp > MERGE_WINDOW:
            return False
        self.after = other.after
        self.stamp = other.stamp
        return True

    def redo(self) -> None:
        self.owner.params[self.key] = self.after
        self.scene.notify_edited(self.owner)
        self.touch()

    def undo(self) -> None:
        self.owner.params[self.key] = self.before
        self.scene.notify_edited(self.owner)
        self.touch()


# ---------------------------------------------------------------- 노드 내부 액션


class AddActionCommand(_SceneCommand):
    def __init__(self, scene, node: Node, action: Action, index: int = -1) -> None:
        super().__init__(scene, f"액션 추가: {action.type}")
        self.node = node
        self.action = action
        self.index = len(node.actions) if index < 0 else index

    def redo(self) -> None:
        self.node.actions.insert(self.index, self.action)
        self.scene.notify_edited(self.node)
        self.touch()

    def undo(self) -> None:
        if self.action in self.node.actions:
            self.node.actions.remove(self.action)
        self.scene.notify_edited(self.node)
        self.touch()


class RemoveActionCommand(_SceneCommand):
    def __init__(self, scene, node: Node, action: Action) -> None:
        super().__init__(scene, "액션 삭제")
        self.node = node
        self.action = action
        self.index = node.actions.index(action)

    def redo(self) -> None:
        if self.action in self.node.actions:
            self.node.actions.remove(self.action)
        self.scene.notify_edited(self.node)
        self.touch()

    def undo(self) -> None:
        self.node.actions.insert(min(self.index, len(self.node.actions)), self.action)
        self.scene.notify_edited(self.node)
        self.touch()


class MoveActionCommand(_SceneCommand):
    def __init__(self, scene, node: Node, from_index: int, to_index: int) -> None:
        super().__init__(scene, "액션 순서 변경")
        self.node = node
        self.from_index = from_index
        self.to_index = to_index

    def _move(self, a: int, b: int) -> None:
        actions = self.node.actions
        if not (0 <= a < len(actions)) or not (0 <= b <= len(actions)):
            return
        actions.insert(b, actions.pop(a))
        self.scene.notify_edited(self.node)
        self.touch()

    def redo(self) -> None:
        self._move(self.from_index, self.to_index)

    def undo(self) -> None:
        self._move(self.to_index, self.from_index)


class ReplaceActionsCommand(_SceneCommand):
    """액션 목록 전체를 갈아끼운다 (붙여넣기, 일괄 정리)."""

    def __init__(self, scene, node: Node, actions: list[Action], text: str = "액션 변경") -> None:
        super().__init__(scene, text)
        self.node = node
        self.before = list(node.actions)
        self.after = list(actions)

    def redo(self) -> None:
        self.node.actions[:] = self.after
        self.scene.notify_edited(self.node)
        self.touch()

    def undo(self) -> None:
        self.node.actions[:] = self.before
        self.scene.notify_edited(self.node)
        self.touch()
