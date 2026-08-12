"""스크린샷 도구.

드래그해서 영역을 지정한다. 지정한 영역의 좌표와 잘라낸 이미지를 함께 돌려주므로,
객체 저장(이미지)과 검색 범위 지정(좌표) 양쪽에 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap

from itda.gui import style
from itda.gui.tools.overlay import FrozenOverlay

HINT = "끌어서 영역 지정 · Enter 로 전체 화면 · ESC 취소"


@dataclass
class Snip:
    """잘라낸 결과."""

    rect: tuple[int, int, int, int]  # 가상 데스크톱 좌표 (x, y, w, h)
    pixmap: QPixmap


class SnipTool(FrozenOverlay):
    def __init__(self) -> None:
        super().__init__()
        self.origin: QPoint | None = None
        self.current: QPoint | None = None

    # ------------------------------------------------------------ 그리기

    def selection(self) -> QRect:
        if self.origin is None or self.current is None:
            return QRect()
        return QRect(self.origin, self.current).normalized()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self.draw_background(painter, dim=120)

            rect = self.selection()
            if rect.isValid() and rect.width() > 0:
                painter.drawPixmap(rect, self.shot, rect)  # 선택 영역만 원본 밝기로
                painter.setPen(QPen(style.ACCENT, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)

                label = f"{rect.width()} × {rect.height()}"
                painter.setPen(QPen(style.TEXT))
                painter.setBrush(QColor(style.SURFACE))
                box = QRect(rect.left(), max(0, rect.top() - 26), 96, 22)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(box, 6, 6)
                painter.setPen(QPen(style.TEXT))
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)

            # 확대경은 **끄는 동안에도** 띄운다. 끝나는 모서리를 픽셀 단위로 맞춰야 하는데
            # 드래그가 시작되면 사라져 버려서, 정작 정확도가 필요한 순간에 볼 수 없었다.
            self.draw_crosshair(painter)
            dragging = rect.isValid() and rect.width() > 0
            self.draw_magnifier(
                painter,
                extra_lines=[f"크기 {rect.width()} × {rect.height()}"] if dragging else None,
            )
            self.draw_hint(painter, HINT)
        finally:
            painter.end()

    # ------------------------------------------------------------ 이벤트

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            self.finish(None)
            return
        self.origin = event.position().toPoint()
        self.current = self.origin
        self.update()

    def mouseMoveEvent(self, event) -> None:
        self.cursor_pos = event.position().toPoint()
        if self.origin is not None:
            self.current = self.cursor_pos
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self.origin is None:
            return
        self.current = event.position().toPoint()
        rect = self.selection()
        if rect.width() < 3 or rect.height() < 3:
            # 잘못 클릭한 것으로 보고 다시 지정하게 둔다
            self.origin = self.current = None
            self.update()
            return
        self.finish(self._make_snip(rect))

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish(self._make_snip(self.rect()))
            return
        super().keyPressEvent(event)

    def _make_snip(self, rect: QRect) -> Snip:
        offset = self.geometry_rect.topLeft()
        return Snip(
            rect=(
                rect.x() + offset.x(),
                rect.y() + offset.y(),
                rect.width(),
                rect.height(),
            ),
            pixmap=self.shot.copy(rect),
        )


def snip() -> Snip | None:
    """영역을 지정해 잘라낸다. 취소하면 None."""
    return SnipTool().run()


def pick_rect() -> tuple[int, int, int, int] | None:
    """좌표만 필요할 때 (검색 범위 지정 등)."""
    result = snip()
    return result.rect if result else None
