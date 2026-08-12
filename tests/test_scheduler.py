"""입력 중재기 + 멀티 플로우 스케줄러 테스트."""

from __future__ import annotations

import threading
import time

import pytest

from itda.core.model import Action, FlowEntry, Node
from itda.engine.arbiter import InputArbiter
from itda.engine.scheduler import MultiFlowScheduler


# ---------------------------------------------------------------- 중재기 — 심장박동
#
# 강제 회수는 **멈춘 플로우**를 구제하려는 장치인데, 쥐고 있은 시간만 재면 "이미지를 60초
# 기다리는 중인 정상 노드" 와 구분이 안 됐다. 그래서 노드가 아직 실행 중인데 남이 입력을
# 가져가 둘이 동시에 주입할 수 있었다.


#: 회수 기준(60ms)보다 길게 노려보되, 박동이 이어지는 동안 끝나도록 잡는다.
STEAL_TIMEOUT_MS = 200
BEAT_ROUNDS = 12  # 30ms * 12 = 360ms — 도둑이 포기한 뒤까지 계속 뛴다


def _steal_attempt(arbiter, beat: str | None) -> bool:
    """다른 스레드가 잠금을 노리는 동안 ``beat`` 이름으로 심장박동을 보낸다.

    두 가지를 지켜야 의미 있는 검사가 된다.

    1. 회수는 ``acquire()`` **안에서만** 검사된다. ``arbiter.owner`` 만 읽으면 회수가
       아예 발동하지 않아 심장박동이 없어도 통과해 버린다 — 실제로 그렇게 틀린 적이 있다.
    2. 도둑이 기다리는 내내 박동이 이어져야 한다. 중간에 박동을 끊으면 그 뒤에 회수가
       걸려서, 고쳐 놓고도 실패한다(이것도 실제로 겪었다). 실행 중인 노드는 잠금을 놓을
       때까지 계속 뛰므로 그 상황을 그대로 흉내 낸다.
    """
    stolen: list[str] = []

    def intruder():
        if arbiter.acquire("침입플로우", 0, timeout_ms=STEAL_TIMEOUT_MS):
            stolen.append("침입플로우")

    thief = threading.Thread(target=intruder)
    thief.start()
    for _ in range(BEAT_ROUNDS):
        time.sleep(0.03)
        if beat:
            arbiter.touch(beat)
    thief.join(timeout=2)
    return bool(stolen)


def test_a_working_holder_is_not_reclaimed():
    """살아 있다고 알리는 동안에는 회수되지 않는다."""
    arbiter = InputArbiter(max_hold_ms=60)
    arbiter.acquire("느린플로우", 0)

    assert _steal_attempt(arbiter, beat="느린플로우") is False
    assert arbiter.owner == "느린플로우"


def test_a_silent_holder_is_still_reclaimed():
    """알림이 끊기면 예정대로 회수한다 — 이게 이 장치의 본래 목적이다."""
    arbiter = InputArbiter(max_hold_ms=60)
    arbiter.acquire("멈춘플로우", 0)

    time.sleep(0.12)  # 아무 알림 없이 가만히

    assert arbiter.acquire("다음플로우", 0, timeout_ms=500) is True
    assert arbiter.forced_releases == 1


def test_touch_from_a_non_holder_is_ignored():
    """남의 잠금 시계를 되감아 주면 멈춘 플로우가 영영 안 풀린다."""
    arbiter = InputArbiter(max_hold_ms=60)
    arbiter.acquire("멈춘플로우", 0)

    assert _steal_attempt(arbiter, beat="엉뚱한플로우") is True


def test_check_stop_sends_the_heartbeat_for_the_node_that_holds_input():
    """러너가 알려 준 이름으로만 심장박동이 나가야 한다."""
    from itda.engine.context import ExecutionContext

    arbiter = InputArbiter(max_hold_ms=60)
    arbiter.acquire("main", 0)
    ctx = ExecutionContext(project=None, arbiter=arbiter, arbiter_owner="main")

    stolen: list[str] = []

    def intruder():
        if arbiter.acquire("침입플로우", 0, timeout_ms=STEAL_TIMEOUT_MS):
            stolen.append("침입플로우")

    thief = threading.Thread(target=intruder)
    thief.start()
    for _ in range(BEAT_ROUNDS):
        time.sleep(0.03)
        ctx.check_stop()  # 폴링 루프가 매 회차 부르는 그 지점
    thief.join(timeout=2)

    assert not stolen
    assert arbiter.owner == "main"


