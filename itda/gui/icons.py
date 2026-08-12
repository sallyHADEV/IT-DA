"""벡터 아이콘.

이미지 파일을 두지 않고 QPainter 로 그린다. 파일이 없으니 배포가 단순하고, 색을 바꿔 달라고
할 수 있어 테마와 어긋나지 않는다. 모양은 전부 단순한 선 하나 굵기의 플랫 아이콘이다.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from itda.gui import style

_CACHE: dict[tuple[str, str, int], QIcon] = {}


def icon(name: str, color: QColor | str | None = None, size: int = 32) -> QIcon:
    """이름으로 아이콘을 얻는다. 같은 (이름, 색, 크기)는 한 번만 그린다."""
    qcolor = QColor(color) if color is not None else QColor(style.TEXT)
    key = (name, qcolor.name(), size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pen = QPen(qcolor, max(1.4, size * 0.075))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        drawer = _DRAWERS.get(name, _draw_dot)
        drawer(painter, float(size), qcolor)
    finally:
        painter.end()

    result = QIcon(pixmap)
    _CACHE[key] = result
    return result


#: 액션 분류 → 아이콘 이름
CATEGORY_ICONS = {
    "인식": "search",
    "입력": "cursor",
    "흐름": "branch",
    "데이터": "data",
    "도구": "tool",
    "기타": "dot",
}

#: 액션 타입 중 분류 아이콘보다 구체적인 것이 나은 경우
ACTION_ICONS = {
    "image_search": "search",
    "wait_image": "hourglass",
    "ocr_read": "text",
    "pixel_check": "pixel",
    "click": "cursor",
    "move": "cursor",
    "drag": "drag",
    "scroll": "scroll",
    "key_press": "keyboard",
    "type_text": "text",
    "touch_point": "touch",
    "touch_multi": "touch",
    "touch_drag": "touch",
    "sleep": "hourglass",
    "if": "branch",
    "run_flow": "module",
    "goto_state": "flag",
    "wait_state": "flag",
    "stop": "stop",
    "set_var": "data",
    "calc": "data",
    "clipboard": "clipboard",
    "log": "log",
    "beep": "bell",
    "screenshot": "camera",
    "window": "window",
    "run_program": "play",
}

#: 노드 타입 아이콘
NODE_ICONS = {
    "start": "play",
    "action_group": "layers",
    "branch": "branch",
    "switch": "branch",
    "loop": "loop",
    "subflow": "module",
    "state_gate": "flag",
    "window": "window",
    "end": "stop",
    "note": "note",
}


#: 상황 판정 조건 아이콘
CONDITION_ICONS = {
    "object_visible": "search",
    "window_title": "window",
    "window_active": "window",
    "ocr_contains": "text",
    "pixel_color": "pixel",
    "expr": "data",
}


def condition_icon(type_id: str, color: QColor | str) -> QIcon:
    return icon(CONDITION_ICONS.get(type_id, "dot"), color, 24)


def action_icon(type_id: str, category: str, color: QColor | str) -> QIcon:
    name = ACTION_ICONS.get(type_id) or CATEGORY_ICONS.get(category, "dot")
    return icon(name, color, 24)


def node_icon(type_id: str, color: QColor | str) -> QIcon:
    return icon(NODE_ICONS.get(type_id, "layers"), color, 24)


# ---------------------------------------------------------------- 그리기


def _fill(painter: QPainter, color: QColor) -> None:
    painter.setBrush(QBrush(color))


def _draw_dot(p: QPainter, s: float, c: QColor) -> None:
    _fill(p, c)
    p.drawEllipse(QPointF(s / 2, s / 2), s * 0.14, s * 0.14)


def _draw_play(p: QPainter, s: float, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(s * 0.32, s * 0.22)
    path.lineTo(s * 0.78, s * 0.5)
    path.lineTo(s * 0.32, s * 0.78)
    path.closeSubpath()
    _fill(p, c)
    p.drawPath(path)


def _draw_pause(p: QPainter, s: float, c: QColor) -> None:
    _fill(p, c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(s * 0.30, s * 0.22, s * 0.14, s * 0.56), 2, 2)
    p.drawRoundedRect(QRectF(s * 0.56, s * 0.22, s * 0.14, s * 0.56), 2, 2)


def _draw_stop(p: QPainter, s: float, c: QColor) -> None:
    _fill(p, c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(s * 0.28, s * 0.28, s * 0.44, s * 0.44), 3, 3)


def _draw_check(p: QPainter, s: float, c: QColor) -> None:
    p.drawRoundedRect(QRectF(s * 0.2, s * 0.18, s * 0.6, s * 0.64), 4, 4)
    path = QPainterPath()
    path.moveTo(s * 0.33, s * 0.5)
    path.lineTo(s * 0.45, s * 0.63)
    path.lineTo(s * 0.68, s * 0.36)
    p.drawPath(path)


def _draw_search(p: QPainter, s: float, c: QColor) -> None:
    p.drawEllipse(QPointF(s * 0.44, s * 0.44), s * 0.22, s * 0.22)
    p.drawLine(QPointF(s * 0.60, s * 0.60), QPointF(s * 0.78, s * 0.78))


def _draw_hourglass(p: QPainter, s: float, c: QColor) -> None:
    p.drawLine(QPointF(s * 0.3, s * 0.22), QPointF(s * 0.7, s * 0.22))
    p.drawLine(QPointF(s * 0.3, s * 0.78), QPointF(s * 0.7, s * 0.78))
    path = QPainterPath()
    path.moveTo(s * 0.32, s * 0.22)
    path.lineTo(s * 0.68, s * 0.78)
    path.moveTo(s * 0.68, s * 0.22)
    path.lineTo(s * 0.32, s * 0.78)
    p.drawPath(path)


def _draw_cursor(p: QPainter, s: float, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(s * 0.3, s * 0.2)
    path.lineTo(s * 0.3, s * 0.72)
    path.lineTo(s * 0.43, s * 0.60)
    path.lineTo(s * 0.52, s * 0.80)
    path.lineTo(s * 0.62, s * 0.75)
    path.lineTo(s * 0.53, s * 0.56)
    path.lineTo(s * 0.70, s * 0.53)
    path.closeSubpath()
    _fill(p, c)
    p.drawPath(path)


def _draw_drag(p: QPainter, s: float, c: QColor) -> None:
    p.drawEllipse(QPointF(s * 0.27, s * 0.68), s * 0.09, s * 0.09)
    path = QPainterPath()
    path.moveTo(s * 0.33, s * 0.62)
    path.cubicTo(s * 0.45, s * 0.35, s * 0.6, s * 0.3, s * 0.72, s * 0.3)
    p.drawPath(path)
    arrow = QPainterPath()
    arrow.moveTo(s * 0.62, s * 0.22)
    arrow.lineTo(s * 0.76, s * 0.3)
    arrow.lineTo(s * 0.62, s * 0.38)
    _fill(p, c)
    p.drawPath(arrow)


def _draw_scroll(p: QPainter, s: float, c: QColor) -> None:
    p.drawRoundedRect(QRectF(s * 0.36, s * 0.18, s * 0.28, s * 0.64), s * 0.14, s * 0.14)
    p.drawLine(QPointF(s * 0.5, s * 0.3), QPointF(s * 0.5, s * 0.44))


def _draw_keyboard(p: QPainter, s: float, c: QColor) -> None:
    p.drawRoundedRect(QRectF(s * 0.14, s * 0.3, s * 0.72, s * 0.4), 3, 3)
    y = s * 0.44
    for x in (0.26, 0.38, 0.5, 0.62, 0.74):
        p.drawPoint(QPointF(s * x, y))
    p.drawLine(QPointF(s * 0.32, s * 0.58), QPointF(s * 0.68, s * 0.58))


def _draw_text(p: QPainter, s: float, c: QColor) -> None:
    p.drawLine(QPointF(s * 0.24, s * 0.28), QPointF(s * 0.76, s * 0.28))
    p.drawLine(QPointF(s * 0.5, s * 0.28), QPointF(s * 0.5, s * 0.74))
    p.drawLine(QPointF(s * 0.36, s * 0.74), QPointF(s * 0.64, s * 0.74))


def _draw_pixel(p: QPainter, s: float, c: QColor) -> None:
    p.drawRect(QRectF(s * 0.2, s * 0.2, s * 0.6, s * 0.6))
    _fill(p, c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(s * 0.2, s * 0.2, s * 0.3, s * 0.3))


def _draw_touch(p: QPainter, s: float, c: QColor) -> None:
    p.drawEllipse(QPointF(s * 0.5, s * 0.52), s * 0.13, s * 0.13)
    p.drawArc(QRectF(s * 0.24, s * 0.26, s * 0.52, s * 0.52), 30 * 16, 120 * 16)
    p.drawArc(QRectF(s * 0.14, s * 0.16, s * 0.72, s * 0.72), 30 * 16, 120 * 16)


def _draw_branch(p: QPainter, s: float, c: QColor) -> None:
    p.drawLine(QPointF(s * 0.22, s * 0.5), QPointF(s * 0.46, s * 0.5))
    path = QPainterPath()
    path.moveTo(s * 0.46, s * 0.5)
    path.cubicTo(s * 0.62, s * 0.5, s * 0.62, s * 0.26, s * 0.78, s * 0.26)
    path.moveTo(s * 0.46, s * 0.5)
    path.cubicTo(s * 0.62, s * 0.5, s * 0.62, s * 0.74, s * 0.78, s * 0.74)
    p.drawPath(path)
    _fill(p, c)
    p.drawEllipse(QPointF(s * 0.22, s * 0.5), s * 0.06, s * 0.06)


def _draw_loop(p: QPainter, s: float, c: QColor) -> None:
    p.drawArc(QRectF(s * 0.22, s * 0.22, s * 0.56, s * 0.56), 40 * 16, 280 * 16)
    arrow = QPainterPath()
    arrow.moveTo(s * 0.62, s * 0.18)
    arrow.lineTo(s * 0.80, s * 0.30)
    arrow.lineTo(s * 0.60, s * 0.38)
    _fill(p, c)
    p.drawPath(arrow)


def _draw_module(p: QPainter, s: float, c: QColor) -> None:
    p.drawRect(QRectF(s * 0.18, s * 0.28, s * 0.4, s * 0.44))
    p.drawRect(QRectF(s * 0.42, s * 0.18, s * 0.4, s * 0.44))


def _draw_layers(p: QPainter, s: float, c: QColor) -> None:
    for i, y in enumerate((0.28, 0.46, 0.64)):
        p.drawLine(QPointF(s * 0.22, s * y), QPointF(s * 0.78, s * y))


def _draw_flag(p: QPainter, s: float, c: QColor) -> None:
    p.drawLine(QPointF(s * 0.3, s * 0.18), QPointF(s * 0.3, s * 0.82))
    path = QPainterPath()
    path.moveTo(s * 0.3, s * 0.22)
    path.lineTo(s * 0.76, s * 0.34)
    path.lineTo(s * 0.3, s * 0.48)
    path.closeSubpath()
    _fill(p, c)
    p.drawPath(path)


def _draw_note(p: QPainter, s: float, c: QColor) -> None:
    p.drawRoundedRect(QRectF(s * 0.22, s * 0.2, s * 0.56, s * 0.6), 3, 3)
    for y in (0.36, 0.5, 0.64):
        p.drawLine(QPointF(s * 0.33, s * y), QPointF(s * 0.67, s * y))


def _draw_data(p: QPainter, s: float, c: QColor) -> None:
    p.drawEllipse(QRectF(s * 0.22, s * 0.2, s * 0.56, s * 0.2))
    p.drawLine(QPointF(s * 0.22, s * 0.3), QPointF(s * 0.22, s * 0.7))
    p.drawLine(QPointF(s * 0.78, s * 0.3), QPointF(s * 0.78, s * 0.7))
    p.drawArc(QRectF(s * 0.22, s * 0.6, s * 0.56, s * 0.2), 180 * 16, 180 * 16)


def _draw_clipboard(p: QPainter, s: float, c: QColor) -> None:
    p.drawRoundedRect(QRectF(s * 0.26, s * 0.22, s * 0.48, s * 0.6), 3, 3)
    _fill(p, c)
    p.drawRoundedRect(QRectF(s * 0.38, s * 0.14, s * 0.24, s * 0.14), 2, 2)


def _draw_log(p: QPainter, s: float, c: QColor) -> None:
    for i, y in enumerate((0.3, 0.45, 0.6, 0.75)):
        _fill(p, c)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(s * 0.26, s * y), s * 0.035, s * 0.035)
    pen = QPen(c, max(1.4, s * 0.075))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    for y in (0.3, 0.45, 0.6, 0.75):
        p.drawLine(QPointF(s * 0.38, s * y), QPointF(s * 0.78, s * y))


def _draw_tool(p: QPainter, s: float, c: QColor) -> None:
    p.drawEllipse(QPointF(s * 0.36, s * 0.36), s * 0.15, s * 0.15)
    p.drawLine(QPointF(s * 0.47, s * 0.47), QPointF(s * 0.76, s * 0.76))


def _draw_bell(p: QPainter, s: float, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(s * 0.26, s * 0.64)
    path.lineTo(s * 0.74, s * 0.64)
    path.lineTo(s * 0.66, s * 0.52)
    path.lineTo(s * 0.66, s * 0.4)
    path.arcTo(QRectF(s * 0.34, s * 0.22, s * 0.32, s * 0.32), 0, 180)
    path.lineTo(s * 0.34, s * 0.52)
    path.closeSubpath()
    p.drawPath(path)
    p.drawArc(QRectF(s * 0.42, s * 0.66, s * 0.16, s * 0.14), 180 * 16, 180 * 16)


def _draw_camera(p: QPainter, s: float, c: QColor) -> None:
    p.drawRoundedRect(QRectF(s * 0.16, s * 0.3, s * 0.68, s * 0.44), 4, 4)
    p.drawEllipse(QPointF(s * 0.5, s * 0.52), s * 0.13, s * 0.13)
    p.drawLine(QPointF(s * 0.36, s * 0.3), QPointF(s * 0.44, s * 0.22))
    p.drawLine(QPointF(s * 0.64, s * 0.3), QPointF(s * 0.56, s * 0.22))


def _draw_window(p: QPainter, s: float, c: QColor) -> None:
    p.drawRoundedRect(QRectF(s * 0.16, s * 0.22, s * 0.68, s * 0.56), 3, 3)
    p.drawLine(QPointF(s * 0.16, s * 0.38), QPointF(s * 0.84, s * 0.38))


def _draw_coord(p: QPainter, s: float, c: QColor) -> None:
    p.drawLine(QPointF(s * 0.5, s * 0.14), QPointF(s * 0.5, s * 0.36))
    p.drawLine(QPointF(s * 0.5, s * 0.64), QPointF(s * 0.5, s * 0.86))
    p.drawLine(QPointF(s * 0.14, s * 0.5), QPointF(s * 0.36, s * 0.5))
    p.drawLine(QPointF(s * 0.64, s * 0.5), QPointF(s * 0.86, s * 0.5))
    p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.12, s * 0.12)


def _draw_snip(p: QPainter, s: float, c: QColor) -> None:
    pen = QPen(c, max(1.4, s * 0.075))
    pen.setStyle(Qt.PenStyle.DashLine)
    pen.setDashPattern([2.4, 2.0])
    p.setPen(pen)
    p.drawRect(QRectF(s * 0.2, s * 0.24, s * 0.6, s * 0.52))
    solid = QPen(c, max(1.6, s * 0.09))
    solid.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(solid)
    for x, y in ((0.2, 0.24), (0.8, 0.24), (0.2, 0.76), (0.8, 0.76)):
        p.drawPoint(QPointF(s * x, s * y))


def _draw_objectify(p: QPainter, s: float, c: QColor) -> None:
    p.drawRect(QRectF(s * 0.16, s * 0.2, s * 0.3, s * 0.24))
    p.drawRect(QRectF(s * 0.54, s * 0.2, s * 0.3, s * 0.24))
    p.drawRect(QRectF(s * 0.16, s * 0.56, s * 0.3, s * 0.24))
    _fill(p, c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(s * 0.54, s * 0.56, s * 0.3, s * 0.24))


def _draw_states(p: QPainter, s: float, c: QColor) -> None:
    p.drawEllipse(QPointF(s * 0.26, s * 0.3), s * 0.12, s * 0.12)
    p.drawEllipse(QPointF(s * 0.74, s * 0.7), s * 0.12, s * 0.12)
    p.drawLine(QPointF(s * 0.36, s * 0.38), QPointF(s * 0.64, s * 0.62))


def _draw_timing(p: QPainter, s: float, c: QColor) -> None:
    p.drawEllipse(QPointF(s * 0.5, s * 0.52), s * 0.3, s * 0.3)
    p.drawLine(QPointF(s * 0.5, s * 0.52), QPointF(s * 0.5, s * 0.34))
    p.drawLine(QPointF(s * 0.5, s * 0.52), QPointF(s * 0.64, s * 0.6))


def _draw_new(p: QPainter, s: float, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(s * 0.26, s * 0.16)
    path.lineTo(s * 0.58, s * 0.16)
    path.lineTo(s * 0.74, s * 0.34)
    path.lineTo(s * 0.74, s * 0.84)
    path.lineTo(s * 0.26, s * 0.84)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(s * 0.58, s * 0.16), QPointF(s * 0.58, s * 0.34))
    p.drawLine(QPointF(s * 0.58, s * 0.34), QPointF(s * 0.74, s * 0.34))


def _draw_open(p: QPainter, s: float, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(s * 0.14, s * 0.74)
    path.lineTo(s * 0.14, s * 0.26)
    path.lineTo(s * 0.42, s * 0.26)
    path.lineTo(s * 0.5, s * 0.38)
    path.lineTo(s * 0.86, s * 0.38)
    path.lineTo(s * 0.86, s * 0.74)
    path.closeSubpath()
    p.drawPath(path)


def _draw_save(p: QPainter, s: float, c: QColor) -> None:
    p.drawRoundedRect(QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64), 3, 3)
    p.drawRect(QRectF(s * 0.34, s * 0.18, s * 0.32, s * 0.22))
    p.drawRect(QRectF(s * 0.3, s * 0.54, s * 0.4, s * 0.28))


def _draw_undo(p: QPainter, s: float, c: QColor) -> None:
    p.drawArc(QRectF(s * 0.2, s * 0.28, s * 0.6, s * 0.5), 20 * 16, 250 * 16)
    arrow = QPainterPath()
    arrow.moveTo(s * 0.2, s * 0.28)
    arrow.lineTo(s * 0.42, s * 0.32)
    arrow.lineTo(s * 0.26, s * 0.5)
    _fill(p, c)
    p.drawPath(arrow)


def _draw_redo(p: QPainter, s: float, c: QColor) -> None:
    p.drawArc(QRectF(s * 0.2, s * 0.28, s * 0.6, s * 0.5), -90 * 16, 250 * 16)
    arrow = QPainterPath()
    arrow.moveTo(s * 0.8, s * 0.28)
    arrow.lineTo(s * 0.58, s * 0.32)
    arrow.lineTo(s * 0.74, s * 0.5)
    _fill(p, c)
    p.drawPath(arrow)


def _draw_layout(p: QPainter, s: float, c: QColor) -> None:
    p.drawRoundedRect(QRectF(s * 0.12, s * 0.36, s * 0.24, s * 0.24), 2, 2)
    p.drawRoundedRect(QRectF(s * 0.62, s * 0.16, s * 0.26, s * 0.22), 2, 2)
    p.drawRoundedRect(QRectF(s * 0.62, s * 0.6, s * 0.26, s * 0.22), 2, 2)
    p.drawLine(QPointF(s * 0.36, s * 0.48), QPointF(s * 0.62, s * 0.27))
    p.drawLine(QPointF(s * 0.36, s * 0.48), QPointF(s * 0.62, s * 0.7))


def _draw_fit(p: QPainter, s: float, c: QColor) -> None:
    for dx, dy, ex, ey in (
        (0.16, 0.16, 0.36, 0.16),
        (0.16, 0.16, 0.16, 0.36),
        (0.84, 0.84, 0.64, 0.84),
        (0.84, 0.84, 0.84, 0.64),
        (0.84, 0.16, 0.64, 0.16),
        (0.84, 0.16, 0.84, 0.36),
        (0.16, 0.84, 0.36, 0.84),
        (0.16, 0.84, 0.16, 0.64),
    ):
        p.drawLine(QPointF(s * dx, s * dy), QPointF(s * ex, s * ey))


def _draw_plus(p: QPainter, s: float, c: QColor) -> None:
    p.drawLine(QPointF(s * 0.5, s * 0.24), QPointF(s * 0.5, s * 0.76))
    p.drawLine(QPointF(s * 0.24, s * 0.5), QPointF(s * 0.76, s * 0.5))


def _draw_minus(p: QPainter, s: float, c: QColor) -> None:
    p.drawLine(QPointF(s * 0.24, s * 0.5), QPointF(s * 0.76, s * 0.5))


def _draw_up(p: QPainter, s: float, c: QColor) -> None:
    p.drawLine(QPointF(s * 0.5, s * 0.76), QPointF(s * 0.5, s * 0.28))
    p.drawLine(QPointF(s * 0.32, s * 0.44), QPointF(s * 0.5, s * 0.26))
    p.drawLine(QPointF(s * 0.68, s * 0.44), QPointF(s * 0.5, s * 0.26))


def _draw_down(p: QPainter, s: float, c: QColor) -> None:
    p.drawLine(QPointF(s * 0.5, s * 0.24), QPointF(s * 0.5, s * 0.72))
    p.drawLine(QPointF(s * 0.32, s * 0.56), QPointF(s * 0.5, s * 0.74))
    p.drawLine(QPointF(s * 0.68, s * 0.56), QPointF(s * 0.5, s * 0.74))


def _draw_copy(p: QPainter, s: float, c: QColor) -> None:
    p.drawRoundedRect(QRectF(s * 0.18, s * 0.18, s * 0.44, s * 0.44), 3, 3)
    p.drawRoundedRect(QRectF(s * 0.38, s * 0.38, s * 0.44, s * 0.44), 3, 3)


def _draw_edit(p: QPainter, s: float, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(s * 0.24, s * 0.76)
    path.lineTo(s * 0.3, s * 0.6)
    path.lineTo(s * 0.66, s * 0.24)
    path.lineTo(s * 0.78, s * 0.36)
    path.lineTo(s * 0.42, s * 0.72)
    path.closeSubpath()
    p.drawPath(path)


def _draw_ellipsis(p: QPainter, s: float, c: QColor) -> None:
    _fill(p, c)
    p.setPen(Qt.PenStyle.NoPen)
    for x in (0.28, 0.5, 0.72):
        p.drawEllipse(QPointF(s * x, s * 0.5), s * 0.06, s * 0.06)


def _draw_region(p: QPainter, s: float, c: QColor) -> None:
    p.drawRect(QRectF(s * 0.22, s * 0.26, s * 0.56, s * 0.48))
    _fill(p, c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(QRectF(s * 0.34, s * 0.38, s * 0.32, s * 0.24))


def _draw_curve(p: QPainter, s: float, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(s * 0.16, s * 0.76)
    path.cubicTo(s * 0.36, s * 0.24, s * 0.64, s * 0.9, s * 0.84, s * 0.3)
    p.drawPath(path)


def _draw_speed(p: QPainter, s: float, c: QColor) -> None:
    p.drawArc(QRectF(s * 0.16, s * 0.26, s * 0.68, s * 0.68), 20 * 16, 140 * 16)
    p.drawLine(QPointF(s * 0.5, s * 0.6), QPointF(s * 0.68, s * 0.4))
    _fill(p, c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(s * 0.5, s * 0.6), s * 0.05, s * 0.05)


def _draw_overshoot(p: QPainter, s: float, c: QColor) -> None:
    path = QPainterPath()
    path.moveTo(s * 0.14, s * 0.62)
    path.cubicTo(s * 0.44, s * 0.62, s * 0.72, s * 0.2, s * 0.84, s * 0.42)
    path.cubicTo(s * 0.9, s * 0.56, s * 0.74, s * 0.6, s * 0.62, s * 0.5)
    p.drawPath(path)
    _fill(p, c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(s * 0.6, s * 0.5), s * 0.055, s * 0.055)


def _draw_drift(p: QPainter, s: float, c: QColor) -> None:
    pen = QPen(c, max(1.4, s * 0.075))
    pen.setStyle(Qt.PenStyle.DotLine)
    p.setPen(pen)
    p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.26, s * 0.26)
    _fill(p, c)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.07, s * 0.07)


def _draw_flow(p: QPainter, s: float, c: QColor) -> None:
    p.drawRoundedRect(QRectF(s * 0.14, s * 0.18, s * 0.3, s * 0.22), 2, 2)
    p.drawRoundedRect(QRectF(s * 0.56, s * 0.6, s * 0.3, s * 0.22), 2, 2)
    p.drawLine(QPointF(s * 0.29, s * 0.4), QPointF(s * 0.29, s * 0.71))
    p.drawLine(QPointF(s * 0.29, s * 0.71), QPointF(s * 0.56, s * 0.71))


def _draw_info(p: QPainter, s: float, c: QColor) -> None:
    p.drawEllipse(QRectF(s * 0.16, s * 0.16, s * 0.68, s * 0.68))
    p.drawEllipse(QRectF(s * 0.47, s * 0.31, s * 0.06, s * 0.06))
    p.drawLine(QPointF(s * 0.5, s * 0.45), QPointF(s * 0.5, s * 0.7))


_DRAWERS = {
    "dot": _draw_dot,
    "play": _draw_play,
    "pause": _draw_pause,
    "stop": _draw_stop,
    "check": _draw_check,
    "search": _draw_search,
    "hourglass": _draw_hourglass,
    "cursor": _draw_cursor,
    "drag": _draw_drag,
    "scroll": _draw_scroll,
    "keyboard": _draw_keyboard,
    "text": _draw_text,
    "pixel": _draw_pixel,
    "touch": _draw_touch,
    "branch": _draw_branch,
    "loop": _draw_loop,
    "module": _draw_module,
    "layers": _draw_layers,
    "flag": _draw_flag,
    "note": _draw_note,
    "data": _draw_data,
    "clipboard": _draw_clipboard,
    "log": _draw_log,
    "tool": _draw_tool,
    "bell": _draw_bell,
    "camera": _draw_camera,
    "window": _draw_window,
    "coord": _draw_coord,
    "snip": _draw_snip,
    "objectify": _draw_objectify,
    "states": _draw_states,
    "timing": _draw_timing,
    "new": _draw_new,
    "open": _draw_open,
    "save": _draw_save,
    "undo": _draw_undo,
    "redo": _draw_redo,
    "layout": _draw_layout,
    "fit": _draw_fit,
    "flow": _draw_flow,
    "info": _draw_info,
    "plus": _draw_plus,
    "minus": _draw_minus,
    "up": _draw_up,
    "down": _draw_down,
    "copy": _draw_copy,
    "edit": _draw_edit,
    "ellipsis": _draw_ellipsis,
    "region": _draw_region,
    "curve": _draw_curve,
    "speed": _draw_speed,
    "overshoot": _draw_overshoot,
    "drift": _draw_drift,
}
