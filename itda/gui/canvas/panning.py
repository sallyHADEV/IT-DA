"""캔버스 화면 이동(패닝).

플로우 캔버스와 액션 시퀀스 뷰가 **똑같이** 동작해야 해서 여기 한 번만 둔다. 두 곳에
같은 코드를 두면 한쪽만 고치고 다른 쪽을 잊는다.

* 마우스 **가운데 버튼** 드래그 — 어느 편집기에서나 통하는 관례
* **Alt** 또는 **Shift** + 좌클릭 드래그 — 가운데 버튼이 없는 마우스/트랙패드용

Shift 를 써도 되는 이유: Qt 의 다중 선택 수식키는 ``Ctrl`` 이고, ``Shift`` 는 이 씬에서
원래도 아무 일도 하지 않았다(넣기 전후 모두 클릭 하나에 하나만 선택됐다 — 확인함).
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt

#: 좌클릭과 함께 누르면 화면 이동이 되는 수식키
PAN_MODIFIERS = Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier


class PanMixin:
    """가운데 버튼 / Alt·Shift + 좌드래그로 화면을 옮긴다.

    ``QGraphicsView`` 앞에 섞어 쓴다::

        class FlowView(PanMixin, QGraphicsView): ...

    화면을 옮기는 것뿐이라 **읽기 전용일 때도 그대로 둔다** — 매크로가 도는 동안 실행
    상황을 따라가려면 이동은 살아 있어야 한다.
    """

    # 인스턴스에 처음 대입되기 전까지 쓰는 기본값. __init__ 을 두지 않아 MRO 가 단순해진다.
    _panning = False
    _pan_start = QPoint()

    def _start_pan(self, point: QPoint) -> None:
        self._panning = True
        self._pan_start = point
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _end_pan(self) -> None:
        self._panning = False
        self.unsetCursor()

    def mousePressEvent(self, event) -> None:
        pans = event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and bool(event.modifiers() & PAN_MODIFIERS)
        )
        if pans:
            self._start_pan(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        # 누른 곳이 이 뷰 밖이면 press 를 못 받는다. 가운데 버튼 또는 Alt/Shift+좌클릭이 눌린 채로 들어오면 그때 시작한다.
        has_pan_button = bool(event.buttons() & Qt.MouseButton.MiddleButton) or (
            bool(event.buttons() & Qt.MouseButton.LeftButton) and bool(event.modifiers() & PAN_MODIFIERS)
        )
        if not self._panning and has_pan_button:
            self._start_pan(event.position().toPoint())

        if self._panning:
            delta = event.position().toPoint() - self._pan_start
            self._pan_start = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            still_panning_buttons = event.buttons() & (Qt.MouseButton.MiddleButton | Qt.MouseButton.LeftButton)
            if not still_panning_buttons:
                self._end_pan()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        if self._panning:
            self._end_pan()
        super().focusOutEvent(event)
