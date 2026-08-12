"""좌표 도구.

화면을 얼린 뒤 확대경으로 정확한 픽셀을 찍는다. 방향키로 1px 씩 미세 조정할 수 있고,
Enter 또는 클릭으로 확정, ESC 로 취소한다.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter

from itda.gui.tools.overlay import FrozenOverlay

HINT = "클릭 또는 Enter 로 좌표 확정 · 방향키 미세조정 · ESC 취소"


class CoordPicker(FrozenOverlay):
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self.draw_background(painter, dim=70)
            self.draw_crosshair(painter)
            self.draw_magnifier(painter)
            self.draw_hint(painter, HINT)
        finally:
            painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.finish(self.screen_point(event.position().toPoint()))
        else:
            self.finish(None)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.finish(self.screen_point(self.cursor_pos))
            return
        super().keyPressEvent(event)


def pick_point() -> tuple[int, int] | None:
    """좌표 도구를 띄우고 찍은 좌표를 돌려준다. 취소하면 None."""
    return CoordPicker().run()
