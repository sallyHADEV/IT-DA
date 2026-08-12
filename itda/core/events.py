"""실행 이벤트 버스.

실행 엔진(2차)은 GUI 를 모른다. 대신 이 버스에 이벤트만 흘리고, 캔버스·로그 패널·변수
워치·상태 배지가 각자 구독한다. 1차에서는 데모 재생기가 같은 버스에 가짜 이벤트를 넣어
시각화 경로를 미리 검증한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, pyqtSignal

# 노드 실행 상태
IDLE = "idle"
PENDING = "pending"
RUNNING = "running"
OK = "ok"
FAIL = "fail"
SKIPPED = "skipped"
BREAK = "break"

STATUS_LABELS = {
    IDLE: "대기",
    PENDING: "예약",
    RUNNING: "실행 중",
    OK: "성공",
    FAIL: "실패",
    SKIPPED: "건너뜀",
    BREAK: "중단점",
}


@dataclass
class LogRecord:
    level: str = "info"  # debug | info | warn | error
    message: str = ""
    flow: str = ""
    node: str = ""
    action: str = ""
    ts: float = field(default_factory=time.time)

    def time_text(self) -> str:
        lt = time.localtime(self.ts)
        return f"{lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}.{int(self.ts % 1 * 1000):03d}"


class EventBus(QObject):
    """앱 전체가 공유하는 단일 인스턴스."""

    #: 로그 한 줄
    logged = pyqtSignal(object)  # LogRecord
    #: (플로우 이름, 노드 id, 상태)
    node_status = pyqtSignal(str, str, str)
    #: (플로우 이름, 엣지 id) — 흐름이 지나갈 때 반짝임
    edge_fired = pyqtSignal(str, str)
    #: (플로우 이름, 노드 id, 액션 id, 상태)
    action_status = pyqtSignal(str, str, str, str)
    #: (플로우 이름, 변수 스냅샷)
    variables = pyqtSignal(str, dict)
    #: (상태 id, 상태 이름) — 워처가 현재 상황을 판정할 때마다
    state_detected = pyqtSignal(str, str)
    #: (플로우 이름, 실행 여부)
    flow_running = pyqtSignal(str, bool)

    def log(self, message: str, level: str = "info", flow: str = "", node: str = "", action: str = "") -> None:
        self.logged.emit(LogRecord(level=level, message=message, flow=flow, node=node, action=action))


#: 전역 버스. GUI 와 엔진 모두 이걸 쓴다.
BUS = EventBus()
