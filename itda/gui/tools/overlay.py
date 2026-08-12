"""화면 위 오버레이의 공통 부분.

좌표 도구와 스크린샷 도구는 둘 다 "화면을 얼어붙게 하고 그 위에 그린다". 화면을 먼저 캡처해
배경으로 깔면 커서를 움직여도 화면이 흔들리지 않고, 확대경이 정확한 픽셀을 읽을 수 있다.
"""

from __future__ import annotations

from PyQt6.QtCore import QEventLoop, QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from itda.gui import style
from itda.vision import capture

MAGNIFIER = 132  # 확대경 한 변(px)
ZOOM = 8


class FrozenOverlay(QWidget):
    """전체 화면을 덮는 반투명 오버레이."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # 앱 모달이어야 한다. 모달 대화상자(노드 편집 창 등) 위에서 도구를 열면, 이게 없으면
        # 오버레이가 이벤트를 못 받아 **마우스를 따라오지 않고**, 클릭은 아래 대화상자로 가서
        # 엉뚱한 버튼을 누른다(창이 닫히는 것처럼 보였다).
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

        self.geometry_rect: QRect = capture.virtual_geometry()
        self.shot: QPixmap = capture.grab_all()
        self.image: QImage = self.shot.toImage()
        self.cursor_pos = QPoint(0, 0)
        self.result = None
        self._loop: QEventLoop | None = None

        self.setGeometry(self.geometry_rect)

    # ------------------------------------------------------------ 실행

    def run(self):
        """오버레이를 띄우고 결과가 나올 때까지 기다린다."""
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.grabKeyboard()
        # 모달 대화상자 위에서 열렸을 때 마우스 이벤트를 확실히 받기 위해 붙잡는다.
        self.grabMouse()
        self._loop = QEventLoop()
        self._loop.exec()
        return self.result

    def finish(self, result=None) -> None:
        self.result = result
        self._release()
        self.close()
        if self._loop is not None:
            self._loop.quit()
            self._loop = None

    def _release(self) -> None:
        self.releaseMouse()
        self.releaseKeyboard()

    def closeEvent(self, event) -> None:
        """어떤 경로로 닫히든(Alt+F4 등) 잡아 둔 입력을 놓고 대기를 끝낸다.

        놓지 않으면 마우스를 붙잡은 채 이벤트 루프가 남아 앱 전체가 멈춘다.
        """
        self._release()
        if self._loop is not None:
            self._loop.quit()
            self._loop = None
        super().closeEvent(event)

    # ------------------------------------------------------------ 좌표

    def screen_point(self, local: QPoint) -> tuple[int, int]:
        """오버레이 좌표 → 가상 데스크톱 좌표."""
        return (local.x() + self.geometry_rect.x(), local.y() + self.geometry_rect.y())

    def color_at(self, local: QPoint) -> QColor:
        if not self.image.rect().contains(local):
            return QColor(0, 0, 0)
        return QColor(self.image.pixel(local))

    # ------------------------------------------------------------ 그리기

    def draw_background(self, painter: QPainter, dim: int = 110) -> None:
        painter.drawPixmap(0, 0, self.shot)
        painter.fillRect(self.rect(), QColor(20, 24, 32, dim))

    def draw_crosshair(self, painter: QPainter) -> None:
        pen = QPen(style.ACCENT, 1)
        painter.setPen(pen)
        painter.drawLine(0, self.cursor_pos.y(), self.width(), self.cursor_pos.y())
        painter.drawLine(self.cursor_pos.x(), 0, self.cursor_pos.x(), self.height())

    def draw_magnifier(self, painter: QPainter, extra_lines: list[str] | None = None) -> None:
        """커서 옆에 확대경과 좌표·색상 정보를 그린다."""
        pos = self.cursor_pos
        span = MAGNIFIER // ZOOM
        source = QRect(pos.x() - span // 2, pos.y() - span // 2, span, span)

        box_x = pos.x() + 22
        box_y = pos.y() + 22
        if box_x + MAGNIFIER + 8 > self.width():
            box_x = pos.x() - MAGNIFIER - 22
        if box_y + MAGNIFIER + 56 > self.height():
            box_y = pos.y() - MAGNIFIER - 56
        target = QRect(box_x, box_y, MAGNIFIER, MAGNIFIER)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style.SURFACE))
        painter.drawRoundedRect(target.adjusted(-4, -4, 4, 52), 8, 8)

        painter.drawPixmap(target, self.shot, source)

        # 중앙 픽셀 표시
        painter.setPen(QPen(style.ACCENT, 1))
        center = target.center()
        painter.drawRect(QRect(center.x() - ZOOM // 2, center.y() - ZOOM // 2, ZOOM, ZOOM))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(target)

        color = self.color_at(pos)
        sx, sy = self.screen_point(pos)
        lines = [f"X {sx}   Y {sy}", f"{color.name().upper()}  ({color.red()},{color.green()},{color.blue()})"]
        if extra_lines:
            lines += extra_lines

        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QPen(style.TEXT))
        for i, line in enumerate(lines):
            painter.drawText(target.x(), target.bottom() + 16 + i * 15, line)

        swatch = QRect(target.right() - 16, target.bottom() + 6, 12, 12)
        painter.fillRect(swatch, color)

    def draw_hint(self, painter: QPainter, text: str) -> None:
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 26
        box = QRect((self.width() - width) // 2, 24, width, 34)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style.SURFACE))
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(QPen(style.TEXT))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # ------------------------------------------------------------ 이벤트

    def mouseMoveEvent(self, event) -> None:
        self.cursor_pos = event.position().toPoint()
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.finish(None)
            return
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        moves = {
            Qt.Key.Key_Left: (-step, 0),
            Qt.Key.Key_Right: (step, 0),
            Qt.Key.Key_Up: (0, -step),
            Qt.Key.Key_Down: (0, step),
        }
        if event.key() in moves:
            dx, dy = moves[event.key()]
            self.cursor_pos += QPoint(dx, dy)
            QGuiApplication.setOverrideCursor(Qt.CursorShape.CrossCursor)
            QGuiApplication.restoreOverrideCursor()
            self.update()
            return
        super().keyPressEvent(event)
