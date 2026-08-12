"""실제 실행 제어.

데모 재생과 달리 여기서는 **진짜 마우스와 키보드가 움직인다.** 그래서 두 가지를 먼저 갖춘다.

1. **비상 정지** — 전역 단축키(기본 F12). 잇다 창이 뒤에 있어도 언제든 멈춘다.
   매크로가 폭주하면 마우스를 뺏겨 정지 버튼을 누르지 못할 수 있기 때문에 필수다.
2. **응답성** — 실행은 메인 스레드에서 돌되, 정지 확인 시점마다 이벤트를 처리해
   정지 버튼과 단축키가 계속 살아 있게 한다. (화면 캡처가 GUI 스레드를 요구한다.)
"""

from __future__ import annotations

import ctypes
import queue
import sys

from PyQt6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from itda.core.events import BUS
from itda.engine.runner import Engine
from itda.engine.scheduler import MultiFlowScheduler

if sys.platform == "win32":
    from ctypes import wintypes

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
VK_F12 = 0x7B
#: RegisterHotKey 에 쓸 임의의 고유 id
HOTKEY_ID = 0x1704


class GlobalHotkey(QAbstractNativeEventFilter):
    """전역 단축키 하나를 잡는다. 실패해도 앱은 정상 동작한다."""

    #: ctypes 함수 시그니처는 프로세스에서 한 번만 설정하면 된다.
    _hotkey_proto_done = False

    def __init__(self, on_pressed, vk: int = VK_F12) -> None:
        super().__init__()
        self.on_pressed = on_pressed
        self.vk = vk
        self.registered = False
        self._was_down = False

    def install(self, app: QApplication) -> bool:
        if sys.platform != "win32":  # pragma: no cover - 다른 OS
            return False
        try:
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            if not type(self)._hotkey_proto_done:
                user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
                user32.RegisterHotKey.restype = wintypes.BOOL
                user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
                user32.UnregisterHotKey.restype = wintypes.BOOL
                user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
                user32.GetAsyncKeyState.restype = wintypes.SHORT
                type(self)._hotkey_proto_done = True

            self.registered = bool(
                user32.RegisterHotKey(None, HOTKEY_ID, MOD_NOREPEAT, self.vk)
            )
        except Exception:
            self.registered = False
        if self.registered:
            self._was_down = False
            app.installNativeEventFilter(self)
        return self.registered

    def remove(self, app: QApplication) -> None:
        if not self.registered:
            return
        try:
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
        except Exception:
            pass
        app.removeNativeEventFilter(self)
        self.registered = False
        self._was_down = False

    def poll(self) -> bool:
        """실행 중 F12 눌림을 직접 확인한다."""
        if sys.platform != "win32":
            return False
        try:
            down = bool(ctypes.windll.user32.GetAsyncKeyState(self.vk) & 0x8000)
        except Exception:
            return False
        pressed = down and not self._was_down
        self._was_down = down
        return pressed

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt 이름
        if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.on_pressed()
                return True, 0
        return False, 0


