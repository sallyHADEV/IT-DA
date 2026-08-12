"""플로우 캔버스 뷰 — 줌, 팬, 드래그 앤 드롭, 컨텍스트 메뉴."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QPainter
from PyQt6.QtWidgets import QApplication, QGraphicsView, QMenu

from itda.core import registry
from itda.gui.canvas.node_item import NodeItem
from itda.gui.canvas.panning import PanMixin
from itda.gui.canvas.scene import FlowScene

#: 팔레트에서 끌어온 항목의 MIME 타입. 값은 "node:<타입>" 또는 "action:<타입>".
PALETTE_MIME = "application/x-itda-palette"

ZOOM_MIN = 0.25
ZOOM_MAX = 3.0


class FlowView(PanMixin, QGraphicsView):
    """캔버스 뷰. 한 탭에 하나."""

    zoom_changed = pyqtSignal(float)
    status_message = pyqtSignal(str)

    def __init__(self, scene: FlowScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        # 노드가 수백 개인 플로우에서 팬·줌이 버벅이지 않게
        self.setOptimizationFlag(QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheBackground)
        self.setAcceptDrops(True)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self._zoom = 1.0
        self.read_only = False
        self._build_actions()

    def set_read_only(self, locked: bool) -> None:
        """편집만 막고 보기는 살려 둔다.

        매크로가 실행되는 동안 쓴다. 실행은 GUI 스레드에서 돌면서 중간중간 이벤트를
        처리하기 때문에(:meth:`RunController._tick`), 그 틈에 노드를 지우거나 연결을
        바꾸면 엔진이 들고 있던 모델과 어긋난다. 그렇다고 뷰 전체를 비활성화하면 실행
        상황을 볼 수 없으므로, **선택·드래그·드롭만 막고 줌·팬은 남긴다.**
        """
        self.read_only = locked
        self.setInteractive(not locked)
        self.setAcceptDrops(not locked)
        for act in (
            self.act_delete, self.act_copy, self.act_paste, self.act_cut,
            self.act_duplicate, self.act_layout,
        ):
            act.setEnabled(not locked)
        if locked:
            self.flow_scene.clearSelection()

    @property
    def flow_scene(self) -> FlowScene:
        return self.scene()  # type: ignore[return-value]

    # ------------------------------------------------------------ 단축키

    def _build_actions(self) -> None:
        def add(text: str, shortcut, slot) -> QAction:
            act = QAction(text, self)
            if shortcut:
                act.setShortcut(shortcut)
            act.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            act.triggered.connect(slot)
            self.addAction(act)
            return act

        self.act_delete = add("삭제", QKeySequence.StandardKey.Delete, self._delete)
        self.act_copy = add("복사", QKeySequence.StandardKey.Copy, self._copy)
        self.act_paste = add("붙여넣기", QKeySequence.StandardKey.Paste, self._paste)
        self.act_cut = add("잘라내기", QKeySequence.StandardKey.Cut, self._cut)
        self.act_duplicate = add("복제", "Ctrl+D", lambda: self.flow_scene.duplicate_selection())
        self.act_select_all = add("모두 선택", QKeySequence.StandardKey.SelectAll, self._select_all)
        self.act_fit = add("전체 보기", "Ctrl+0", self.fit_all)
        self.act_zoom_in = add("확대", QKeySequence.StandardKey.ZoomIn, lambda: self.zoom_by(1.15))
        self.act_zoom_out = add("축소", QKeySequence.StandardKey.ZoomOut, lambda: self.zoom_by(1 / 1.15))
        self.act_layout = add("자동 정렬", "Ctrl+L", lambda: self.flow_scene.auto_layout())

    def _delete(self) -> None:
        self.flow_scene.delete_selection()

    def _copy(self) -> None:
        text = self.flow_scene.copy_selection()
        if text:
            QApplication.clipboard().setText(text)
            self.status_message.emit(f"{len(self.flow_scene.selected_nodes())}개 노드를 복사했습니다")

    def _cut(self) -> None:
        self._copy()
        self._delete()

    def _paste(self) -> None:
        text = QApplication.clipboard().text()
        pos = self.mapToScene(self.mapFromGlobal(self.cursor().pos()))
        if not self.viewport().rect().contains(self.mapFromGlobal(self.cursor().pos())):
            pos = self.mapToScene(self.viewport().rect().center())
        nodes = self.flow_scene.paste(text, pos)
        if nodes:
            self.status_message.emit(f"{len(nodes)}개 노드를 붙여넣었습니다")

    def _select_all(self) -> None:
        for item in self.flow_scene.node_items.values():
            item.setSelected(True)

    # ------------------------------------------------------------ 줌 / 팬

    def zoom_by(self, factor: float) -> None:
        target = max(ZOOM_MIN, min(ZOOM_MAX, self._zoom * factor))
        factor = target / self._zoom
        if abs(factor - 1.0) < 1e-6:
            return
        self._zoom = target
        self.scale(factor, factor)
        self._apply_detail()
        self.zoom_changed.emit(self._zoom)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self._zoom = 1.0
        self._apply_detail()
        self.zoom_changed.emit(self._zoom)

    def _apply_detail(self) -> None:
        """배율이 바뀌면 씬에 알려 자잘한 것을 감추게 한다 (노드가 많을 때 체감된다)."""
        self.flow_scene.apply_detail(self._zoom)

    def fit_all(self) -> None:
        items = list(self.flow_scene.node_items.values())
        if not items:
            self.reset_zoom()
            return
        rect = items[0].sceneBoundingRect()
        for item in items[1:]:
            rect = rect.united(item.sceneBoundingRect())
        rect = rect.adjusted(-60, -60, 60, 60)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()
        self._apply_detail()
        self.zoom_changed.emit(self._zoom)

    def center_on_node(self, node_id: str) -> None:
        item = self.flow_scene.node_items.get(node_id)
        if item:
            self.centerOn(item)

    def wheelEvent(self, event) -> None:
        # 휠은 줌. 화면 이동은 가운데 버튼 드래그나 Alt/Shift + 좌드래그 (PanMixin).
        self.zoom_by(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
        event.accept()

    # 마우스 화면 이동은 PanMixin 이 담당한다 (시퀀스 뷰와 같은 조작이어야 하므로).

    # ------------------------------------------------------------ 드래그 앤 드롭

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(PALETTE_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(PALETTE_MIME):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        data = event.mimeData().data(PALETTE_MIME)
        if not data:
            super().dropEvent(event)
            return
        payload = bytes(data).decode("utf-8")
        pos = self.mapToScene(event.position().toPoint())
        kind, _, type_id = payload.partition(":")
        if kind == "node":
            created = self.flow_scene.add_node(type_id, pos)
            if created is None:
                self.status_message.emit("시작 노드는 플로우에 하나만 둘 수 있습니다")
        elif kind == "action":
            self.flow_scene.add_action_node(type_id, pos)
        event.acceptProposedAction()

    # ------------------------------------------------------------ 컨텍스트 메뉴

    def contextMenuEvent(self, event) -> None:
        self.build_context_menu(event.pos()).exec(event.globalPos())

    def build_context_menu(self, pos: QPoint) -> QMenu:
        """오른쪽 클릭 메뉴를 만든다 (띄우지는 않는다).

        만드는 것과 띄우는 것을 나눠 두면 무엇이 들어 있는지 테스트할 수 있다.
        """
        scene_pos = self.mapToScene(pos)
        item = self.itemAt(pos)
        menu = QMenu(self)

        if self.read_only:
            # 메뉴 항목은 씬을 직접 고치므로, 잠겨 있으면 보기 기능만 남긴다
            menu.addAction(self.act_fit)
            menu.addAction(self.act_zoom_in)
            menu.addAction(self.act_zoom_out)
            return menu

        if isinstance(item, NodeItem):
            item.setSelected(True)
            menu.addAction("속성 편집", lambda: self.flow_scene.node_double_clicked.emit(item.node.id))
            bp = menu.addAction("중단점 토글")
            bp.setCheckable(True)
            bp.setChecked(item.node.breakpoint)
            bp.triggered.connect(lambda: self._toggle_breakpoint(item))
            menu.addSeparator()
            menu.addAction(self.act_copy)
            menu.addAction(self.act_duplicate)
            menu.addAction(self.act_delete)
        elif item is not None and not isinstance(item, NodeItem) and self.flow_scene.selectedItems():
            menu.addAction(self.act_delete)
        else:
            add_menu = menu.addMenu("노드 추가")
            for type_id, spec in registry.NODE_TYPES.items():
                act = add_menu.addAction(f"{spec.icon}  {spec.label}")
                act.triggered.connect(
                    lambda _=False, t=type_id, p=scene_pos: self.flow_scene.add_node(t, p)
                )
            menu.addSeparator()
            menu.addAction(self.act_paste)
            menu.addAction(self.act_select_all)
            menu.addSeparator()
            menu.addAction(self.act_layout)
            menu.addAction(self.act_fit)
            snap = menu.addAction("격자에 맞추기")
            snap.setCheckable(True)
            snap.setChecked(self.flow_scene.snap_enabled)
            snap.triggered.connect(self._toggle_snap)

        return menu

    def _toggle_breakpoint(self, item: NodeItem) -> None:
        item.node.breakpoint = not item.node.breakpoint
        item.update()
        self.flow_scene.mark_changed()

    def _toggle_snap(self) -> None:
        self.flow_scene.snap_enabled = not self.flow_scene.snap_enabled
        self.status_message.emit(
            "격자 맞춤 " + ("켜짐" if self.flow_scene.snap_enabled else "꺼짐")
        )

    # ------------------------------------------------------------ 키보드 이동

    def keyPressEvent(self, event) -> None:
        arrows = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if event.key() in arrows and not self.read_only and self.flow_scene.selected_nodes():
            step = 1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 10
            dx, dy = arrows[event.key()]
            scene = self.flow_scene
            moves = {}
            for node in scene.selected_nodes():
                old = (node.x, node.y)
                moves[node.id] = (old, (old[0] + dx * step, old[1] + dy * step))
            if moves:
                from itda.gui.commands import MoveNodesCommand

                scene.undo_stack.push(MoveNodesCommand(scene, moves))
            event.accept()
            return
        super().keyPressEvent(event)
