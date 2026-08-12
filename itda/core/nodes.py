"""기본 노드 타입 정의.

노드는 그 자체로 "모듈"이다. 대부분의 노드는 내부에 액션 시퀀스를 담고, 그래프는 노드 사이의
흐름과 상태 조건만 표현한다. 반복은 loop 노드 내부에서 처리하거나, 그래프에서 이전 노드로
엣지를 되돌려 만든다.
"""

from __future__ import annotations

from itda.core.registry import NodeType, register_node
from itda.core.schema import Field
from itda.core.window_spec import window_params


def _switch_ports(params: dict) -> list[str]:
    raw = str(params.get("cases", "") or "")
    cases = [c.strip() for c in raw.split(",") if c.strip()]
    return cases + ["default"]


START = register_node(
    NodeType(
        id="start",
        label="시작",
        color="#4fa98a",
        icon="▶",
        help="플로우의 진입점. 플로우당 하나만 둘 수 있습니다.",
        in_ports=[],
        out_ports=["ok"],
        allows_actions=False,
        allows_state=False,
        unique=True,
    )
)

ACTION_GROUP = register_node(
    NodeType(
        id="action_group",
        label="동작",
        color="#4a6fa5",
        icon="▤",
        help="여러 액션을 순서대로 실행하는 기본 노드입니다.",
        out_ports=["ok", "fail"],
    )
)

BRANCH = register_node(
    NodeType(
        id="branch",
        label="분기",
        color="#c98a4b",
        icon="◇",
        help="내부 액션을 먼저 실행한 뒤 조건식으로 참/거짓 출구를 고릅니다.",
        out_ports=["true", "false"],
        params=[
            Field("expr", "expr", "조건식", "", help="예: found == True 또는 count > 3"),
        ],
    )
)

SWITCH = register_node(
    NodeType(
        id="switch",
        label="다중 분기",
        color="#b57b45",
        icon="⋔",
        help="식의 결과 문자열과 같은 이름의 출구로 나갑니다. 없으면 default.",
        out_ports=["default"],
        params=[
            Field("expr", "expr", "판정식", ""),
            Field("cases", "str", "출구 목록", "", help="쉼표로 구분. 예: 성공, 재시도, 취소"),
        ],
        dynamic_out=_switch_ports,
    )
)

LOOP = register_node(
    NodeType(
        id="loop",
        label="반복",
        color="#7a6ba8",
        icon="↻",
        help="내부 액션 시퀀스를 조건에 따라 반복합니다.",
        out_ports=["ok", "fail"],
        params=[
            Field(
                "mode",
                "enum",
                "반복 방식",
                "count",
                options=[
                    ("count", "지정 횟수"),
                    ("while", "조건이 참인 동안"),
                    ("until", "조건이 참이 될 때까지"),
                    ("forever", "무한 (중단 조건은 내부 액션에서)"),
                ],
            ),
            Field("count", "int", "횟수", 3, minimum=1, maximum=100000,
                  depends_on=("mode", "count")),
            Field("expr", "expr", "조건식", "", depends_on=("mode", ("while", "until"))),
            Field("max_iterations", "int", "최대 반복(안전장치)", 1000, minimum=1, maximum=1000000),
            Field("interval_ms", "int", "반복 간격", 0, minimum=0, maximum=600000, suffix=" ms"),
        ],
    )
)

SUBFLOW = register_node(
    NodeType(
        id="subflow",
        label="플로우 호출",
        color="#3f8f8f",
        icon="⧉",
        help="파일로 만들어진 다른 플로우를 모듈처럼 불러 실행합니다.",
        out_ports=["ok", "fail"],
        allows_actions=False,
        params=[
            Field("flow", "flow_ref", "대상 플로우", ""),
            Field("args", "text", "인자 (name=value 줄단위)", ""),
            Field("wait", "bool", "끝날 때까지 대기", True,
                  help="끄면 배경에서 돌리고 곧바로 다음 노드로 넘어갑니다."),
            Field("priority", "int", "우선순위(비동기일 때)", 0, minimum=-10, maximum=10,
                  depends_on=("wait", False),
                  help="배경에서 도는 플로우가 마우스·키보드를 가져가는 순서입니다."),
        ],
    )
)

STATE_GATE = register_node(
    NodeType(
        id="state_gate",
        label="상황 이동",
        color="#ee7f63",
        icon="⚑",
        help="타겟 프로그램을 지정한 상황(화면)으로 이동시키거나, 그 상황이 될 때까지 기다립니다.",
        out_ports=["ok", "fail"],
        allows_actions=False,
        allows_state=False,
        params=[
            Field("target_state", "state_ref", "목표 상황", ""),
            Field(
                "mode",
                "enum",
                "방식",
                "navigate",
                options=[
                    ("navigate", "전이 경로를 따라 이동"),
                    ("wait", "그 상황이 될 때까지 대기"),
                    ("check", "확인만 (아니면 fail)"),
                ],
            ),
            Field("timeout_ms", "int", "제한시간", 10000, minimum=0, maximum=600000, suffix=" ms"),
        ],
    )
)

WINDOW = register_node(
    NodeType(
        id="window",
        label="창 맞추기",
        color="#5b7fa8",
        icon="▭",
        help=(
            "대상 창을 정해진 위치·크기로 맞춥니다. 창 크기가 매번 달라지면 좌표와 이미지 "
            "검색이 어긋나므로, 보통 플로우 맨 앞에 둡니다."
        ),
        out_ports=["ok", "fail"],
        allows_actions=False,
        allows_state=False,
        params=window_params(),
    )
)

END = register_node(
    NodeType(
        id="end",
        label="종료",
        color="#6b7383",
        icon="■",
        help="플로우를 끝냅니다.",
        out_ports=[],
        allows_actions=False,
        allows_state=False,
        params=[
            Field(
                "result",
                "enum",
                "결과",
                "success",
                options=[("success", "성공"), ("fail", "실패"), ("stop_all", "전체 중단")],
            ),
        ],
    )
)

NOTE = register_node(
    NodeType(
        id="note",
        label="메모",
        color="#71766b",
        icon="✎",
        help="설명을 적어두는 장식 노드입니다. 실행되지 않습니다.",
        in_ports=[],
        out_ports=[],
        allows_actions=False,
        allows_state=False,
        params=[Field("text", "text", "내용", "")],
    )
)
