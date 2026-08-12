"""멀티 플로우 스케줄러.

"복수의 매크로가 동시에 동작하고, 우선순위를 가져갈 수 있음" 을 담당한다.

플로우마다 스레드 하나와 자기 :class:`~itda.engine.runner.Engine` 을 갖는다. 변수와 상황
판정은 플로우별로 독립이고, **입력 장치만 공유**한다 — 그래서 하나뿐인 마우스·키보드를
:class:`~itda.engine.arbiter.InputArbiter` 가 우선순위대로 나눠 준다.

화면 캡처는 GDI 경로를 쓰므로 작업 스레드에서도 안전하다(:mod:`itda.vision.gdi_capture`).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from itda.core.events import BUS
from itda.core.model import FlowEntry
from itda.engine.arbiter import InputArbiter
from itda.engine.runner import Engine


@dataclass
class RunSlot:
    """실행 중인 플로우 하나."""

    entry: FlowEntry
    engine: Engine
    thread: threading.Thread | None = None
    runs: int = 0
    last_ok: bool | None = None
    stopped: bool = field(default=False)

    @property
    def key(self) -> str:
        return self.entry.flow


class MultiFlowScheduler:
    """여러 플로우를 동시에 돌린다."""

    def __init__(self, project, sender_factory=None, arbiter: InputArbiter | None = None,
                 loop_interval_ms: int = 500) -> None:
        self.project = project
        self.sender_factory = sender_factory or _dry_run_factory
        self.arbiter = arbiter or InputArbiter()
        self.loop_interval_ms = loop_interval_ms
        #: 현재 실행 중인 슬롯만 보관한다. 완료된 실행은 _completed로 옮긴다.
        self.slots: dict[str, RunSlot] = {}
        self._completed: dict[str, RunSlot] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ 시작 / 정지

    def entries(self, autostart_only: bool = False) -> list[FlowEntry]:
        """실행 대상 목록. 우선순위가 높은 순서."""
        items = [e for e in self.project.settings.entries if e.enabled]
        if autostart_only:
            items = [e for e in items if e.autostart]
        return sorted(items, key=lambda e: -e.priority)

    def start_all(self) -> list[str]:
        """자동 시작으로 표시된 플로우를 전부 띄운다."""
        started = []
        for entry in self.entries(autostart_only=True):
            if self.start(entry):
                started.append(entry.flow)
        if not started:
            BUS.log("자동 시작으로 표시된 플로우가 없습니다", level="warn")
        return started

    def start(self, entry: FlowEntry) -> bool:
        """플로우 하나를 스레드로 띄운다."""
        if self.project.flow(entry.flow) is None:
            BUS.log(f"플로우를 찾을 수 없습니다: {entry.flow}", level="error")
            return False

        with self._lock:
            if entry.flow in self.slots and self.is_running(entry.flow):
                return False

            engine = Engine(
                self.project,
                sender=self.sender_factory(),
                arbiter=self.arbiter,
                sender_factory=self.sender_factory,
            )
            self.arbiter.arm(entry.flow)
            engine.ctx.priority = entry.priority
            slot = RunSlot(entry=entry, engine=engine)
            self.slots[entry.flow] = slot

            thread = threading.Thread(
                target=self._run_slot, args=(slot,), name=f"itda-{entry.flow}", daemon=True
            )
            slot.thread = thread
            thread.start()

        BUS.log(
            f"'{entry.flow}' 시작 (우선순위 {entry.priority}"
            f"{', 반복' if entry.loop else ''})",
            level="info",
        )
        return True

    def start_one(self, flow_key: str, priority: int = 0, loop: bool = False) -> bool:
        """설정에 없는 플로우도 임시로 띄운다."""
        entry = next((e for e in self.project.settings.entries if e.flow == flow_key), None)
        return self.start(entry or FlowEntry(flow=flow_key, priority=priority, loop=loop))

    def stop(self, flow_key: str) -> None:
        with self._lock:
            slot = self.slots.get(flow_key)
            if slot is not None:
                slot.stopped = True
        if slot is None:
            return
        slot.engine.stop()
        self.arbiter.cancel(flow_key)

    def stop_all(self) -> None:
        with self._lock:
            keys = list(self.slots)
        for key in keys:
            self.stop(key)

    def join(self, timeout: float = 5.0) -> bool:
        """모든 스레드가 끝날 때까지 기다린다. 테스트와 종료에 쓴다."""
        deadline = time.perf_counter() + timeout
        with self._lock:
            slots = list(self.slots.values())
        for slot in slots:
            if slot.thread is None:
                continue
            remaining = max(0.0, deadline - time.perf_counter())
            slot.thread.join(remaining)
        return not self.any_running()

    # ------------------------------------------------------------ 상태

    def is_running(self, flow_key: str) -> bool:
        with self._lock:
            slot = self.slots.get(flow_key)
            return bool(slot and slot.thread and slot.thread.is_alive())

    def any_running(self) -> bool:
        with self._lock:
            return any(slot.thread and slot.thread.is_alive() for slot in self.slots.values())

    def running_keys(self) -> list[str]:
        with self._lock:
            return [key for key, slot in self.slots.items()
                    if slot.thread and slot.thread.is_alive()]

    def completed_slots(self) -> list[RunSlot]:
        """완료된 슬롯의 결과 스냅샷. UI 완료 알림과 진단에 쓴다."""
        with self._lock:
            return list(self._completed.values())

    def max_active_priority(self) -> int:
        with self._lock:
            return max((slot.entry.priority for slot in self.slots.values()), default=0)

    def describe(self) -> str:
        with self._lock:
            slots = list(self.slots.items())
        if not slots:
            return "실행 중인 플로우 없음"
        parts = []
        for key, slot in slots:
            state = "실행 중" if slot.thread and slot.thread.is_alive() else "정지"
            parts.append(f"{key}(p{slot.entry.priority}, {state}, {slot.runs}회)")
        holder = self.arbiter.owner
        tail = f" · 입력 사용 중: {holder}" if holder else ""
        return " / ".join(parts) + tail

    # ------------------------------------------------------------ 내부

    def _run_slot(self, slot: RunSlot) -> None:
        try:
            while True:
                with self._lock:
                    if slot.stopped:
                        break
                try:
                    ok = slot.engine.run(slot.key)
                except Exception as e:  # 스레드가 조용히 죽지 않게
                    ok = False
                    BUS.log(f"'{slot.key}' 실행 중 예외: {type(e).__name__}: {e}", level="error")
                finally:
                    self.arbiter.release(slot.key)  # 중간에 끊겨도 권한은 돌려준다

                with self._lock:
                    slot.last_ok = ok
                    slot.runs += 1
                    stopped = slot.stopped
                if not slot.entry.loop or stopped:
                    break
                if slot.engine.stop_flag.get("stop"):
                    break
                time.sleep(max(0, self.loop_interval_ms) / 1000)
        finally:
            BUS.flow_running.emit(slot.key, False)
            with self._lock:
                # 같은 키가 새로 시작된 경우 새 슬롯을 지우지 않는다.
                if self.slots.get(slot.key) is slot:
                    self.slots.pop(slot.key, None)
                self._completed[slot.key] = slot


def _dry_run_factory():
    from itda.engine.input import DryRunSender

    return DryRunSender()
