"""엣지(연결선) 그래픽 아이템.

출구에서 입구로 흐르는 베지어 곡선. 실행 중에는 흐름이 지나갈 때 잠깐 밝아진다.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsObject, QStyle

ARROW = 9.0


class EdgeItem(QGraphicsObject):
    def __init__(self, edge, scene_ref) -> None:
        super().__init__()
        self.edge = edge
        self._scene = scene_ref
        self._path = QPainterPath()
        self._src = QPointF()
        self._dst = QPointF()
        self._flash = 0.0
        self._anim: QVariantAnimation | None = None
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setZValue(0)
        self._hover = False
        self.sync()

    # ------------------------------------------------------------ 경로

    def sync(self) -> None:
        """양 끝 노드의 현재 위치로 곡선을 다시 계산한다."""
        src_item = self._scene.node_items.get(self.edge.src_node)
        dst_item = self._scene.node_items.get(self.edge.dst_node)
        if src_item is None or dst_item is None:
            self.prepareGeometryChange()
            self._path = QPainterPath()
            return

        self._src = src_item.port_pos(self.edge.src_port, is_output=True)
        self._dst = dst_item.port_pos(self.edge.dst_port, is_output=False)

        dx = abs(self._dst.x() - self._src.x())
        reach = max(55.0, min(dx * 0.6, 220.0))
        c1 = QPointF(self._src.x() + reach, self._src.y())
        c2 = QPointF(self._dst.x() - reach, self._dst.y())

        path = QPainterPath(self._src)
        path.cubicTo(c1, c2, self._dst)
        self.prepareGeometryChange()
        self._path = path
        self.update()

    def boundingRect(self) -> QRectF:
        return self._path.boundingRect().adjusted(-14, -14, 14, 14)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(self._path)

    # ------------------------------------------------------------ 그리기

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self._path.isEmpty():
            return
        from itda.gui import style

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        detail = option.levelOfDetailFromTransform(painter.worldTransform())

        color = QColor(style.EDGE)
        width = 1.8
        if selected or self._hover:
            color = QColor(style.EDGE_SELECTED)
            width = 2.4
        if self._flash > 0:
            color = _mix(color, QColor(style.EDGE_FIRED), self._flash)
            width = 1.8 + 1.8 * self._flash

        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if self.edge.src_port in ("fail", "false"):
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([5, 4])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path)

        if detail < 0.3:
            return  # 축소 상태에서는 선만 — 화살촉·라벨은 어차피 안 보인다

        # 화살촉
        angle = _end_angle(self._path)
        tip = self._dst
        left = tip + QPointF(
            -ARROW * math.cos(angle - math.pi / 7), -ARROW * math.sin(angle - math.pi / 7)
        )
        right = tip + QPointF(
            -ARROW * math.cos(angle + math.pi / 7), -ARROW * math.sin(angle + math.pi / 7)
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPolygon(QPolygonF([tip, left, right]))

        if self.edge.label:
            mid = self._path.pointAtPercent(0.5)
            painter.setPen(QPen(style.TEXT_FAINT))
            painter.drawText(QRectF(mid.x() - 50, mid.y() - 16, 100, 14),
                             Qt.AlignmentFlag.AlignCenter, self.edge.label)

    # ------------------------------------------------------------ 상호작용 / 실행 표시

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def flash(self) -> None:
        """흐름이 이 연결을 지나갔음을 잠깐 표시한다."""
        if self._anim is not None:
            self._anim.stop()
        anim = QVariantAnimation()
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(650)
        anim.valueChanged.connect(self._on_flash)
        anim.finished.connect(lambda: setattr(self, "_anim", None))
        self._anim = anim
        anim.start()

    def _on_flash(self, value) -> None:
        self._flash = float(value)
        self.update()


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def _end_angle(path: QPainterPath) -> float:
    """곡선 끝의 진행 방향(라디안)."""
    if path.isEmpty():
        return 0.0
    a = path.pointAtPercent(0.94)
    b = path.pointAtPercent(1.0)
    return math.atan2(b.y() - a.y(), b.x() - a.x())
