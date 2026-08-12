"""화면 캡처의 스레드 안전성.

``QScreen.grabWindow``/``QPixmap``/``QPainter`` 는 GUI 스레드 전용이다 — 다른 스레드에서
부르면 Qt 가 그 자리에서 프로세스를 죽인다(Fatal, 예외로 못 잡는다). 멀티 플로우는 플로우마다
``threading.Thread`` 를 새로 띄우므로(:mod:`itda.engine.scheduler`), 그 작업 스레드에서
Qt 캡처 경로를 절대 타면 안 된다.

Qt Fatal 은 프로세스를 통째로 끝내 버려서, 안전장치가 없는 상태를 실제로 작업 스레드에서
실행해 "재현" 하는 건 이 테스트 프로세스 자체를 죽일 위험이 있다 — 하지 않는다. 대신 몽키패치로
"Qt 함수가 불렸는지" 만 안전하게 확인한다.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest

from itda.vision import capture


@pytest.fixture
def worker_result():
    """작업 스레드에서 함수 하나를 돌리고 결과(또는 예외)를 받아 온다."""

    def run(fn):
        box: dict[str, object] = {}

        def target():
            try:
                box["value"] = fn()
            except BaseException as e:  # noqa: BLE001 - 스레드 예외도 잡아서 보고
                box["error"] = e

        t = threading.Thread(target=target)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "작업 스레드가 끝나지 않았다"
        if "error" in box:
            raise box["error"]
        return box["value"]

    return run


def test_on_gui_thread_true_on_the_qt_thread(qapp):
    assert capture.on_gui_thread() is True


def test_on_gui_thread_false_on_a_worker_thread(qapp, worker_result):
    assert worker_result(capture.on_gui_thread) is False


def test_grab_array_never_touches_qt_on_a_worker_thread(qapp, monkeypatch, worker_result):
    """GDI 가 실패해도, 작업 스레드에서는 Qt 로 폴백하지 않고 빈 배열을 돌려줘야 한다."""
    from itda.vision import gdi_capture

    monkeypatch.setattr(gdi_capture, "is_available", lambda: True)
    monkeypatch.setattr(gdi_capture, "grab", lambda *a, **k: np.zeros((0, 0, 3), dtype=np.uint8))

    def qt_path_touched(*_a, **_k):
        raise AssertionError("작업 스레드에서 Qt 캡처 경로가 불렸다 — Fatal 크래시 위험")

    monkeypatch.setattr(capture, "grab_all", qt_path_touched)
    monkeypatch.setattr(capture, "grab_rect", qt_path_touched)

    result = worker_result(capture.grab_array)
    assert result.size == 0  # 예외 대신 빈 배열


def test_grab_array_still_falls_back_to_qt_on_the_gui_thread(qapp, monkeypatch):
    """메인 스레드에서는 예전처럼 Qt 폴백이 살아 있어야 한다 — 여기서 막으면 과하다."""
    from itda.vision import gdi_capture
    from PyQt6.QtGui import QPixmap

    monkeypatch.setattr(gdi_capture, "is_available", lambda: True)
    monkeypatch.setattr(gdi_capture, "grab", lambda *a, **k: np.zeros((0, 0, 3), dtype=np.uint8))

    stand_in = QPixmap(5, 5)
    stand_in.fill()
    monkeypatch.setattr(capture, "grab_all", lambda: stand_in)

    result = capture.grab_array()
    assert result.shape == (5, 5, 3)


# ---------------------------------------------------------------- screenshot 액션


@pytest.fixture
def sender():
    from itda.engine.input import DryRunSender

    return DryRunSender()


@pytest.fixture
def engine(project, sender):
    from itda.engine.runner import Engine

    e = Engine(project, sender=sender)
    project.settings.timing.default_pre_ms = 0
    project.settings.timing.default_post_ms = 0
    project.settings.human.enabled = False
    return e


def _screenshot_flow(project, path: str = "shot.png"):
    from itda.core.model import Action, Node

    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()
    node = Node(
        type="action_group",
        title="캡처",
        actions=[Action(type="screenshot", params={"region_mode": "full", "path": path})],
    )
    flow.add_node(node)
    flow.connect(start.id, "ok", node.id)
    return flow


def test_screenshot_executor_uses_the_thread_safe_path_not_qpixmap(project, engine, monkeypatch):
    """스크린샷 액션이 QPixmap 경로 대신 스레드 안전한 배열 경로를 쓰는지."""
    _screenshot_flow(project)
    calls = []

    monkeypatch.setattr(capture, "grab_array", lambda *a, **k: (
        calls.append("grab_array"), np.zeros((4, 4, 3), dtype=np.uint8)
    )[1])
    monkeypatch.setattr(capture, "save_bgr", lambda arr, path: (calls.append("save_bgr"), True)[1])

    def forbidden(*_a, **_k):
        raise AssertionError("QPixmap 경로가 불렸다 — 작업 스레드에서 크래시 위험")

    monkeypatch.setattr(capture, "grab_all", forbidden)
    monkeypatch.setattr(capture, "grab_rect", forbidden)
    monkeypatch.setattr(capture, "save_pixmap", forbidden)

    ok = engine.run("main")

    assert ok is True
    assert calls == ["grab_array", "save_bgr"]
