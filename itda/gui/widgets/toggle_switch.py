"""스위치형 토글과 설정 행.

체크박스보다 켜짐/꺼짐이 한눈에 들어온다. 레퍼런스 UI 킷의 토글과 같은 모양(알약 + 손잡이,
켜지면 코럴)이고, 손잡이는 애니메이션으로 미끄러진다.

    [아이콘]  제목                                   ( ●—— )
              한 줄 설명
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, pyqtProperty
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from itda.gui import icons, style

TRACK_W = 42
TRACK_H = 22
KNOB_R = 8.5


class ToggleSwitch(QAbstractButton):
    """켜짐/꺼짐 스위치."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(TRACK_W, TRACK_H)
        self._offset = 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate)

    # 애니메이션용 속성 (0=꺼짐, 1=켜짐)
    @pyqtProperty(float)
    def offset(self) -> float:  # type: ignore[override]
        return self._offset

    @offset.setter
    def offset(self, value: float) -> None:  # type: ignore[override]
        self._offset = float(value)
        self.update()

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt 이름
        super().setChecked(checked)
        self._offset = 1.0 if checked else 0.0
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(TRACK_W, TRACK_H)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            enabled = self.isEnabled()
            track_on = style.ACCENT if enabled else style.SURFACE_HI
            track_off = style.SURFACE_ALT if enabled else style.SURFACE
            track = _mix(track_off, track_on, self._offset)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(track))
            painter.drawRoundedRect(QRectF(0, 0, TRACK_W, TRACK_H), TRACK_H / 2, TRACK_H / 2)

            margin = (TRACK_H - KNOB_R * 2) / 2
            x = margin + KNOB_R + self._offset * (TRACK_W - 2 * (margin + KNOB_R))
            knob = QColor("#1d222d") if self._offset > 0.5 else style.TEXT_DIM
            painter.setBrush(QBrush(knob if enabled else style.TEXT_FAINT))
            painter.drawEllipse(QRectF(x - KNOB_R, TRACK_H / 2 - KNOB_R, KNOB_R * 2, KNOB_R * 2))

            if self.hasFocus():
                painter.setPen(QPen(style.ACCENT, 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(
                    QRectF(0.5, 0.5, TRACK_W - 1, TRACK_H - 1), TRACK_H / 2, TRACK_H / 2
                )
        finally:
            painter.end()


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


class SwitchRow(QWidget):
    """아이콘 + 제목 + 설명 + 스위치 한 줄."""

    def __init__(
        self,
        icon_name: str,
        title: str,
        description: str = "",
        checked: bool = False,
        color=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.icon_name = icon_name
        self._color = QColor(color) if color is not None else QColor(style.ACCENT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(10)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(1)
        self.title_label = QLabel(title)
        title_font = QFont()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        text_box.addWidget(self.title_label)
        if description:
            self.desc_label = QLabel(description)
            self.desc_label.setProperty("role", "hint")
            self.desc_label.setWordWrap(True)
            text_box.addWidget(self.desc_label)
        layout.addLayout(text_box, 1)

        self.switch = ToggleSwitch()
        self.switch.setChecked(checked)
        self.switch.toggled.connect(self._repaint_icon)
        layout.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)

        self.setProperty("role", "card")
        self._repaint_icon(checked)

    def _repaint_icon(self, checked: bool) -> None:
        """켜지면 아이콘도 악센트 색으로 — 스위치를 안 봐도 상태를 안다."""
        color = self._color if checked else style.TEXT_FAINT
        self.icon_label.setPixmap(icons.icon(self.icon_name, color, 40).pixmap(20, 20))
        self.title_label.setStyleSheet(
            f"color: {(style.TEXT if checked else style.TEXT_DIM).name()}"
        )

    # ---- 편의 API

    def isChecked(self) -> bool:  # noqa: N802 - Qt 관습에 맞춘다
        return self.switch.isChecked()

    def setChecked(self, value: bool) -> None:  # noqa: N802
        self.switch.setChecked(value)
        self._repaint_icon(value)

    @property
    def toggled(self):
        return self.switch.toggled

    def setSubEnabled(self, value: bool) -> None:  # noqa: N802
        """상위 스위치가 꺼지면 흐리게."""
        self.setEnabled(value)
        self._repaint_icon(self.isChecked() and value)