def test_check_stop_without_a_recorded_owner_does_not_touch_anything():
    """잠금을 안 쥔 상태(노드 밖)에서는 아무 시계도 건드리지 않는다."""
    from itda.engine.context import ExecutionContext

    arbiter = InputArbiter(max_hold_ms=60)
    arbiter.acquire("멈춘플로우", 0)
    ctx = ExecutionContext(project=None, arbiter=arbiter)  # arbiter_owner 비어 있음

    stolen: list[str] = []

    def intruder():
        if arbiter.acquire("침입플로우", 0, timeout_ms=STEAL_TIMEOUT_MS):
            stolen.append("침입플로우")

    thief = threading.Thread(target=intruder)
    thief.start()
    for _ in range(BEAT_ROUNDS):
        time.sleep(0.03)
        ctx.check_stop()
    thief.join(timeout=2)

    assert stolen == ["침입플로우"]  # 멈춘 것으로 보고 예정대로 회수됐다


# ---------------------------------------------------------------- 중재기 — 재진입 원자성
#
# `_Hold.__enter__` 는 예전엔 "재진입인가" 를 락 밖에서 먼저 읽고, 그 다음 락 안에서
# `acquire()` 를 별도로 불렀다. 그 사이(락이 풀린 틈)에 바깥 스코프가 놓았다가 같은 이름으로
# 다시 잡히면, 방금 새로 잡은(재진입이 아닌) 락인데도 "재진입" 이라고 낡은 판정을 그대로
# 믿어서 `__exit__` 가 놓지 않는다 — 락이 영영 안 풀린다.
#
# 이 경합은 실제 스레드 타이밍으로는 400회를 돌려도 재현이 안 됐다(GIL 때문에 그 틈이 너무
# 좁다). 그래서 타이밍에 기대지 않고, 문제였던 "순서" 자체를 그대로 재현해 결정론적으로
# 검증한다.


def test_the_old_check_then_acquire_order_would_have_gone_stale():
    """예전 순서(락 밖에서 owner 확인 → 나중에 acquire)를 그대로 밟으면 판정이 낡는다.

    지금 `_Hold` 는 이 순서를 쓰지 않는다 — 이 테스트는 왜 그 순서가 틀렸는지를 보여준다.
    """
    arbiter = InputArbiter()
    arbiter.acquire("X", 0)  # 바깥 스코프가 이미 쥐고 있다고 하자

    stale_reentrant = arbiter.owner == "X"  # (예전) 1단계 — 락 밖에서 미리 확인
    arbiter.release("X")  # 그 사이 바깥 스코프가 끝나 놓아 버렸다
    acquired = arbiter.acquire("X", 0)  # (예전) 2단계 — 사실은 새로 잡은 것, 재진입이 아니다

    assert stale_reentrant is True  # 낡은 판정: 재진입이라 잘못 믿는다
    assert acquired is True  # 하지만 방금 잡은 건 유일한 보유다
    # __exit__ 가 stale_reentrant 를 믿었다면 release 를 건너뛰어 락이 영영 안 풀렸을 것이다


def test_acquire_decides_reentrant_atomically():
    """``_acquire`` 는 재진입 여부와 획득을 같은 잠금 구간 안에서 함께 정한다."""
    arbiter = InputArbiter()
    arbiter.acquire("X", 0)

    acquired, reentrant = arbiter._acquire("X", 0, 1000)
    assert (acquired, reentrant) == (True, True)  # 진짜로 아직 쥐고 있으니 맞는 판정

    arbiter.release("X")
    acquired, reentrant = arbiter._acquire("X", 0, 1000)
    assert (acquired, reentrant) == (True, False)  # 방금 새로 잡은 것 — 재진입이 아니다


def test_hold_releases_a_fresh_acquisition_even_when_the_owner_name_repeats():
    """이름이 같아도, 진짜로 새로 잡은 락이면 나갈 때 반드시 놓아야 한다."""
    arbiter = InputArbiter()
    arbiter.acquire("X", 0)
    arbiter.release("X")  # 바깥 스코프는 이미 끝났다 — 다음 hold는 재진입이 아니다

    with arbiter.hold("X", 0):
        pass

    assert arbiter.owner is None


def test_hold_does_not_release_a_truly_nested_hold():
    arbiter = InputArbiter()
    with arbiter.hold("X", 0):
        with arbiter.hold("X", 0):
            pass
        assert arbiter.owner == "X"  # 안쪽이 나가도 바깥은 아직 쥐고 있다
    assert arbiter.owner is None


