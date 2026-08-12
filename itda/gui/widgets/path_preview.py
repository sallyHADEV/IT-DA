"""마우스 궤적 미리보기.

스위치를 켜고 끌 때 "무엇이 달라지는지" 를 글이 아니라 그림으로 보여 준다.
:func:`itda.core.humanize.mouse_path` 를 그대로 호출하므로, 화면에 보이는 궤적이 실제로
실행될 궤적이다.
"""

from __future__ import annotations

import random

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from itda.core.humanize import HumanProfile, mouse_path
from itda.gui import style

MARGIN = 26


class PathPreview(QWidget):
    """현재 설정으로 생성한 궤적을 그린다. 몇 초마다 다시 뽑아 무작위성을 보여 준다."""

    def __init__(self, profile: HumanProfile, parent=None) -> None:
        super().__init__(parent)
        self.profile = profile
        self.setMinimumHeight(118)
        self._rng = random.Random(7)
        self._points: list[tuple[float, float, float]] = []

        self._timer = QTimer(self)
        self._timer.setInterval(2200)
        self._timer.timeout.connect(self.reroll)
        self._timer.start()
        self.regenerate()

    # ------------------------------------------------------------

    def set_profile(self, profile: HumanProfile) -> None:
        self.profile = profile
        self.regenerate()

    def reroll(self) -> None:
        self._rng = random.Random(self._rng.randrange(1 << 30))
        self.regenerate()

    def regenerate(self) -> None:
        width = max(120, self.width())
        height = max(80, self.height())
        start = (MARGIN, height - MARGIN)
        end = (width - MARGIN, MARGIN)
        rng = random.Random(self._rng.randrange(1 << 30))
        points = mouse_path(start, end, self.profile, duration_ms=600, rng=rng)
        self._points = [(p.x, p.y, p.delay_ms) for p in points]
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.regenerate()

    # ------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = QRectF(0, 0, self.width(), self.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(style.CANVAS_BG))
            painter.drawRoundedRect(rect, 10, 10)

            if not self._points:
                return

            start = QPointF(MARGIN, self.height() - MARGIN)
            end = QPointF(self.width() - MARGIN, MARGIN)

            # 비교용 직선 (기계적인 경로)
            dashed = QPen(style.TEXT_FAINT, 1, Qt.PenStyle.DashLine)
            dashed.setDashPattern([3, 4])
            painter.setPen(dashed)
            painter.drawLine(start, end)

            # 실제 궤적
            path = QPainterPath(QPointF(self._points[0][0], self._points[0][1]))
            for x, y, _delay in self._points[1:]:
                path.lineTo(QPointF(x, y))
            painter.setPen(QPen(style.ACCENT, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

            # 속도 점 — 간격이 넓을수록 빠르게 지나간 구간
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(style.with_alpha(style.EDGE_FIRED, 190)))
            for x, y, _delay in self._points[::2]:
                painter.drawEllipse(QPointF(x, y), 1.7, 1.7)

            painter.setBrush(QBrush(style.TEXT_DIM))
            painter.drawEllipse(start, 3.5, 3.5)
            painter.setBrush(QBrush(style.ACCENT))
            painter.drawEllipse(end, 4.5, 4.5)

            painter.setPen(QPen(style.TEXT_FAINT))
            painter.drawText(
                QRectF(8, self.height() - 20, self.width() - 16, 16),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                f"점 {len(self._points)}개 · 점선은 기계적인 직선",
            )
        finally:
            painter.end()
