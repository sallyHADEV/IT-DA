"""잇다(IT-DA)의 데이터 모델.

전부 평범한 데이터클래스이고 Qt 를 모른다. GUI 도, 2차의 실행 엔진도 같은 모델을 읽는다.
JSON 변환은 :mod:`itda.core.serde` 가 타입 힌트를 보고 자동으로 한다.

계층:
    Project ─┬─ Flow ─┬─ Node ── Action*      (노드 = 액션 시퀀스 컨테이너 = 모듈형 노드)
             │        └─ Edge
             ├─ ObjectRepo ── TargetObject*   (타겟 객체화 + 태그)
             └─ StateGraph ─┬─ State*         (상황 판단)
                            └─ Transition*    (상황 이동)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from itda.core.humanize import HumanProfile
from itda.core.ids import new_id
from itda.core.timing import Timing, TimingProfile

# ---------------------------------------------------------------- 공통 조각


@dataclass
class Retry:
    """실패 시 재시도 정책."""

    count: int = 0
    interval_ms: int = 500


@dataclass
class ErrorPolicy:
    """에러 발생 시 처리 방법 (예외 처리 기능)."""

    #: stop=플로우 중단 / continue=무시하고 다음 / goto=지정 노드로 / fail_port=fail 출구로 / raise_up=상위 플로우로 전파
    mode: str = "fail_port"
    #: mode 가 goto 일 때 이동할 노드 id
    target: str = ""
    #: 에러 시 경고음 재생
    beep: bool = False
    #: 로그에 남길 메시지
    message: str = ""
    #: 에러 순간 화면을 저장할지
    capture_screenshot: bool = False


@dataclass
class VarDecl:
    """변수 선언. 전역(프로젝트) 또는 플로우 지역."""

    name: str = ""
    type: str = "str"  # str | int | float | bool
    default: str = ""
    note: str = ""


@dataclass
class SearchRegion:
    """이미지 검색 / 캡처 범위."""

    #: full=전체화면 / rect=지정 사각형 / window=창 기준 / state_region=상태가 지정한 영역
    mode: str = "full"
    rect: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    window_title: str = ""


@dataclass
class MatchOptions:
    """템플릿 매칭 옵션."""

    #: None 이면 프로젝트 프로파일의 match_threshold 를 쓴다.
    threshold: float | None = None
    #: any=하나라도 찾으면 성공 / best=가장 점수 높은 것 / all=전부 찾아야 성공
    mode: str = "any"
    #: 배율 목록. 해상도가 다른 환경 대응.
    scales: list[float] = field(default_factory=lambda: [1.0])
    grayscale: bool = True


# ---------------------------------------------------------------- 액션


@dataclass
class Action:
    """노드 안에 들어가는 개별 동작.

    ``type`` 은 :mod:`itda.core.registry` 에 등록된 액션 타입 id 이고,
    ``params`` 의 구조는 그 타입이 선언한 :class:`~itda.core.schema.Field` 목록이 정한다.
    """

    id: str = field(default_factory=lambda: new_id("a"))
    type: str = "log"
    title: str = ""
    enabled: bool = True
    params: dict = field(default_factory=dict)
    timing: Timing = field(default_factory=Timing)
    #: 결과를 담을 변수 이름 (비우면 저장 안 함)
    out_var: str = ""
    note: str = ""


# ---------------------------------------------------------------- 노드 / 엣지


@dataclass
class Node:
    """플로우차트의 노드. 내부에 액션 시퀀스를 갖는 모듈이다."""

    id: str = field(default_factory=lambda: new_id("n"))
    #: start | action_group | branch | loop | subflow | state_gate | end
    type: str = "action_group"
    title: str = "새 노드"
    x: float = 0.0
    y: float = 0.0
    width: float = 190.0
    height: float = 78.0
    color: str = ""
    note: str = ""

    #: 이 노드를 실행하기 전에 만족해야 하는 상태 id. 비면 상태를 따지지 않는다.
    required_state: str = ""
    #: 상태가 맞지 않을 때: navigate=전이 경로로 이동 / wait=맞을 때까지 대기 / skip=건너뜀 / fail=실패 처리
    on_wrong_state: str = "navigate"
    #: 상태 이동/대기 제한시간
    state_timeout_ms: int = 10000

    pre: Timing = field(default_factory=Timing)
    post: Timing = field(default_factory=Timing)
    retry: Retry = field(default_factory=Retry)
    on_error: ErrorPolicy = field(default_factory=ErrorPolicy)

    #: 노드 타입 자체의 파라미터 (subflow 의 대상 플로우, loop 의 반복 횟수 등)
    params: dict = field(default_factory=dict)
    actions: list[Action] = field(default_factory=list)

    breakpoint: bool = False
    collapsed: bool = False

    def action(self, action_id: str) -> Action | None:
        return next((a for a in self.actions if a.id == action_id), None)

    def enabled_actions(self) -> list[Action]:
        return [a for a in self.actions if a.enabled]


@dataclass
class Edge:
    """노드 사이의 연결. ``src_port`` 는 ok/fail 같은 출구 이름이다."""

    id: str = field(default_factory=lambda: new_id("e"))
    src_node: str = ""
    src_port: str = "ok"
    dst_node: str = ""
    dst_port: str = "in"
    label: str = ""


@dataclass
class Flow:
    """플로우 하나 = 파일 하나. 그대로 다른 프로젝트에서 모듈로 불러올 수 있다."""

    id: str = field(default_factory=lambda: new_id("f"))
    name: str = "새 플로우"
    description: str = ""
    #: 이 플로우를 subflow 로 호출할 때 넘길 수 있는 입력 변수
    params: list[VarDecl] = field(default_factory=list)
    variables: list[VarDecl] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    # ---- 조회

    def node(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def edge(self, edge_id: str) -> Edge | None:
        return next((e for e in self.edges if e.id == edge_id), None)

    def start_node(self) -> Node | None:
        return next((n for n in self.nodes if n.type == "start"), None)

    def edges_from(self, node_id: str, port: str | None = None) -> list[Edge]:
        return [
            e
            for e in self.edges
            if e.src_node == node_id and (port is None or e.src_port == port)
        ]

    def edges_to(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.dst_node == node_id]

    # ---- 편집

    def add_node(self, node: Node) -> Node:
        self.nodes.append(node)
        return node

    def remove_node(self, node_id: str) -> tuple[Node | None, list[Edge]]:
        """노드와 거기 붙은 엣지를 함께 제거하고 되돌리기용으로 돌려준다."""
        node = self.node(node_id)
        if node is None:
            return None, []
        detached = [e for e in self.edges if node_id in (e.src_node, e.dst_node)]
        self.edges = [e for e in self.edges if e not in detached]
        self.nodes.remove(node)
        return node, detached

    def connect(self, src_node: str, src_port: str, dst_node: str, dst_port: str = "in") -> Edge | None:
        """엣지를 추가한다. 같은 연결이 이미 있으면 None."""
        for e in self.edges:
            if (e.src_node, e.src_port, e.dst_node) == (src_node, src_port, dst_node):
                return None
        edge = Edge(src_node=src_node, src_port=src_port, dst_node=dst_node, dst_port=dst_port)
        self.edges.append(edge)
        return edge

    def subflow_refs(self) -> list[str]:
        """이 플로우가 참조하는 다른 플로우 이름 목록 (순환 검사용)."""
        refs = []
        for n in self.nodes:
            if n.type == "subflow":
                target = n.params.get("flow", "")
                if target:
                    refs.append(target)
            for a in n.actions:
                if a.type == "run_flow":
                    target = a.params.get("flow", "")
                    if target:
                        refs.append(target)
        return refs


# ---------------------------------------------------------------- 객체 저장소


@dataclass
class TargetObject:
    """타겟을 객체화한 것. 이름 + 태그 + 이미지 여러 장.

    이미지를 여러 장 두는 이유는 "예외 상황이 많은 경우 여러 이미지를 한꺼번에 사용" 하기
    위해서다. 매칭은 :class:`MatchOptions` 의 mode 에 따라 any/best/all 로 동작한다.
    """

    id: str = field(default_factory=lambda: new_id("obj"))
    name: str = "새 객체"
    tags: list[str] = field(default_factory=list)
    #: 프로젝트 폴더 기준 상대경로 목록 (objects/img/*.png)
    images: list[str] = field(default_factory=list)
    match: MatchOptions = field(default_factory=MatchOptions)
    region: SearchRegion = field(default_factory=SearchRegion)
    #: 매칭 위치에서 실제 클릭 지점까지의 상대 오프셋
    anchor_dx: int = 0
    anchor_dy: int = 0
    note: str = ""


@dataclass
class ObjectRepo:
    objects: list[TargetObject] = field(default_factory=list)

    def get(self, object_id: str) -> TargetObject | None:
        return next((o for o in self.objects if o.id == object_id), None)

    def by_name(self, name: str) -> TargetObject | None:
        return next((o for o in self.objects if o.name == name), None)

    def all_tags(self) -> list[str]:
        tags: set[str] = set()
        for o in self.objects:
            tags.update(o.tags)
        return sorted(tags)

    def search(self, text: str = "", tags: list[str] | None = None) -> list[TargetObject]:
        """이름 부분일치 + 태그 AND 조건으로 거른다."""
        text = (text or "").strip().lower()
        want = set(tags or [])
        out = []
        for o in self.objects:
            if text and text not in o.name.lower():
                continue
            if want and not want.issubset(set(o.tags)):
                continue
            out.append(o)
        return out


# ---------------------------------------------------------------- 상태 (핵심)


@dataclass
class Condition:
    """상태 판정 조건 트리의 노드.

    ``op`` 가 leaf 이면 ``type`` + ``params`` 가 실제 검사이고,
    and/or/not 이면 ``items`` 가 자식이다.
    """

    op: str = "leaf"  # leaf | and | or | not
    #: leaf 일 때 등록된 조건 타입 id (object_visible, window_title, ocr_contains, ...)
    type: str = "object_visible"
    params: dict = field(default_factory=dict)
    items: list[Condition] = field(default_factory=list)
    negate: bool = False


@dataclass
class State:
    """타겟 프로그램의 한 가지 상황 (설정창, 편집메뉴, 출력메뉴 ...)."""

    id: str = field(default_factory=lambda: new_id("st"))
    name: str = "새 상태"
    #: 여러 상태가 동시에 참이면 priority 가 큰 쪽으로 판정한다.
    priority: int = 0
    #: 끼어드는 화면인가 (광고·업데이트 알림 같은 팝업).
    #: 참이면 언제 나타나든 최우선으로 처리하고, 닫은 뒤 원래 하던 일로 돌아간다.
    interrupt: bool = False
    condition: Condition = field(default_factory=lambda: Condition(op="and"))
    tags: list[str] = field(default_factory=list)
    color: str = "#4a7dbd"
    note: str = ""
    #: 상태 그래프 캔버스에서의 위치
    x: float = 0.0
    y: float = 0.0


@dataclass
class Transition:
    """상태 A → 상태 B 로 가기 위해 수행할 동작.

    실행 엔진은 이 간선들로 그래프를 만들고 최소 비용 경로를 찾아 "적합한 상황으로 이동"한다.
    """

    id: str = field(default_factory=lambda: new_id("tr"))
    src: str = ""
    dst: str = ""
    cost: float = 1.0
    actions: list[Action] = field(default_factory=list)
    #: 이동 후 목표 상태가 될 때까지 기다릴 시간
    settle_ms: int = 800
    note: str = ""

    def action(self, action_id: str) -> Action | None:
        """노드와 같은 방식으로 액션을 찾는다 (액션 목록 편집기가 공유된다)."""
        return next((a for a in self.actions if a.id == action_id), None)


@dataclass
class WatcherConfig:
    """상태를 주기적으로 판별하는 워처 설정."""

    enabled: bool = True
    interval_ms: int = 700
    region: SearchRegion = field(default_factory=SearchRegion)
    #: 어느 상태에도 해당하지 않을 때 붙일 이름
    unknown_name: str = "UNKNOWN"
    #: UNKNOWN 이 이 시간 이상 지속되면 복구 플로우를 돌린다 (0=사용 안 함)
    unknown_timeout_ms: int = 0
    recovery_flow: str = ""


@dataclass
class StateGraph:
    states: list[State] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    watcher: WatcherConfig = field(default_factory=WatcherConfig)

    def state(self, state_id: str) -> State | None:
        return next((s for s in self.states if s.id == state_id), None)

    def state_by_name(self, name: str) -> State | None:
        return next((s for s in self.states if s.name == name), None)

    def transitions_from(self, state_id: str) -> list[Transition]:
        return [t for t in self.transitions if t.src == state_id]

    def find_path(self, src: str, dst: str) -> list[Transition] | None:
        """src 상태에서 dst 상태까지의 최소 비용 경로. 없으면 None.

        간선 수가 많지 않으므로 다익스트라로 충분하다. 2차 실행 엔진이 그대로 쓴다.
        """
        if src == dst:
            return []
        import heapq

        best: dict[str, float] = {src: 0.0}
        heap: list[tuple[float, int, str, list[Transition]]] = [(0.0, 0, src, [])]
        counter = 0
        while heap:
            cost, _, node, path = heapq.heappop(heap)
            if node == dst:
                return path
            if cost > best.get(node, float("inf")):
                continue
            for t in self.transitions_from(node):
                nc = cost + max(0.0, t.cost)
                if nc < best.get(t.dst, float("inf")):
                    best[t.dst] = nc
                    counter += 1
                    heapq.heappush(heap, (nc, counter, t.dst, path + [t]))
        return None


# ---------------------------------------------------------------- 프로젝트


@dataclass
class FlowEntry:
    """멀티 플로우 실행 항목. 여러 매크로를 동시에 돌리고 우선순위를 준다."""

    flow: str = ""  # flows/ 아래 파일 이름 (확장자 제외)
    priority: int = 0  # 클수록 우선. 입력 장치 점유를 먼저 가져간다.
    autostart: bool = False
    loop: bool = False
    enabled: bool = True
    note: str = ""


@dataclass
class ProjectSettings:
    """project.json 에 저장되는 프로젝트 수준 설정."""

    name: str = "새 프로젝트"
    description: str = ""
    schema_version: int = 1
    timing: TimingProfile = field(default_factory=TimingProfile)
    #: 사람처럼 움직이기 설정 (마우스 궤적, 타이핑 리듬 …)
    human: HumanProfile = field(default_factory=HumanProfile)
    entries: list[FlowEntry] = field(default_factory=list)
    globals: list[VarDecl] = field(default_factory=list)
    #: 자동화 대상 창 (비면 전체 화면 기준)
    target_window: str = ""
    #: 실패 시 경고음 기본값
    beep_on_error: bool = True