def test_hold_enter_decides_in_a_single_call(monkeypatch):
    """``_Hold.__enter__`` 는 재진입 판정과 획득을 한 번의 호출로 묶어야 한다.

    예전처럼 ``owner`` 를 먼저 읽고 나중에 ``acquire()`` 를 따로 부르면, 그 사이(락이
    풀린 틈)가 곧 경합 창이다. 몇 번 호출하는지를 스파이로 확인한다.
    """
    arbiter = InputArbiter()
    calls = []

    real_acquire = InputArbiter._acquire

    def spy_acquire(self, *args, **kwargs):
        calls.append("_acquire")
        return real_acquire(self, *args, **kwargs)

    owner_getter = InputArbiter.owner.fget

    def spy_owner(self):
        calls.append("owner")
        return owner_getter(self)

    monkeypatch.setattr(InputArbiter, "_acquire", spy_acquire)
    monkeypatch.setattr(InputArbiter, "owner", property(spy_owner))

    with arbiter.hold("A", 0):
        pass

    assert calls == ["_acquire"]  # owner 를 따로 읽지 않는다 — 판정이 한 곳에서만 이뤄진다


# ---------------------------------------------------------------- 중재기


def test_single_owner_at_a_time():
    arbiter = InputArbiter()
    assert arbiter.acquire("A", 0) is True
    assert arbiter.owner == "A"

    assert arbiter.acquire("B", 0, timeout_ms=50) is False  # A 가 쥐고 있다

    arbiter.release("A")
    assert arbiter.acquire("B", 0, timeout_ms=200) is True


def test_reentrant_for_the_same_owner():
    arbiter = InputArbiter()
    arbiter.acquire("A", 0)
    assert arbiter.acquire("A", 0, timeout_ms=10) is True  # 자기 자신은 곧바로


def test_release_by_a_non_owner_is_ignored():
    arbiter = InputArbiter()
    arbiter.acquire("A", 0)
    arbiter.release("B")
    assert arbiter.owner == "A"


def test_higher_priority_goes_first():
    """A 가 놓는 순간, 기다리던 셋 중 우선순위가 가장 높은 쪽이 가져간다."""
    arbiter = InputArbiter()
    arbiter.acquire("A", 0)

    granted: list[str] = []
    barrier = threading.Barrier(4)

    def waiter(name: str, priority: int) -> None:
        barrier.wait()
        if arbiter.acquire(name, priority, timeout_ms=3000):
            granted.append(name)
            time.sleep(0.02)
            arbiter.release(name)

    threads = [
        threading.Thread(target=waiter, args=("낮음", 1)),
        threading.Thread(target=waiter, args=("높음", 9)),
        threading.Thread(target=waiter, args=("중간", 5)),
    ]
    for t in threads:
        t.start()
    barrier.wait()
    time.sleep(0.1)  # 셋 다 대기열에 들어갈 시간
    arbiter.release("A")
    for t in threads:
        t.join(3)

    assert granted[0] == "높음"
    assert set(granted) == {"높음", "중간", "낮음"}


def test_equal_priority_is_first_come_first_served():
    arbiter = InputArbiter()
    arbiter.acquire("A", 0)

    granted: list[str] = []

    def waiter(name: str) -> None:
        if arbiter.acquire(name, 5, timeout_ms=3000):
            granted.append(name)
            arbiter.release(name)

    first = threading.Thread(target=waiter, args=("먼저",))
    first.start()
    time.sleep(0.08)  # '먼저' 가 확실히 먼저 줄을 선다
    second = threading.Thread(target=waiter, args=("나중",))
    second.start()

    time.sleep(0.05)
    arbiter.release("A")
    first.join(3)
    second.join(3)

    assert granted == ["먼저", "나중"]


def test_stuck_holder_is_reclaimed():
    """한 플로우가 멈춰도 나머지가 굶지 않는다."""
    arbiter = InputArbiter(max_hold_ms=60)
    arbiter.acquire("멈춘것", 0)

    assert arbiter.acquire("다음것", 0, timeout_ms=1000) is True
    assert arbiter.forced_releases == 1


def test_hold_context_manager_releases():
    arbiter = InputArbiter()
    with arbiter.hold("A", 0) as granted:
        assert granted is True
        assert arbiter.owner == "A"
    assert arbiter.owner is None


def test_nested_hold_keeps_the_outer_lock():
    arbiter = InputArbiter()
    with arbiter.hold("A", 0):
        with arbiter.hold("A", 0):
            pass
        assert arbiter.owner == "A"  # 안쪽이 끝나도 유지된다
    assert arbiter.owner is None


def test_reset_clears_everything():
    arbiter = InputArbiter()
    arbiter.acquire("A", 0)
    arbiter.reset()
    assert arbiter.owner is None


# ---------------------------------------------------------------- 스케줄러