class RunController(QObject):
    """실제 실행을 시작하고 멈춘다."""

    started = pyqtSignal(str)
    finished = pyqtSignal(str, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.engine: Engine | None = None
        self.scheduler: MultiFlowScheduler | None = None
        self.watcher = None
        self._watcher_owned_by_run = False
        self._recovery_requests: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.running = False
        self.hotkey = GlobalHotkey(self.stop)
        self._watch = QTimer(self)
        self._watch.setInterval(400)
        self._watch.timeout.connect(self._check_scheduler)

    # ------------------------------------------------------------

    def install_hotkey(self) -> bool:
        return self.hotkey.install(QApplication.instance())

    def release_hotkey(self) -> None:
        self.hotkey.remove(QApplication.instance())

    def run(self, project, flow_key: str) -> bool:
        """플로우를 실제 입력으로 실행한다."""
        if self.running:
            return False

        from itda.engine.input import Win32Sender
        from itda.vision.coords import current_screens

        # 모니터 정보는 GUI 스레드에서 미리 확보해 둔다
        sender = Win32Sender(screens=current_screens())

        from itda.engine.arbiter import InputArbiter

        # 비동기로 띄우는 플로우와 입력이 섞이지 않도록 중재기를 함께 넘긴다
        self.engine = Engine(
            project,
            sender=sender,
            arbiter=InputArbiter(),
            sender_factory=lambda: Win32Sender(screens=current_screens()),
        )
        self.engine.ctx.tick = self._tick
        self._start_run_watcher(project)
        self.running = True
        self.started.emit(flow_key)
        BUS.log(
            f"실제 실행 시작 — 멈추려면 F12 또는 정지 버튼 (플로우 '{flow_key}')",
            level="warn",
        )

        try:
            ok = self.engine.run(flow_key)
            if self.engine.children_running():
                BUS.log("배경에서 도는 플로우가 끝나기를 기다립니다", level="info")
                self.engine.join_children(timeout=10)
        finally:
            if self.engine is not None:
                self.engine.stop()  # 남은 비동기 플로우까지 정리
            self.running = False
            self.engine = None
            if self._watcher_owned_by_run:
                self.stop_watching()
                self._watcher_owned_by_run = False

        BUS.log("실행 완료" if ok else "실행이 실패 또는 중단으로 끝났습니다",
                level="info" if ok else "warn")
        self.finished.emit(flow_key, ok)
        return ok

    def run_multi(self, project) -> list[str]:
        """자동 시작으로 표시된 플로우들을 **동시에** 실행한다.

        각 플로우는 스레드에서 돌고, 하나뿐인 마우스·키보드는 우선순위대로 나눠 쓴다.
        """
        if self.running:
            return []

        from itda.engine.input import Win32Sender
        from itda.vision.coords import current_screens

        screens = current_screens()  # 모니터 정보는 GUI 스레드에서 미리 확보
        self.scheduler = MultiFlowScheduler(
            project, sender_factory=lambda: Win32Sender(screens=screens)
        )
        self._start_run_watcher(project)
        started = self.scheduler.start_all()
        if not started:
            self.scheduler = None
            return []

        self.running = True
        self.started.emit(", ".join(started))
        BUS.log(
            f"멀티 플로우 실행 — {len(started)}개 동시 실행. 멈추려면 F12", level="warn"
        )
        self._watch.start()
        return started

    def _check_scheduler(self) -> None:
        """스레드가 전부 끝났는지 지켜본다."""
        if self.scheduler is None:
            self._watch.stop()
            return
        self._drain_recovery_requests()
        if self.scheduler.any_running():
            return

        self._watch.stop()
        completed = self.scheduler.completed_slots()
        keys = ", ".join(slot.key for slot in completed)
        ok = bool(completed) and all(slot.last_ok for slot in completed)
        self.scheduler = None
        self.running = False
        if self._watcher_owned_by_run:
            self.stop_watching()
            self._watcher_owned_by_run = False
        BUS.log("멀티 플로우 실행이 끝났습니다", level="info")
        self.finished.emit(keys, ok)

    # ------------------------------------------------------------ 상황 감시

    def _start_run_watcher(self, project) -> None:
        """실행하는 동안 감시를 자동으로 켠다 (이미 켜져 있으면 그대로 둔다)."""
        self._watcher_owned_by_run = False
        if self.watching or not project.states.watcher.enabled:
            return
        if self.start_watching(project):
            self._watcher_owned_by_run = True
            self.watcher.on_unknown_timeout = self._run_recovery_flow

    def _run_recovery_flow(self, flow_key: str) -> None:
        """모르는 화면이 오래 이어질 때 복구 플로우를 부른다.

        감시 스레드에서 불리므로 직접 실행하지 않고 실행 엔진에 맡긴다 —
        입력 장치를 쥔 쪽이 처리해야 다른 동작과 부딪히지 않는다.
        """
        # 워처는 백그라운드 스레드이므로 실행 컨텍스트를 직접 호출하지 않는다.
        self._recovery_requests.put(flow_key)

    def _drain_recovery_requests(self) -> None:
        """워처가 보낸 복구 요청을 안전한 실행 지점에서 처리한다."""
        while True:
            try:
                flow_key = self._recovery_requests.get_nowait()
            except queue.Empty:
                return
            if self.scheduler is not None:
                priority = self.scheduler.max_active_priority() + 1
                self.scheduler.start_one(flow_key, priority=priority)
                continue
            engine = self.engine
            if engine is None or engine.ctx.run_flow is None:
                continue
            try:
                engine.ctx.run_flow(flow_key, {}, True)
            except Exception as e:
                BUS.log(f"복구 플로우 실행 실패: {type(e).__name__}: {e}", level="error")

    def start_watching(self, project) -> bool:
        """상황 감시를 켠다. 편집기에서도, 실행 중에도 쓴다."""
        from itda.engine.watcher import StateWatcher

        if self.watcher is not None and self.watcher.running:
            return True
        if not project.states.watcher.enabled:
            BUS.log("상황 감시가 꺼져 있습니다 (상황 관리에서 켜세요)", level="warn")
            return False

        self.watcher = StateWatcher(project)
        if not self.watcher.start():
            self.watcher = None
            return False
        return True

    def stop_watching(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None

    @property
    def watching(self) -> bool:
        return self.watcher is not None and self.watcher.running

    def stop(self) -> None:
        if self.engine is not None:
            self.engine.stop()
            BUS.log("정지 신호를 보냈습니다", level="warn")
        if self.scheduler is not None:
            self.scheduler.stop_all()
            BUS.log("모든 플로우에 정지 신호를 보냈습니다", level="warn")

    def _tick(self) -> None:
        """실행 중 GUI 를 살려 둔다 — 정지 버튼과 전역 단축키가 계속 동작하도록."""
        app = QApplication.instance()
        if self.hotkey.poll():
            self.stop()
        if app is not None:
            app.processEvents()
        self._drain_recovery_requests()
