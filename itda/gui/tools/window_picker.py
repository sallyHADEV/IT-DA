"""창 선택 도구.

화면을 얼린 뒤, 마우스 아래에 있는 창을 실시간으로 찾아 붉은 테두리로 감싼다. 클릭하면 그
창의 제목과 (화면에 보이는 기준의) 위치·크기를 돌려준다 — 창 맞추기 노드/액션의 제목·좌표·
크기 칸에 그대로 채워 넣기 위해서다.

창 목록은 도구를 여는 시점에 **한 번만** 찍어 둔다. 선택하는 몇 초 사이에 창이 움직여도
테두리가 흔들리지 않고, 마우스가 움직일 때마다 창을 새로 훑지 않아도 된다(스크린샷 도구가
화면 스냅샷을 한 번만 뜨는 것과 같은 이유).

**잇다 자신의 창은 프로세스 단위로 걸러낸다.** 도구를 열기 전에 우리 창을 치우긴 하지만
(:meth:`MainWindow._hidden_during`), 대화상자는 숨기면 ``exec()`` 가 끝나 버려서 투명하게만
만든다. 그런데 투명도 0 인 창도 ``EnumWindows`` 에는 그대로 잡히므로, 창 목록에서 빼지 않으면
**안 보이는 노드 편집 창이 그 아래 대상 앱 대신 선택된다**(실제로 그랬다).
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen

from itda.gui import style
from itda.gui.tools.overlay import FrozenOverlay

HINT = "창 위에서 클릭해 선택 · Enter 로 확정 · ESC 취소"
BORDER = QColor(224, 90, 84)  # 코럴 레드 — 선택 강조 전용, 팔레트의 실패 색과 계열을 맞춤


@dataclass(frozen=True)
class WindowPick:
    """고른 창 하나 — 눈에 보이는 기준의 위치·크기(투명 테두리 보정 적용됨)."""

    title: str
    x: int
    y: int
    width: int
    height: int


class WindowPicker(FrozenOverlay):
    def __init__(self) -> None:
        super().__init__()
        self._windows = self._enumerate()
        self._hovered: tuple[str, tuple[int, int, int, int]] | None = None

    def _enumerate(self) -> list[tuple[str, tuple[int, int, int, int]]]:
        """지금 떠 있는 창 목록 — (제목, 눈에 보이는 사각형) 쌍으로.

        잇다 자신의 창은 전부 뺀다. 핸들 하나만 빼면 투명해진 대화상자가 남아 대상 앱을 덮는다.
        """
        from itda.engine.window import WindowController, current_process_id

        try:
            controller = WindowController()
        except RuntimeError:  # pragma: no cover - 다른 OS
            return []
        mine = current_process_id()
        return [
            (w.title, w.box.as_tuple())
            for w in controller.windows()
            if w.pid != mine and w.box.width > 0 and w.box.height > 0
        ]

    def _window_at(self, point: tuple[int, int]) -> tuple[str, tuple[int, int, int, int]] | None:
        """가상 데스크톱 좌표 아래에 있는 창. z-순서상 가장 앞의 것을 고른다."""
        x, y = point
        for title, box in self._windows:
            bx, by, bw, bh = box
            if bx <= x < bx + bw and by <= y < by + bh:
                return title, box
        return None

    # ------------------------------------------------------------ 그리기

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self.draw_background(painter, dim=90)

            if self._hovered is not None:
                title, box = self._hovered
                local = self._local_rect(box)
                painter.setPen(QPen(BORDER, 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(local)
                self._draw_info(painter, local, title, box)
            else:
                self.draw_crosshair(painter)

            self.draw_hint(painter, HINT)
        finally:
            painter.end()

    def _local_rect(self, box: tuple[int, int, int, int]) -> QRect:
        bx, by, bw, bh = box
        offset = self.geometry_rect.topLeft()
        return QRect(bx - offset.x(), by - offset.y(), bw, bh)

    def _draw_info(self, painter: QPainter, local: QRect, title: str,
                    box: tuple[int, int, int, int]) -> None:
        _, _, w, h = box
        text = f"{title or '(제목 없음)'}   {w}×{h}"
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        max_width = min(metrics.horizontalAdvance(text) + 20, self.width() - 20)
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max_width - 20)

        top = local.top() - 32
        if top < 8:
            top = min(local.bottom() + 6, self.height() - 30)
        info = QRect(max(8, min(local.left(), self.width() - max_width - 8)), top, max_width, 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(style.SURFACE))
        painter.drawRoundedRect(info, 6, 6)
        painter.setPen(QPen(style.TEXT))
        painter.drawText(info, Qt.AlignmentFlag.AlignCenter, elided)

    # ------------------------------------------------------------ 이벤트

    def _sync_hover(self) -> None:
        """커서 자리에 맞춰 강조할 창을 다시 고른다."""
        self._hovered = self._window_at(self.screen_point(self.cursor_pos))

    def mouseMoveEvent(self, event) -> None:
        self.cursor_pos = event.position().toPoint()
        self._sync_hover()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            self.finish(None)
            return
        if self._hovered is not None:
            self.finish(self._as_pick(*self._hovered))
        # 창이 없는 자리를 클릭하면 무시한다 — ESC 로만 취소

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._hovered is not None:
                self.finish(self._as_pick(*self._hovered))
            return
        super().keyPressEvent(event)
        # 방향키는 커서만 옮긴다. 여기서 강조를 다시 고르지 않으면 테두리가 엉뚱한 창에
        # 남아 있다가 Enter 로 그대로 확정된다.
        self._sync_hover()
        self.update()

    @staticmethod
    def _as_pick(title: str, box: tuple[int, int, int, int]) -> WindowPick:
        x, y, w, h = box
        return WindowPick(title, x, y, w, h)


def pick_window() -> WindowPick | None:
    """창 선택 도구를 띄우고 고른 창 정보를 돌려준다. 취소하면 None."""
    return WindowPicker().run()
