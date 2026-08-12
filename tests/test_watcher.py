"""상황 감시 스레드 테스트.

화면을 갈아 끼우며 "지금 어떤 화면인가" 가 따라오는지 본다. 감시는 화면을 읽기만 하므로
입력 안전장치와 무관하다.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from itda.core.model import Condition, State, TargetObject
from itda.engine.context import ExecutionContext
from itda.engine.watcher import StateWatcher


@pytest.fixture
def screen(monkeypatch):
    """지금 보이는 객체를 테스트가 정한다."""
    visible: set[str] = set()

    def find_object(_self, names, **kwargs):
        from itda.vision.matcher import Match

        for name in names:
            if name in visible:
                return Match(5, 5, 10, 10, 0.99)
        return None

    monkeypatch.setattr(ExecutionContext, "find_object", find_object)
    monkeypatch.setattr(
        ExecutionContext, "screen",
        lambda _self, fresh=False: np.zeros((60, 60, 3), dtype=np.uint8),
    )
    return visible


def add_state(project, name: str, marker: str, **kwargs) -> State:
    state = State(
        name=name,
        condition=Condition(op="and", items=[
            Condition(type="object_visible", params={"object": marker})
        ]),
        **kwargs,
    )
    project.states.states.append(state)
    project.objects.objects.append(TargetObject(name=marker))
    return state


@pytest.fixture
def watcher(project, screen):
    add_state(project, "메인화면", "메인마커")
    add_state(project, "설정창", "설정마커")
    project.states.watcher.interval_ms = 50
    w = StateWatcher(project)
    yield w
    w.stop()


def wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# ---------------------------------------------------------------- 기본


def test_detect_once_without_starting(watcher, screen):
    screen.add("설정마커")
    assert watcher.detect_once().name == "설정창"
    assert watcher.latest_name == "설정창"


def test_unknown_name_when_nothing_matches(watcher):
    assert watcher.detect_once() is None
    assert watcher.latest_name == "UNKNOWN"


def test_starts_and_stops(watcher, screen):
    screen.add("메인마커")
    assert watcher.start() is True
    assert wait_until(lambda: watcher.detections > 0)
    assert watcher.running

    watcher.stop()
    assert not watcher.running


def test_follows_screen_changes(watcher, screen):
    screen.add("메인마커")
    watcher.start()
    assert wait_until(lambda: watcher.latest_name == "메인화면")

    screen.clear()
    screen.add("설정마커")
    assert wait_until(lambda: watcher.latest_name == "설정창")


def test_state_change_callback(project, screen):
    add_state(project, "메인화면", "메인마커")
    project.states.watcher.interval_ms = 50
    seen: list[str] = []

    watcher = StateWatcher(project, on_state=lambda s: seen.append(s.name if s else "UNKNOWN"))
    screen.add("메인마커")
    watcher.start()
    try:
        assert wait_until(lambda: "메인화면" in seen)
    finally:
        watcher.stop()


def test_callback_only_on_change(project, screen):
    add_state(project, "메인화면", "메인마커")
    project.states.watcher.interval_ms = 30
    calls: list[object] = []

    watcher = StateWatcher(project, on_state=calls.append)
    screen.add("메인마커")
    watcher.start()
    try:
        assert wait_until(lambda: watcher.detections >= 5)
    finally:
        watcher.stop()

    # 여러 번 판별했지만 화면이 그대로면 알림은 한 번뿐이다
    assert len(calls) == 1


def test_refuses_to_start_without_states(project):
    watcher = StateWatcher(project)
    assert watcher.start() is False
    assert not watcher.running


def test_starting_twice_is_harmless(watcher, screen):
    screen.add("메인마커")
    assert watcher.start() is True
    assert watcher.start() is True
    watcher.stop()


# ---------------------------------------------------------------- 복구 플로우


def test_recovery_fires_after_unknown_persists(project, screen):
    add_state(project, "메인화면", "메인마커")
    config = project.states.watcher
    config.interval_ms = 30
    config.unknown_timeout_ms = 60
    config.recovery_flow = "복구"

    called: list[str] = []
    watcher = StateWatcher(project, on_unknown_timeout=called.append)
    watcher.start()  # 아무 마커도 안 보이는 상태 = UNKNOWN
    try:
        assert wait_until(lambda: called, timeout=3.0)
    finally:
        watcher.stop()

    assert called == ["복구"]


def test_recovery_fires_only_once_per_episode(project, screen):
    add_state(project, "메인화면", "메인마커")
    config = project.states.watcher
    config.interval_ms = 20
    config.unknown_timeout_ms = 40
    config.recovery_flow = "복구"

    called: list[str] = []
    watcher = StateWatcher(project, on_unknown_timeout=called.append)
    watcher.start()
    try:
        assert wait_until(lambda: called)
        time.sleep(0.3)  # 계속 UNKNOWN 이어도 다시 부르지 않는다
    finally:
        watcher.stop()

    assert len(called) == 1


def test_recovery_resets_when_the_screen_recovers(project, screen):
    add_state(project, "메인화면", "메인마커")
    config = project.states.watcher
    config.interval_ms = 20
    config.unknown_timeout_ms = 40
    config.recovery_flow = "복구"

    called: list[str] = []
    watcher = StateWatcher(project, on_unknown_timeout=called.append)
    watcher.start()
    try:
        assert wait_until(lambda: len(called) == 1)
        screen.add("메인마커")  # 화면이 돌아왔다
        assert wait_until(lambda: watcher.latest_name == "메인화면")
        screen.clear()  # 다시 모르는 화면
        assert wait_until(lambda: len(called) == 2, timeout=3.0)
    finally:
        watcher.stop()


def test_no_recovery_when_not_configured(project, screen):
    add_state(project, "메인화면", "메인마커")
    project.states.watcher.interval_ms = 20
    project.states.watcher.unknown_timeout_ms = 0  # 사용 안 함

    called: list[str] = []
    watcher = StateWatcher(project, on_unknown_timeout=called.append)
    watcher.start()
    try:
        assert wait_until(lambda: watcher.detections >= 4)
    finally:
        watcher.stop()

    assert called == []


# ---------------------------------------------------------------- 견고성


def test_detection_error_does_not_kill_the_thread(project, screen, monkeypatch):
    add_state(project, "메인화면", "메인마커")
    project.states.watcher.interval_ms = 20
    watcher = StateWatcher(project)

    calls = {"n": 0}
    original = watcher.machine.detect

    def flaky(fresh=False):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("일시적 오류")
        return original(fresh=fresh)

    watcher.machine.detect = flaky
    watcher.start()
    try:
        assert wait_until(lambda: calls["n"] >= 4)  # 오류 뒤에도 계속 돈다
        assert watcher.running
    finally:
        watcher.stop()


def test_watcher_has_its_own_context(project, screen):
    """실행 엔진과 화면 캐시를 공유하면 스레드끼리 부딪힌다."""
    from itda.engine.runner import Engine

    engine = Engine(project)
    watcher = StateWatcher(project)

    assert watcher.ctx is not engine.ctx
    assert watcher.machine is not engine.ctx.states


def test_watcher_never_injects_input(project, screen):
    from itda.engine.input import DryRunSender

    watcher = StateWatcher(project)
    assert isinstance(watcher.ctx.sender, DryRunSender)


# ---------------------------------------------------------------- GUI 연동


def test_controller_toggles_watching(qapp, project, screen):
    from itda.gui.run_controller import RunController

    add_state(project, "메인화면", "메인마커")
    project.states.watcher.interval_ms = 40
    controller = RunController()

    try:
        assert controller.start_watching(project) is True
        assert controller.watching
        assert wait_until(lambda: controller.watcher.detections > 0)
    finally:
        controller.stop_watching()

    assert not controller.watching


def test_controller_respects_the_disabled_setting(qapp, project, screen):
    from itda.gui.run_controller import RunController

    add_state(project, "메인화면", "메인마커")
    project.states.watcher.enabled = False
    controller = RunController()

    assert controller.start_watching(project) is False
    assert not controller.watching
