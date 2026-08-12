"""화면 도구(좌표·스크린샷) 오버레이 — 대화상자 위에서도 동작하는지.

노드 편집 창은 모달이다. 오버레이가 모달이 아니면 이벤트를 하나도 못 받아서 커서를 따라오지
않고, 클릭은 아래 대화상자로 새어 나간다. 실제로 겪은 문제라 못을 박아 둔다.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QDialog

from itda.gui.tools.overlay import FrozenOverlay


def test_overlay_outranks_an_open_modal_dialog(qapp):
    """모달 대화상자가 떠 있어도 오버레이가 입력을 받는 쪽이어야 한다."""
    dialog = QDialog()
    dialog.setModal(True)
    dialog.show()
    assert QApplication.activeModalWidget() is dialog

    overlay = FrozenOverlay()
    overlay.show()
    try:
        # 모달 스택의 꼭대기가 오버레이여야 대화상자가 이벤트를 가로채지 않는다
        assert overlay.windowModality() == Qt.WindowModality.ApplicationModal
        assert QApplication.activeModalWidget() is overlay
    finally:
        overlay.close()
        dialog.close()


def test_closing_overlay_any_other_way_ends_the_wait(qapp):
    """Alt+F4 로 닫아도 대기 루프가 끝나야 한다 — 안 그러면 앱 전체가 멈춘다."""
    overlay = FrozenOverlay()
    hung: list[bool] = []

    QTimer.singleShot(0, overlay.close)  # 창 닫기 버튼 / Alt+F4 와 같은 경로

    def watchdog() -> None:
        if overlay._loop is not None:  # run() 이 아직 안 끝났다 = 멈춘 것
            hung.append(True)
            overlay._loop.quit()

    QTimer.singleShot(2000, watchdog)

    assert overlay.run() is None
    assert not hung


def test_capture_clears_every_itda_window_from_the_screen(qapp):
    """도구가 화면을 얼리는 동안 우리 창은 화면에 하나도 남아 있으면 안 된다.

    메인 창만 치우면 노드 편집 창이 얼어붙은 배경에 찍혀 대상 프로그램을 가린다.
    """
    from itda.gui.main_window import MainWindow

    window = MainWindow(restore_recent=False)
    window.show()
    dialog = QDialog(window)
    dialog.show()

    seen: dict[str, object] = {}

    def probe() -> str:
        seen["main_visible"] = window.isVisible()
        seen["dialog_opacity"] = dialog.windowOpacity()
        return "찍었다"

    try:
        assert window._hidden_during(probe) == "찍었다"
        assert seen["main_visible"] is False
        assert seen["dialog_opacity"] == 0.0  # 캡처에서 사라진다
        # 끝나면 둘 다 되돌아온다
        assert window.isVisible() and dialog.isVisible()
        assert dialog.windowOpacity() == 1.0
    finally:
        dialog.close()
        window.close()


def test_capture_does_not_close_an_open_dialog(qapp):
    """대화상자를 숨기면 exec() 가 끝나 편집 창이 닫혀 버린다 — 그러면 안 된다.

    사용자가 겪은 증상이 바로 이것이다: 좌표를 찍고 나면 노드 편집 창이 사라지고
    플로우차트로 돌아가 있었다.
    """
    from itda.gui.main_window import MainWindow

    window = MainWindow(restore_recent=False)
    window.show()
    dialog = QDialog(window)
    seen: dict[str, object] = {}

    def use_tool() -> None:
        window._hidden_during(lambda: seen.update(alive=dialog.isVisible()))

    QTimer.singleShot(0, use_tool)
    QTimer.singleShot(600, lambda: dialog.done(7))

    try:
        # 도구를 쓰는 동안에도 대화상자는 살아 있어야 하고, 닫는 건 우리여야 한다
        assert dialog.exec() == 7
        assert seen == {"alive": True}
    finally:
        window.close()
