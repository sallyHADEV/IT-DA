"""실행 중 편집 잠금.

실행은 GUI 스레드에서 돌면서 정지 버튼이 살아 있도록 중간중간 이벤트를 처리한다
(``RunController._tick`` → ``processEvents``). 그 틈에 노드를 지우거나 탭을 닫으면 엔진이
들고 있던 모델과 화면이 어긋난다. 그래서 실행하는 동안은 읽기 전용이어야 한다.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF


@pytest.fixture
def window(qapp):
    from itda.gui.main_window import MainWindow

    w = MainWindow(restore_recent=False)
    yield w
    w.project.mark_dirty(False)
    w.runner.running = False
    w.close()


def test_running_locks_editing_and_finishing_unlocks(window):
    window._on_run_started("main")

    assert window.editing_locked is True
    assert window.act_undo.isEnabled() is False
    assert window.act_open.isEnabled() is False
    assert window.dock_palette.widget().isEnabled() is False
    assert window.dock_property.widget().isEnabled() is False
    assert window.tabs.tabsClosable() is False  # 탭을 닫으면 씬이 통째로 사라진다
    # 정지는 살아 있어야 한다 — 이게 잠기면 매크로를 멈출 수 없다
    assert window.act_run_stop.isEnabled() is True

    window._on_run_finished("main", True)

    assert window.editing_locked is False
    assert window.act_undo.isEnabled() is True
    assert window.dock_palette.widget().isEnabled() is True
    assert window.tabs.tabsClosable() is True


def test_modal_dialogs_are_locked_too(window):
    """실행 중에 모달 대화상자가 열리면 매크로가 그 자리에서 멈춘다.

    실행이 GUI 스레드의 processEvents 안에서 도는 구조라, 그 위에 대화상자가 이벤트 루프를
    하나 더 얹으면 대화상자를 닫을 때까지 다음 동작이 나가지 않는다.
    """
    window._on_run_started("main")

    for name in ("act_timing", "act_states", "act_entries", "act_about", "act_objectify"):
        assert getattr(window, name).isEnabled() is False, name


def test_run_display_stays_alive_while_locked(window):
    """실행 상황을 보여 주는 것들까지 잠그면 '실행 중 GUI 표시'가 무의미해진다."""
    window._on_run_started("main")

    assert window.dock_log.widget().isEnabled() is True
    assert window.dock_vars.widget().isEnabled() is True
    view = window.current_view()
    assert view.isEnabled() is True  # 캔버스는 계속 보이고 줌·팬도 된다
    assert view.act_zoom_in.isEnabled() is True


def test_canvas_cannot_be_edited_while_running(window):
    view = window.current_view()
    scene = view.flow_scene
    before = len(scene.flow.nodes)

    window._on_run_started("main")

    assert view.isInteractive() is False  # 선택·드래그·연결이 안 먹는다
    assert view.acceptDrops() is False  # 팔레트 드롭으로 노드가 생기지 않는다
    assert view.act_delete.isEnabled() is False
    assert view.act_paste.isEnabled() is False
    assert len(scene.flow.nodes) == before


def test_tabs_opened_during_a_run_are_locked_too(window):
    window._on_run_started("main")
    window.project.add_flow("두번째")
    window.open_flow("두번째")

    view = window.views["두번째"]
    assert view.read_only is True
    assert view.isInteractive() is False


def test_closing_while_running_stops_instead_of_destroying_the_window(window):
    """실행 중에 창을 닫으면 엔진이 쓰고 있는 씬이 사라진다 — 정지부터 한다."""
    from PyQt6.QtGui import QCloseEvent

    stopped = []
    window.runner.stop = lambda: stopped.append(True)
    window.runner.running = True

    event = QCloseEvent()
    window.closeEvent(event)

    assert stopped == [True]
    assert event.isAccepted() is False  # 창은 아직 닫히지 않는다


def test_read_only_context_menu_has_no_editing_entries(window):
    """오른쪽 클릭 메뉴는 씬을 직접 고치므로 잠겼을 때 새면 안 된다."""
    from PyQt6.QtCore import QPoint

    view = window.current_view()
    view.resize(600, 400)

    before = " ".join(a.text() for a in view.build_context_menu(QPoint(50, 50)).actions())
    assert "노드 추가" in before  # 평소에는 편집 항목이 있고

    window._on_run_started("main")

    entries = " ".join(a.text() for a in view.build_context_menu(QPoint(50, 50)).actions())
    assert "노드 추가" not in entries
    assert "붙여넣기" not in entries
    assert "삭제" not in entries
    assert "전체 보기" in entries  # 보기 기능은 남는다
