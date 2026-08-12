"""입력 장치 중재.

마우스와 키보드는 하나뿐이다. 여러 매크로가 동시에 돌면 서로의 클릭과 타이핑이 섞여
둘 다 망가진다. 그래서 **노드 단위로** 입력 권한을 빌려 쓴다.

* 단위가 노드인 이유: "클릭 → 문자 입력" 이 다른 플로우에 쪼개지면 엉뚱한 창에 글자가 들어간다.
* 우선순위가 높은 플로우가 먼저 가져간다. 같으면 먼저 기다린 쪽이 먼저다(굶지 않게).
* 실행 중인 쪽을 중간에 뺏지는 않는다. 대신 다음 차례를 우선순위로 정한다.
* 오래 쥐고 놓지 않으면(버그·멈춤) 감시 시간이 지나 강제로 회수한다. 기준은 "쥐고 있은
  시간" 이 아니라 **"살아 있다고 마지막으로 알린 뒤 지난 시간"** 이다(:meth:`InputArbiter.touch`).
  시간만 재면 이미지를 60초 기다리는 정상 노드를 멈춘 것으로 오해해, 노드가 실행 중인데
  남이 입력을 가져가 둘이 동시에 주입한다.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Holder:
    owner: str
    priority: int
    since: float

    def held_ms(self) -> float:
        return (time.perf_counter() - self.since) * 1000


class InputArbiter:
    """우선순위 기반 입력 권한 뮤텍스."""

    def __init__(self, max_hold_ms: int = 30000) -> None:
        self._condition = threading.Condition()
        self._holder: Holder | None = None
        self._waiting: dict[str, tuple[int, int]] = {}  # owner -> (priority, 도착 순번)
        self._cancelled: set[str] = set()
        self._ticket = itertools.count()
        self.max_hold_ms = max_hold_ms
        #: 강제 회수 횟수 (진단용)
        self.forced_releases = 0

    # ------------------------------------------------------------

    @property
    def owner(self) -> str | None:
        with self._condition:
            return self._holder.owner if self._holder else None

    def acquire(self, owner: str, priority: int = 0, timeout_ms: int = 15000) -> bool:
        """입력 권한을 얻는다. 이미 자신이 쥐고 있으면 곧바로 성공한다."""
        acquired, _ = self._acquire(owner, priority, timeout_ms)
        return acquired

    def _acquire(self, owner: str, priority: int, timeout_ms: int) -> tuple[bool, bool]:
        """``(획득 성공, 재진입이었는가)`` 를 한 번의 잠금 안에서 원자적으로 낸다.

        ``_Hold`` 가 "재진입인가" 를 이 함수 **바깥**에서 먼저 확인하고 나중에 이 함수를
        부르면, 그 사이(락이 풀려 있는 틈)에 다른 스레드가 같은 이름으로 놓았다 다시 잡을
        수 있다 — 그러면 재진입 여부 판정이 낡아져서, `__exit__` 가 새로 잡은 락을 재진입인
        줄 알고 놓지 않는다(락이 영영 안 풀린다). 판정과 획득을 같은 잠금 구간에 묶어 없앤다.
        """
        deadline = time.perf_counter() + max(0, timeout_ms) / 1000
        with self._condition:
            if owner in self._cancelled:
                return False, False
            self._cancelled.discard(owner)
            if self._holder is not None and self._holder.owner == owner:
                return True, True  # 재진입 허용 (노드 안에서 중첩 호출)

            self._waiting[owner] = (priority, next(self._ticket))
            try:
                while True:
                    if owner in self._cancelled:
                        return False, False
                    self._reclaim_if_stuck()
                    if self._holder is None and self._is_next(owner):
                        self._holder = Holder(owner, priority, time.perf_counter())
                        return True, False
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        return False, False
                    self._condition.wait(min(0.05, remaining))
            finally:
                self._waiting.pop(owner, None)

    def touch(self, owner: str) -> None:
        """보유자가 아직 살아 움직인다고 알려 강제 회수 시계를 되감는다.

        회수(:meth:`_reclaim_if_stuck`)는 **멈춘 플로우**를 구제하려는 장치인데, 시간만
        재면 "이미지를 60초 기다리는 중인 정상 노드" 와 구분이 안 된다. 그대로 두면 노드가
        아직 실행 중인데 남이 입력을 가져가 둘이 동시에 주입한다. 그래서 실행이 살아 있음을
        스스로 알리게 하고, 회수는 **알림이 끊긴** 보유자에게만 건다.
        """
        with self._condition:
            if self._holder is not None and self._holder.owner == owner:
                self._holder = Holder(owner, self._holder.priority, time.perf_counter())

    def release(self, owner: str) -> None:
        with self._condition:
            if self._holder is not None and self._holder.owner == owner:
                self._holder = None
                self._condition.notify_all()

    def cancel(self, owner: str) -> None:
        """대기 중인 소유자의 입력 대기를 깨운다."""
        with self._condition:
            self._cancelled.add(owner)
            self._waiting.pop(owner, None)
            self._condition.notify_all()

    def arm(self, owner: str) -> None:
        """새 실행을 시작할 때 이전 정지 표시를 지운다."""
        with self._condition:
            self._cancelled.discard(owner)

    def hold(self, owner: str, priority: int = 0, timeout_ms: int = 15000):
        """``with arbiter.hold(...)`` 로 쓰는 컨텍스트 매니저."""
        return _Hold(self, owner, priority, timeout_ms)

    def reset(self) -> None:
        with self._condition:
            self._holder = None
            self._waiting.clear()
            self._cancelled.clear()
            self._condition.notify_all()

    # ------------------------------------------------------------

    def _is_next(self, owner: str) -> bool:
        """대기자 중 내 차례인가. 우선순위 내림차순, 그다음 도착 순."""
        mine = self._waiting.get(owner)
        if mine is None:
            return True
        my_priority, my_ticket = mine
        for other, (priority, ticket) in self._waiting.items():
            if other == owner:
                continue
            if (priority, -ticket) > (my_priority, -my_ticket):
                return False
        return True

    def _reclaim_if_stuck(self) -> None:
        """소식이 끊긴 지 오래면 회수한다. 한 플로우가 멈춰도 나머지가 계속 돌게.

        기준은 "쥐고 있은 시간" 이 아니라 "마지막으로 살아 있다고 알린 뒤 지난 시간" 이다
        (:meth:`touch`). 정상적으로 오래 기다리는 노드를 멈춘 것으로 오해하지 않는다.
        """
        if self._holder is None or self.max_hold_ms <= 0:
            return
        if self._holder.held_ms() > self.max_hold_ms:
            self.forced_releases += 1
            self._holder = None
            self._condition.notify_all()


class _Hold:
    def __init__(self, arbiter: InputArbiter, owner: str, priority: int, timeout_ms: int) -> None:
        self.arbiter = arbiter
        self.owner = owner
        self.priority = priority
        self.timeout_ms = timeout_ms
        self.acquired = False
        #: 이미 쥐고 있던 경우 — 나갈 때 놓지 않는다(중첩 안전)
        self.reentrant = False

    def __enter__(self) -> bool:
        self.acquired, self.reentrant = self.arbiter._acquire(
            self.owner, self.priority, self.timeout_ms
        )
        return self.acquired

    def __exit__(self, *_exc) -> None:
        if self.acquired and not self.reentrant:
            self.arbiter.release(self.owner)
