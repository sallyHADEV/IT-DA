"""노드 그래픽 아이템.

노드는 플랫한 카드다. 왼쪽에 노드 타입 색 막대, 그 옆에 제목과 요약, 아래에 배지(상황 조건,
재시도, 액션 개수). 실행 상태는 카드 테두리 색으로만 표시해 카드 색(=노드 종류)을 가리지 않는다.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsObject, QStyle

from itda.core import registry
from itda.core.events import IDLE
from itda.gui import icons, style

CORNER = 10.0
BAR_W = 5.0
HEADER_H = 30.0
PORT_R = 5.0
PORT_HIT = 9.0
MIN_H = 62.0
#: 출구 하나가 차지하는 세로 간격. 7pt 라벨(글자 높이 9px)이 겹치지 않을 만큼.
PORT_SPACING = 17.0
#: 마지막 출구 아래로 남기는 여백 (layout_ports 의 span 계산과 짝을 이룬다)
PORT_BOTTOM_PAD = 8.0


class PortItem(QGraphicsObject):
    """노드의 입/출력 접점. 여기서 드래그하면 연결이 시작된다."""

    def __init__(self, node_item: NodeItem, name: str, is_output: bool) -> None:
        super().__init__(node_item)
        self.node_item = node_item
        self.name = name
        self.is_output = is_output
        self._hover = False
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self.setToolTip(f"{'출구' if is_output else '입구'}: {name}")

    def boundingRect(self) -> QRectF:
        return QRectF(-PORT_HIT, -PORT_HIT, PORT_HIT * 2, PORT_HIT * 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = style.PORT_HOVER if self._hover else style.PORT
        r = PORT_R + (1.5 if self._hover else 0)
        painter.setPen(QPen(style.CANVAS_BG, 2))
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QPointF(0, 0), r, r)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.is_output:
            self.scene().begin_connection(self)
            event.accept()
            return
        event.ignore()

    def scene_pos(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))


class NodeItem(QGraphicsObject):
    """플로우 노드 하나."""

    geometry_changed = pyqtSignal()

    def __init__(self, node, scene_ref) -> None:
        super().__init__()
        self.node = node
        self._scene = scene_ref
        self.status = IDLE
        self._hover = False
        self._press_pos: tuple[float, float] | None = None
        self.in_ports: dict[str, PortItem] = {}
        self.out_ports: dict[str, PortItem] = {}

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setPos(node.x, node.y)
        self.setZValue(1)
        # 아이템 캐시는 쓰지 않는다 — 줌마다 무효화돼 이득이 없고 메모리만 먹는다(측정 확인).
        self.rebuild_ports()
        self.refresh()

    # ------------------------------------------------------------ 기하

    @property
    def type_spec(self):
        return registry.node_type(self.node.type)

    def width(self) -> float:
        return max(120.0, float(self.node.width or 190))

    def out_port_count(self) -> int:
        """출구 개수. 위젯이 아니라 모델에서 얻는다 — 포트를 만들기 전에도 높이를 재야 한다."""
        spec = self.type_spec
        outs = spec.ports_out(self.node.params) if spec else ["ok", "fail"]
        return max(1, len(outs))

    def height(self) -> float:
        spec = self.type_spec
        rows = 1  # 요약 줄
        if self.node.required_state and (spec is None or spec.allows_state):
            rows += 1
        base = max(MIN_H, HEADER_H + 16 + rows * 15)

        # 출구가 여럿이면 라벨이 겹치지 않을 만큼 키운다. 안 그러면 62px 기본 높이에서
        # 출구 2개가 8px 간격으로 붙어 "성공"·"실패" 글자가 서로 위에 찍힌다(실측).
        outs = self.out_port_count()
        if outs > 1:
            base = max(base, HEADER_H + PORT_BOTTOM_PAD + PORT_SPACING * (outs + 1))
        return base

    def boundingRect(self) -> QRectF:
        return QRectF(-2, -2, self.width() + 4, self.height() + 4)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), CORNER, CORNER)
        return path

    # ------------------------------------------------------------ 포트

    def rebuild_ports(self) -> None:
        """노드 타입(및 파라미터)에 맞춰 포트를 다시 만든다."""
        spec = self.type_spec
        ins = list(spec.in_ports) if spec else ["in"]
        outs = spec.ports_out(self.node.params) if spec else ["ok", "fail"]

        for existing in (self.in_ports, self.out_ports):
            for item in existing.values():
                item.setParentItem(None)
                if item.scene():
                    item.scene().removeItem(item)
            existing.clear()

        for name in ins:
            self.in_ports[name] = PortItem(self, name, is_output=False)
        for name in outs:
            self.out_ports[name] = PortItem(self, name, is_output=True)
        self.layout_ports()

    def layout_ports(self) -> None:
        h, w = self.height(), self.width()

        def place(items: dict[str, PortItem], x: float) -> None:
            n = len(items)
            if not n:
                return
            top = HEADER_H
            span = max(h - top - PORT_BOTTOM_PAD, 10)
            for i, item in enumerate(items.values()):
                y = top + span * (i + 1) / (n + 1)
                item.setPos(x, y)

        place(self.in_ports, 0.0)
        place(self.out_ports, w)

    def port_pos(self, name: str, is_output: bool) -> QPointF:
        table = self.out_ports if is_output else self.in_ports
        item = table.get(name)
        if item is None and table:
            item = next(iter(table.values()))
        if item is None:
            return self.mapToScene(QPointF(self.width() if is_output else 0, self.height() / 2))
        return item.scene_pos()

    def port_at(self, scene_pos: QPointF, is_output: bool) -> PortItem | None:
        table = self.out_ports if is_output else self.in_ports
        for item in table.values():
            if (item.scene_pos() - scene_pos).manhattanLength() < 16:
                return item
        return next(iter(table.values()), None)

    # ------------------------------------------------------------ 갱신

    def refresh(self) -> None:
        """모델이 바뀐 뒤 화면을 맞춘다."""
        self.prepareGeometryChange()
        self.rebuild_ports()
        spec = self.type_spec
        tip = [f"<b>{self.node.title}</b>", f"종류: {spec.label if spec else self.node.type}"]
        if self.node.required_state:
            tip.append(f"필요 상황: {self.node.required_state}")
        if self.node.actions:
            tip.append("<br>".join(
                f"{i + 1}. {registry.action_summary(a.type, a.params)}"
                for i, a in enumerate(self.node.actions[:8])
            ))
        self.setToolTip("<br>".join(tip))
        self.update()
        self.geometry_changed.emit()

    def set_status(self, status: str) -> None:
        if status != self.status:
            self.status = status
            self.update()

    # ------------------------------------------------------------ 그리기

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        rect = QRectF(0, 0, w, h)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # 많이 축소한 상태에서는 글자를 그려 봐야 읽히지 않는다. 가장 비싼 작업이므로 생략한다.
        detail = option.levelOfDetailFromTransform(painter.worldTransform())
        spec = self.type_spec
        accent = QColor(self.node.color) if self.node.color else style.node_color(
            self.node.type, spec.color if spec else "#4a6fa5"
        )

        # 카드
        body = style.NODE_BG_SELECTED if (selected or self._hover) else style.NODE_BG
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(body))
        painter.drawRoundedRect(rect, CORNER, CORNER)

        # 왼쪽 타입 색 막대
        bar = QPainterPath()
        bar.addRoundedRect(QRectF(0, 0, BAR_W * 2, h), CORNER, CORNER)
        clip = QPainterPath()
        clip.addRect(QRectF(0, 0, BAR_W, h))
        painter.setBrush(QBrush(accent))
        painter.drawPath(bar.intersected(clip))

        # 상태 / 선택 테두리
        border = None
        if self.status != IDLE:
            border = QPen(style.status_color(self.status), 2)
        elif selected:
            border = QPen(style.ACCENT, 2)
        if border is not None:
            border.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(border)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), CORNER - 1, CORNER - 1)

        if self.node.breakpoint:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(style.STATUS_COLORS["fail"]))
            painter.drawEllipse(QPointF(w - 12, 12), 4, 4)

        if detail < 0.35:
            return  # 이 배율에서는 카드 색과 상태만 보인다

        left = BAR_W + 9

        # 아이콘 + 제목. 아이콘은 벡터로 그린다 — 글리프 문자는 폰트에 없으면 네모가 된다.
        icons.node_icon(self.node.type, accent).paint(
            painter, QRect(int(left), 8, 16, 16)
        )

        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(9)
        painter.setFont(title_font)
        painter.setPen(QPen(style.NODE_TEXT))
        title_rect = QRectF(left + 20, 6, w - left - 30, 19)
        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            _elide(painter, self.node.title or (spec.label if spec else self.node.type), title_rect.width()),
        )

        if detail < 0.6:
            return  # 제목까지만

        # 본문 요약
        small = QFont()
        small.setPointSize(8)
        painter.setFont(small)
        painter.setPen(QPen(style.NODE_SUBTEXT))
        y = HEADER_H + 2
        body_rect = QRectF(left, y, w - left - 10, 14)
        painter.drawText(
            body_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            _elide(painter, self._summary_line(), body_rect.width()),
        )
        y += 15

        # 상황 배지
        if self.node.required_state and (spec is None or spec.allows_state):
            chip = f"상황: {self.node.required_state}"
            painter.setFont(small)
            metrics = QFontMetrics(small)
            cw = min(metrics.horizontalAdvance(chip) + 12, w - left - 10)
            chip_rect = QRectF(left, y, cw, 15)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(style.with_alpha(style.ACCENT, 45)))
            painter.drawRoundedRect(chip_rect, 7, 7)
            painter.setPen(QPen(style.ACCENT))
            painter.drawText(
                chip_rect,
                Qt.AlignmentFlag.AlignCenter,
                _elide(painter, chip, cw - 8),
            )

        # 출구 라벨 (ok/fail 처럼 여러 개일 때만)
        if len(self.out_ports) > 1:
            tiny = QFont()
            tiny.setPointSize(7)
            painter.setFont(tiny)
            painter.setPen(QPen(style.TEXT_FAINT))
            for name, port in self.out_ports.items():
                py = port.pos().y()
                painter.drawText(
                    QRectF(w - 62, py - 7, 52, 14),
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                    _port_label(name),
                )

    def _summary_line(self) -> str:
        spec = self.type_spec
        if spec and not spec.allows_actions:
            return _node_param_summary(self.node, spec)
        count = len(self.node.actions)
        if count == 0:
            return "액션 없음"
        first = registry.action_summary(self.node.actions[0].type, self.node.actions[0].params)
        return first if count == 1 else f"{first}  (+{count - 1})"

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
        self._press_pos = (self.node.x, self.node.y)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._press_pos is None:
            return
        moved = (round(self.pos().x(), 2), round(self.pos().y(), 2)) != (
            round(self._press_pos[0], 2),
            round(self._press_pos[1], 2),
        )
        self._press_pos = None
        if moved:
            self._scene.commit_move()

    def mouseDoubleClickEvent(self, event) -> None:
        self._scene.node_double_clicked.emit(self.node.id)
        event.accept()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            pos = self._scene.snap(value)
            return pos
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.node.x = self.pos().x()
            self.node.y = self.pos().y()
            self.geometry_changed.emit()
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.setZValue(3 if value else 1)
        return super().itemChange(change, value)


# ---------------------------------------------------------------- 보조


def _elide(painter: QPainter, text: str, width: float) -> str:
    metrics = QFontMetrics(painter.font())
    return metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(max(10, width)))


_PORT_LABELS = {
    "ok": "성공",
    "fail": "실패",
    "true": "참",
    "false": "거짓",
    "default": "그 외",
    "in": "",
}


def _port_label(name: str) -> str:
    return _PORT_LABELS.get(name, name)


def _node_param_summary(node, spec) -> str:
    """액션을 담지 않는 노드(호출/상황이동/종료 등)의 한 줄 요약."""
    p = node.params or {}
    match node.type:
        case "subflow":
            return f"플로우 '{p.get('flow') or '(미지정)'}' 호출"
        case "state_gate":
            mode = {"navigate": "이동", "wait": "대기", "check": "확인"}.get(p.get("mode", ""), "")
            return f"'{p.get('target_state') or '(미지정)'}' 상황으로 {mode}"
        case "window":
            from itda.core.window_spec import summarize as window_summary

            return window_summary(p)
        case "end":
            return {"success": "성공으로 종료", "fail": "실패로 종료", "stop_all": "전체 중단"}.get(
                p.get("result", "success"), "종료"
            )
        case "note":
            return (p.get("text") or "메모").splitlines()[0]
        case "start":
            return "플로우 시작"
        case _:
            return spec.label if spec else node.type