@pytest.fixture
def two_flows(project):
    """빠르게 끝나는 플로우 두 개."""
    project.settings.timing.default_pre_ms = 0
    project.settings.timing.default_post_ms = 0
    project.settings.human.enabled = False

    def fill(flow, text: str) -> None:
        flow.nodes = [n for n in flow.nodes if n.type == "start"]
        flow.edges = []
        start = flow.start_node()
        node = flow.add_node(
            Node(type="action_group", title="작업",
                 actions=[Action(type="type_text", params={"text": text})])
        )
        flow.connect(start.id, "ok", node.id)

    fill(project.flow("main"), "M")
    key, second = project.add_flow("보조")
    fill(second, "S")

    project.settings.entries = [
        FlowEntry(flow="main", priority=5, autostart=True),
        FlowEntry(flow=key, priority=1, autostart=True),
    ]
    return project, key


def test_starts_autostart_flows(two_flows):
    project, key = two_flows
    scheduler = MultiFlowScheduler(project)

    started = scheduler.start_all()
    scheduler.join(5)

    assert set(started) == {"main", key}
    completed = scheduler.completed_slots()
    assert all(slot.runs >= 1 for slot in completed)
    assert all(slot.last_ok for slot in completed)


def test_disabled_entries_are_skipped(two_flows):
    project, key = two_flows
    project.settings.entries[1].enabled = False
    scheduler = MultiFlowScheduler(project)

    started = scheduler.start_all()
    scheduler.join(5)

    assert started == ["main"]


def test_entries_are_ordered_by_priority(two_flows):
    project, key = two_flows
    scheduler = MultiFlowScheduler(project)
    assert [e.flow for e in scheduler.entries()] == ["main", key]


def test_flows_do_not_interleave_within_a_node(two_flows):
    """입력이 섞이면 'MS' 처럼 뒤엉킨다. 노드 단위로 권한을 빌리므로 그럴 수 없다."""
    project, key = two_flows
    for flow_key in ("main", key):
        flow = project.flow(flow_key)
        node = flow.nodes[1]
        letter = "M" if flow_key == "main" else "S"
        node.actions = [
            Action(type="type_text", params={"text": letter * 3, "interval_ms": 1})
        ]

    scheduler = MultiFlowScheduler(project)
    scheduler.start_all()
    scheduler.join(5)

    for slot in scheduler.completed_slots():
        typed = slot.engine.ctx.sender.text()
        assert typed in ("MMM", "SSS")


def test_stop_ends_a_looping_flow(project):
    project.settings.timing.default_pre_ms = 0
    project.settings.timing.default_post_ms = 0
    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()
    node = flow.add_node(
        Node(type="action_group", title="짧은 작업",
             actions=[Action(type="sleep", params={"ms": 5, "jitter_pct": 0})])
    )
    flow.connect(start.id, "ok", node.id)
    project.settings.entries = [FlowEntry(flow="main", priority=0, autostart=True, loop=True)]

    scheduler = MultiFlowScheduler(project, loop_interval_ms=10)
    scheduler.start_all()
    time.sleep(0.2)
    assert scheduler.any_running()

    scheduler.stop_all()

    assert scheduler.join(5) is True
    assert next(slot for slot in scheduler.completed_slots() if slot.key == "main").runs >= 1


def test_missing_flow_does_not_start(project):
    scheduler = MultiFlowScheduler(project)
    assert scheduler.start(FlowEntry(flow="없는것")) is False


def test_start_one_adds_an_ad_hoc_entry(two_flows):
    project, key = two_flows
    project.settings.entries = []
    scheduler = MultiFlowScheduler(project)

    assert scheduler.start_one("main", priority=3) is True
    scheduler.join(5)
    assert next(slot for slot in scheduler.completed_slots() if slot.key == "main").entry.priority == 3


def test_describe_reports_state(two_flows):
    project, key = two_flows
    scheduler = MultiFlowScheduler(project)
    assert "없음" in scheduler.describe()

    scheduler.start_all()
    scheduler.join(5)

    assert "없음" in scheduler.describe()


def test_arbiter_is_released_even_if_a_flow_fails(project):
    """실행 중 실패해도 입력 권한이 잠긴 채로 남으면 안 된다."""
    project.settings.timing.default_pre_ms = 0
    project.settings.timing.default_post_ms = 0
    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()
    node = flow.add_node(
        Node(type="action_group", title="실패",
             actions=[Action(type="image_search", params={"objects": ["없는객체"]})])
    )
    flow.connect(start.id, "ok", node.id)
    project.settings.entries = [FlowEntry(flow="main", autostart=True)]

    scheduler = MultiFlowScheduler(project)
    scheduler.start_all()
    scheduler.join(5)

    assert scheduler.arbiter.owner is None
