"""상황 감시 — 주기적으로 "지금 어떤 화면인가" 를 판별한다.

요구사항의 "주기적으로 판별하여 프로그램이 어떤 상태에 있는지 이름을 명명" 이 여기다.
설정(:class:`~itda.core.model.WatcherConfig`)의 주기·미지정 이름·복구 플로우를 실제로 쓴다.

**감시는 화면을 읽기만 한다.** 팝업을 닫는 등 입력이 필요한 처리는 실행 엔진이 한다 —
입력 장치를 쥐고 있는 쪽이 처리해야 다른 플로우와 충돌하지 않기 때문이다. 그래서 워처는
자기 :class:`~itda.engine.context.ExecutionContext` 를 따로 갖는다(화면 캐시를 공유하면
스레드끼리 부딪힌다).

편집기에서도 켤 수 있다 — 상황 정의가 제대로 됐는지 화면을 옮겨 가며 바로 확인할 수 있다.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from itda.core.events import BUS
from itda.engine.context import ExecutionContext
from itda.engine.input import DryRunSender
from itda.engine.state_machine import StateMachine

MIN_INTERVAL_MS = 50


class StateWatcher:
    """배경에서 상황을 계속 판별한다."""

    def __init__(
        self,
        project,
        on_state: Callable[[object], None] | None = None,
        on_unknown_timeout: Callable[[str], None] | None = None,
    ) -> None:
        self.project = project
        self.on_state = on_state
        self.on_unknown_timeout = on_unknown_timeout

        # 감시 전용 문맥 — 입력은 하지 않으므로 안전한 주입기를 쓴다
        self.ctx = ExecutionContext(project=project, sender=DryRunSender(), flow_key="감시")
        self.machine = StateMachine(project.states, self.ctx)

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest = None
        self._latest_name = ""
        self._unknown_since: float | None = None
        self._recovery_fired = False
        #: 판별 횟수 (진단용)
        self.detections = 0

    # ------------------------------------------------------------ 상태

    @property
    def config(self):
        return self.project.states.watcher

    @property
    def latest(self):
        with self._lock:
            return self._latest

    @property
    def latest_name(self) -> str:
        with self._lock:
            return self._latest_name or self.config.unknown_name

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------ 제어

    def start(self) -> bool:
        """감시를 시작한다. 상황이 하나도 없으면 시작하지 않는다."""
        if self.running:
            return True
        if not self.project.states.states:
            BUS.log("등록된 상황이 없어 감시를 시작하지 않습니다", level="warn")
            return False

        self._stop.clear()
        self._unknown_since = None
        self._recovery_fired = False
        self._thread = threading.Thread(target=self._loop, name="itda-watcher", daemon=True)
        self._thread.start()
        BUS.log(f"상황 감시 시작 (주기 {self.config.interval_ms}ms)", level="info")
        return True

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._thread = None

    def detect_once(self):
        """한 번만 판별한다. 편집기에서 버튼으로 확인할 때 쓴다."""
        state = self.machine.detect(fresh=True)
        self._remember(state)
        return state

    # ------------------------------------------------------------ 내부

    def _loop(self) -> None:
        interval = max(MIN_INTERVAL_MS, self.config.interval_ms) / 1000
        while not self._stop.is_set():
            try:
                state = self.machine.detect(fresh=True)
                self.detections += 1
                self._remember(state)
                self._check_unknown(state)
            except Exception as e:  # 감시가 죽어도 실행은 계속돼야 한다
                BUS.log(f"상황 감시 오류: {type(e).__name__}: {e}", level="warn")
            self._stop.wait(interval)

        BUS.log("상황 감시 정지", level="info")

    def _remember(self, state) -> None:
        with self._lock:
            changed = state is not self._latest
            self._latest = state
            self._latest_name = state.name if state else self.config.unknown_name

        if changed and self.on_state is not None:
            self.on_state(state)

    def _check_unknown(self, state) -> None:
        """모르는 화면이 오래 지속되면 복구 플로우를 부른다."""
        timeout = self.config.unknown_timeout_ms
        if state is not None:
            self._unknown_since = None
            self._recovery_fired = False
            return
        if timeout <= 0 or not self.config.recovery_flow:
            return

        now = time.perf_counter()
        if self._unknown_since is None:
            self._unknown_since = now
            return
        if self._recovery_fired or (now - self._unknown_since) * 1000 < timeout:
            return

        self._recovery_fired = True
        BUS.log(
            f"'{self.config.unknown_name}' 상태가 {timeout}ms 넘게 이어져 "
            f"복구 플로우 '{self.config.recovery_flow}' 를 호출합니다",
            level="warn",
        )
        if self.on_unknown_timeout is not None:
            self.on_unknown_timeout(self.config.recovery_flow)
