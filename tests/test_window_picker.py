"""창 선택 도구.

실제 창 열거는 OS 에 의존하므로, 여기서는 **고른 규칙**만 검증한다 —
어떤 창을 목록에서 빼는지, 커서가 움직였을 때 강조가 따라오는지.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication

from itda.core.window_spec import Box
from itda.engine import window as window_module
from itda.gui.tools import window_picker as picker_module
from itda.gui.tools.window_picker import WindowPicker

OUR_PID = 4242
OTHER_PID = 9999


def _ref(title: str, box: tuple[int, int, int, int], pid: int) -> window_module.WindowRef:
    return window_module.WindowRef(
        handle=abs(hash(title)) % 100000,
        title=title,
        box=Box(*box),
        pid=pid,
    )


@pytest.fixture
def fake_windows(monkeypatch):
    """WindowController 를 가짜로 바꿔 원하는 창 목록을 심는다."""
    listed: list[window_module.WindowRef] = []

    class FakeController:
        def __init__(self) -> None:
            pass

        def windows(self):
            return list(listed)

    monkeypatch.setattr(window_module, "WindowController", FakeController)
    monkeypatch.setattr(window_module, "current_process_id", lambda: OUR_PID)
    return listed


def _picker(qapp) -> WindowPicker:
    return WindowPicker()


def test_our_own_windows_are_excluded(qapp, fake_windows):
    """투명해진 노드 편집 창이 대상 앱을 덮어 대신 잡히던 문제.

    도구를 열기 전에 우리 창을 치우지만 대화상자는 숨길 수 없어 투명하게만 만든다
    (숨기면 exec() 가 끝난다). 투명도 0 인 창도 EnumWindows 에는 잡히므로
    프로세스 단위로 빼야 한다.
    """
    fake_windows.extend([
        _ref("노드 편집 - 창 맞추기", (350, 250, 1000, 650), OUR_PID),
        _ref("진짜대상앱", (400, 300, 700, 500), OTHER_PID),
    ])

    picker = _picker(qapp)
    try:
        titles = [t for t, _ in picker._windows]
        assert "노드 편집 - 창 맞추기" not in titles
        assert "진짜대상앱" in titles
    finally:
        picker.close()


def test_hover_picks_the_target_under_our_hidden_dialog(qapp, fake_windows):
    """우리 대화상자가 덮고 있어도 그 아래 대상 앱이 잡혀야 한다."""
    fake_windows.extend([
        _ref("노드 편집 - 창 맞추기", (350, 250, 1000, 650), OUR_PID),
        _ref("진짜대상앱", (400, 300, 700, 500), OTHER_PID),
    ])

    picker = _picker(qapp)
    try:
        centre = (400 + 350, 300 + 250)  # 대상 앱 한가운데
        found = picker._window_at(centre)
        assert found is not None
        assert found[0] == "진짜대상앱"
    finally:
        picker.close()


def test_zero_sized_windows_are_excluded(qapp, fake_windows):
    fake_windows.extend([
        _ref("납작한창", (0, 0, 0, 0), OTHER_PID),
        _ref("멀쩡한창", (10, 10, 100, 100), OTHER_PID),
    ])

    picker = _picker(qapp)
    try:
        assert [t for t, _ in picker._windows] == ["멀쩡한창"]
    finally:
        picker.close()


def test_topmost_window_wins_when_they_overlap(qapp, fake_windows):
    """EnumWindows 는 z-순서로 준다 — 먼저 나온 것이 위에 있는 창이다."""
    fake_windows.extend([
        _ref("위에있는창", (0, 0, 500, 500), OTHER_PID),
        _ref("아래있는창", (0, 0, 500, 500), OTHER_PID),
    ])

    picker = _picker(qapp)
    try:
        assert picker._window_at((100, 100))[0] == "위에있는창"
    finally:
        picker.close()


def _send_key(picker: WindowPicker, key) -> None:
    QApplication.sendEvent(
        picker, QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.ShiftModifier)
    )


def _hover(picker: WindowPicker, screen_point: tuple[int, int]) -> None:
    local = QPoint(
        screen_point[0] - picker.geometry_rect.x(),
        screen_point[1] - picker.geometry_rect.y(),
    )
    QApplication.sendEvent(
        picker,
        QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(local),
            QPointF(local),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def test_arrow_keys_move_the_highlight_not_just_the_crosshair(qapp, fake_windows):
    """방향키로 커서만 옮기면 테두리가 엉뚱한 창에 남아 Enter 로 그대로 확정됐다."""
    fake_windows.extend([
        _ref("위쪽창", (0, 0, 400, 200), OTHER_PID),
        _ref("아래쪽창", (0, 400, 400, 200), OTHER_PID),
    ])

    picker = _picker(qapp)
    try:
        _hover(picker, (100, 100))
        assert picker._hovered[0] == "위쪽창"

        for _ in range(40):  # Shift = 10px 씩 → 400px 아래로
            _send_key(picker, Qt.Key.Key_Down)

        assert picker._hovered is not None, "커서가 아래쪽창 안으로 들어갔다"
        assert picker._hovered[0] == "아래쪽창"
    finally:
        picker.close()


def test_arrow_keys_can_clear_the_highlight(qapp, fake_windows):
    """빈 곳으로 나가면 강조도 없어져야 한다 — 없는 창을 확정하지 않도록."""
    fake_windows.append(_ref("위쪽창", (0, 0, 400, 200), OTHER_PID))

    picker = _picker(qapp)
    try:
        _hover(picker, (100, 100))
        assert picker._hovered is not None

        for _ in range(40):
            _send_key(picker, Qt.Key.Key_Down)

        assert picker._hovered is None
    finally:
        picker.close()


def test_enter_confirms_the_window_the_crosshair_is_on(qapp, fake_windows):
    fake_windows.extend([
        _ref("위쪽창", (0, 0, 400, 200), OTHER_PID),
        _ref("아래쪽창", (0, 400, 400, 200), OTHER_PID),
    ])

    picker = _picker(qapp)
    result = []
    picker.finish = lambda r=None: result.append(r)
    try:
        _hover(picker, (100, 100))
        for _ in range(40):
            _send_key(picker, Qt.Key.Key_Down)
        QApplication.sendEvent(
            picker,
            QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier),
        )

        assert result and result[0] is not None
        assert result[0].title == "아래쪽창"
    finally:
        picker.close()
