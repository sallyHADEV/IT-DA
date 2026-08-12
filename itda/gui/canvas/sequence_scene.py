"""노드 안의 액션 시퀀스를 카드 흐름으로 그리는 씬.

노드는 액션을 순서대로 실행한다. 목록으로 보면 순서는 알지만 "흐름" 이라는 느낌이 없다.
여기서는 플로우차트와 같은 카드 모양으로 위에서 아래로 늘어놓고, 팔레트에서 끌어다 놓거나
카드를 끌어 순서를 바꾼다.

편집은 전부 기존 커맨드(:mod:`itda.gui.commands`)를 거치므로 되돌리기가 그대로 동작하고,
플로우 캔버스와 같은 되돌리기 스택을 공유한다.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsObject, QGraphicsScene, QGraphicsView, QStyle

from itda.core import registry
from itda.core.model import Action
from itda.gui import icons, style
from itda.gui.canvas.panning import PanMixin
from itda.gui.canvas.view import PALETTE_MIME
from itda.gui.commands import AddActionCommand, MoveActionCommand, RemoveActionCommand

CARD_WIDTH = 300.0
CARD_HEIGHT = 62.0
CARD_GAP = 26.0
CORNER = 10.0
MARGIN_TOP = 20.0


class ActionCardItem(QGraphicsObject):
    """액션 하나를 나타내는 카드."""

    def __init__(self, action: Action, index: int, scene_ref: SequenceScene) -> None:
        super().__init__()
        self.action = action
        self.index = index
        self._scene = scene_ref
        self._hover = False
        self._drag_from: int | None = None

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(1)
        self.setPos(0, MARGIN_TOP + index * (CARD_HEIGHT + CARD_GAP))
        self.setToolTip(self._tooltip())

    # ------------------------------------------------------------

    @property
    def type_spec(self):
        return registry.action_type(self.action.type)

    def _tooltip(self) -> str:
        spec = self.type_spec
        parts = [f"<b>{self.label()}</b>", self.summary()]
        if spec and spec.HELP:
            parts.append(spec.HELP)
        if not self.action.enabled:
            parts.append("<i>꺼져 있어 실행되지 않습니다</i>")
        return "<br>".join(parts)

    def label(self) -> str:
        spec = self.type_spec
        return self.action.title or (spec.LABEL if spec else self.action.type)

    def summary(self) -> str:
        return registry.action_summary(self.action.type, self.action.params)

    def accent(self) -> QColor:
        spec = self.type_spec
        return QColor(spec.COLOR if spec else "#7a8ba6")

    def boundingRect(self) -> QRectF:
        return QRectF(-2, -2, CARD_WIDTH + 4, CARD_HEIGHT + 4)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, CARD_WIDTH, CARD_HEIGHT), CORNER, CORNER)
        return path

    # ------------------------------------------------------------ 그리기

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, CARD_WIDTH, CARD_HEIGHT)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        enabled = self.action.enabled
        accent = self.accent() if enabled else style.TEXT_FAINT

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(style.NODE_BG_SELECTED if (selected or self._hover)
                                else style.NODE_BG))
        painter.drawRoundedRect(rect, CORNER, CORNER)

        # 왼쪽 종류 색 막대
        bar = QPainterPath()
        bar.addRoundedRect(QRectF(0, 0, 10, CARD_HEIGHT), CORNER, CORNER)
        clip = QPainterPath()
        clip.addRect(QRectF(0, 0, 5, CARD_HEIGHT))
        painter.setBrush(QBrush(accent))
        painter.drawPath(bar.intersected(clip))

        if selected:
            pen = QPen(style.ACCENT, 2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), CORNER - 1, CORNER - 1)

        # 순번
        painter.setPen(QPen(style.TEXT_FAINT))
        number_font = QFont()
        number_font.setPointSize(8)
        painter.setFont(number_font)
        painter.drawText(QRectF(12, 6, 22, 16),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         f"{self.index + 1}")

        # 아이콘
        spec = self.type_spec
        icons.action_icon(
            self.action.type, spec.CATEGORY if spec else "기타", accent
        ).paint(painter, 32, 8, 18, 18)

        # 제목
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(9)
        title_font.setStrikeOut(not enabled)
        painter.setFont(title_font)
        painter.setPen(QPen(style.NODE_TEXT if enabled else style.TEXT_FAINT))
        title_rect = QRectF(56, 6, CARD_WIDTH - 68, 18)
        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            _elide(painter, self.label(), title_rect.width()),
        )

        # 요약
        small = QFont()
        small.setPointSize(8)
        painter.setFont(small)
        painter.setPen(QPen(style.NODE_SUBTEXT if enabled else style.TEXT_FAINT))
        summary_rect = QRectF(56, 26, CARD_WIDTH - 68, 30)
        painter.drawText(
            summary_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            _elide(painter, self.summary(), summary_rect.width()),
        )

        # 사용/끔 표시 — 오른쪽 점
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(style.STATUS_COLORS["ok"] if enabled else style.SURFACE_ALT))
        painter.drawEllipse(QPointF(CARD_WIDTH - 16, CARD_HEIGHT / 2), 4, 4)

    # ------------------------------------------------------------ 상호작용

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._drag_from = self.index
        self.setZValue(3)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self.setZValue(1)
        if self._drag_from is None:
            return
        target = self._scene.index_at(self.pos().y() + CARD_HEIGHT / 2)
        origin, self._drag_from = self._drag_from, None
        if target != origin:
            self._scene.move_action(origin, target)
        else:
            self._scene.rebuild()  # 제자리로 되돌린다

    def mouseDoubleClickEvent(self, event) -> None:
        self._scene.toggle_enabled(self.action)
        event.accept()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            # 세로로만 움직인다 — 시퀀스라 가로 위치는 의미가 없다
            return QPointF(0, value.y())
        return super().itemChange(change, value)


class SequenceScene(QGraphicsScene):
    """액션 시퀀스 카드들을 담는 씬."""

    action_selected = pyqtSignal(object)  # Action | None
    changed_actions = pyqtSignal()

    def __init__(self, host, node, parent=None) -> None:
        super().__init__(parent)
        self.host = host  # FlowScene 또는 EditHost — 커맨드가 필요로 하는 것만 쓴다
        self.node = node
        self.cards: list[ActionCardItem] = []
        self.setBackgroundBrush(style.CANVAS_BG)
        self.selectionChanged.connect(self._emit_selection)
        self.rebuild()

    # ------------------------------------------------------------

    def rebuild(self) -> None:
        selected = self.selected_action()
        self.clear()
        self.cards.clear()

        for index, action in enumerate(self.node.actions):
            card = ActionCardItem(action, index, self)
            self.addItem(card)
            self.cards.append(card)

        height = MARGIN_TOP * 2 + max(1, len(self.cards)) * (CARD_HEIGHT + CARD_GAP)
        self.setSceneRect(-30, 0, CARD_WIDTH + 60, max(height, 260))

        if selected is not None:
            self.select_action(selected)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, style.CANVAS_BG)
        if not self.cards:
            painter.setPen(QPen(style.TEXT_FAINT))
            painter.drawText(
                QRectF(0, 40, CARD_WIDTH, 40),
                Qt.AlignmentFlag.AlignCenter,
                "왼쪽 팔레트에서 액션을 끌어다 놓으세요",
            )
            return

        # 카드 사이 화살표
        pen = QPen(style.EDGE, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(QBrush(style.EDGE))
        for index in range(len(self.cards) - 1):
            top = MARGIN_TOP + index * (CARD_HEIGHT + CARD_GAP) + CARD_HEIGHT
            bottom = top + CARD_GAP
            x = CARD_WIDTH / 2
            painter.drawLine(QPointF(x, top + 2), QPointF(x, bottom - 6))
            head = QPainterPath()
            head.moveTo(x, bottom - 1)
            head.lineTo(x - 4, bottom - 8)
            head.lineTo(x + 4, bottom - 8)
            head.closeSubpath()
            painter.drawPath(head)

    # ------------------------------------------------------------ 편집

    def index_at(self, y: float) -> int:
        """세로 위치 → 삽입/이동할 자리."""
        step = CARD_HEIGHT + CARD_GAP
        raw = int(round((y - MARGIN_TOP) / step))
        return max(0, min(len(self.node.actions) - 1, raw))

    def drop_index_at(self, y: float) -> int:
        step = CARD_HEIGHT + CARD_GAP
        raw = int(round((y - MARGIN_TOP) / step))
        return max(0, min(len(self.node.actions), raw))

    def add_action(self, type_id: str, index: int | None = None) -> Action | None:
        spec = registry.action_type(type_id)
        if spec is None:
            return None
        action = Action(type=type_id, params=spec.defaults())
        position = len(self.node.actions) if index is None else index
        self.host.undo_stack.push(AddActionCommand(self.host, self.node, action, position))
        self.rebuild()
        self.select_action(action)
        self.changed_actions.emit()
        return action

    def move_action(self, origin: int, target: int) -> None:
        self.host.undo_stack.push(MoveActionCommand(self.host, self.node, origin, target))
        self.rebuild()
        self.changed_actions.emit()

    def remove_action(self, action: Action) -> None:
        if action not in self.node.actions:
            return
        self.host.undo_stack.push(RemoveActionCommand(self.host, self.node, action))
        self.rebuild()
        self.changed_actions.emit()

    def delete_selected(self) -> None:
        action = self.selected_action()
        if action is not None:
            self.remove_action(action)

    def duplicate_selected(self) -> None:
        from itda.core.serde import clone

        action = self.selected_action()
        if action is None:
            return
        copy = clone(action)
        copy.id = Action().id
        index = self.node.actions.index(action) + 1
        self.host.undo_stack.push(AddActionCommand(self.host, self.node, copy, index))
        self.rebuild()
        self.select_action(copy)
        self.changed_actions.emit()

    def toggle_enabled(self, action: Action) -> None:
        from itda.gui.commands import SetAttrCommand

        self.host.undo_stack.push(
            SetAttrCommand(self.host, action, "enabled", not action.enabled, "액션 사용 전환")
        )
        self.rebuild()
        self.changed_actions.emit()

    # ------------------------------------------------------------ 선택

    def selected_action(self) -> Action | None:
        for item in self.selectedItems():
            if isinstance(item, ActionCardItem):
                return item.action
        return None

    def select_action(self, action: Action) -> None:
        """카드 하나를 고른다.

        선택 해제와 선택을 한 번의 알림으로 묶는다. 나누면 "아무것도 선택 안 됨" 이 잠깐
        끼어들어 속성 패널이 노드 화면을 통째로 만들었다가 곧바로 버린다 — 헛일이다.
        """
        blocked = self.blockSignals(True)
        try:
            self.clearSelection()
            for card in self.cards:
                if card.action is action:
                    card.setSelected(True)
                    break
        finally:
            self.blockSignals(blocked)
        self._emit_selection()

    def _emit_selection(self) -> None:
        self.action_selected.emit(self.selected_action())


class SequenceView(PanMixin, QGraphicsView):
    """시퀀스 캔버스 뷰. 팔레트에서 끌어다 놓는 것을 받는다."""

    status_message = pyqtSignal(str)

    def __init__(self, scene: SequenceScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setAcceptDrops(True)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    @property
    def sequence(self) -> SequenceScene:
        return self.scene()  # type: ignore[return-value]

    # 마우스 화면 이동은 PanMixin 이 담당한다 (플로우 캔버스와 같은 조작이어야 하므로).

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
        kind, _, type_id = bytes(data).decode("utf-8").partition(":")
        if kind != "action":
            self.status_message.emit("노드는 플로우 캔버스에 놓으세요. 여기에는 액션만 넣습니다.")
            event.ignore()
            return

        position = self.mapToScene(event.position().toPoint())
        self.sequence.add_action(type_id, self.sequence.drop_index_at(position.y()))
        event.acceptProposedAction()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.sequence.delete_selected()
            event.accept()
            return
        super().keyPressEvent(event)


def _elide(painter: QPainter, text: str, width: float) -> str:
    metrics = QFontMetrics(painter.font())
    return metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(max(10, width)))
