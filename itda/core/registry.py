"""액션 / 노드 / 조건 타입 레지스트리.

새 동작을 추가하는 방법은 하나뿐이다: 클래스를 만들고 ``@register_action`` 을 붙인다.
그러면 팔레트에 뜨고, 속성 폼이 자동 생성되고, 저장/로드도 된다. GUI 코드는 건드리지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from itda.core.schema import Field, coerce, defaults_for

# ---------------------------------------------------------------- 액션


class ActionType:
    """액션 타입의 베이스.

    클래스 속성만으로 에디터가 필요한 정보를 전부 얻는다. ``execute`` 는 2차(실행 엔진)에서
    채운다 — 1차에서는 스키마와 요약만 있으면 에디터가 완성된다.
    """

    ID: str = ""
    LABEL: str = ""
    CATEGORY: str = "기타"
    COLOR: str = "#7a8ba6"
    ICON: str = "•"
    HELP: str = ""
    PARAMS: list[Field] = []
    #: 결과를 변수에 담을 수 있는 액션인지 (속성 패널의 out_var 칸 표시 여부)
    HAS_OUTPUT: bool = False

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return defaults_for(cls.PARAMS)

    @classmethod
    def summary(cls, params: dict[str, Any]) -> str:
        """액션 목록에 한 줄로 보여줄 요약. 하위 클래스에서 덮어쓴다."""
        return cls.LABEL

    def execute(self, action, ctx):  # pragma: no cover - 2차에서 구현
        raise NotImplementedError(f"{self.ID} 액션은 아직 실행부가 없습니다 (2차 구현 예정)")


ACTION_TYPES: dict[str, type[ActionType]] = {}
#: 팔레트에 보여줄 카테고리 순서
ACTION_CATEGORY_ORDER: list[str] = ["인식", "입력", "흐름", "데이터", "도구", "기타"]


def register_action(cls: type[ActionType]) -> type[ActionType]:
    """액션 타입을 등록하는 데코레이터."""
    if not cls.ID:
        raise ValueError(f"{cls.__name__} 에 ID 가 없습니다")
    if cls.ID in ACTION_TYPES:
        raise ValueError(f"액션 id 중복: {cls.ID}")
    if not cls.LABEL:
        cls.LABEL = cls.ID
    ACTION_TYPES[cls.ID] = cls
    return cls


def action_type(type_id: str) -> type[ActionType] | None:
    return ACTION_TYPES.get(type_id)


def action_params(type_id: str, params: dict | None) -> dict:
    """저장된 params 를 현재 스키마에 맞춰 정규화한다."""
    at = ACTION_TYPES.get(type_id)
    return coerce(at.PARAMS, params) if at else dict(params or {})


def action_summary(type_id: str, params: dict | None) -> str:
    at = ACTION_TYPES.get(type_id)
    if at is None:
        return f"(알 수 없는 액션: {type_id})"
    try:
        return at.summary(coerce(at.PARAMS, params))
    except Exception:  # 요약 하나 때문에 에디터가 죽으면 안 된다
        return at.LABEL


def actions_by_category() -> dict[str, list[type[ActionType]]]:
    groups: dict[str, list[type[ActionType]]] = {}
    for at in ACTION_TYPES.values():
        groups.setdefault(at.CATEGORY, []).append(at)
    for items in groups.values():
        items.sort(key=lambda a: a.LABEL)
    ordered = {c: groups[c] for c in ACTION_CATEGORY_ORDER if c in groups}
    for c, items in groups.items():
        ordered.setdefault(c, items)
    return ordered


# ---------------------------------------------------------------- 노드


@dataclass
class NodeType:
    """플로우차트 노드 종류."""

    id: str
    label: str
    color: str = "#4a6fa5"
    icon: str = "▢"
    help: str = ""
    in_ports: list[str] = field(default_factory=lambda: ["in"])
    out_ports: list[str] = field(default_factory=lambda: ["ok", "fail"])
    #: 노드 자체의 설정 파라미터
    params: list[Field] = field(default_factory=list)
    #: 내부에 액션 시퀀스를 담을 수 있는지
    allows_actions: bool = True
    #: 상태 조건(required_state)을 지정할 수 있는지
    allows_state: bool = True
    #: 출구가 파라미터에 따라 달라지는 노드(branch 등)를 위한 훅
    dynamic_out: Callable[[dict], list[str]] | None = None
    #: 플로우당 하나만 존재할 수 있는지 (start)
    unique: bool = False

    def ports_out(self, params: dict | None = None) -> list[str]:
        if self.dynamic_out is not None:
            try:
                return self.dynamic_out(params or {})
            except Exception:
                return list(self.out_ports)
        return list(self.out_ports)

    def defaults(self) -> dict[str, Any]:
        return defaults_for(self.params)


NODE_TYPES: dict[str, NodeType] = {}


def register_node(nt: NodeType) -> NodeType:
    if nt.id in NODE_TYPES:
        raise ValueError(f"노드 id 중복: {nt.id}")
    NODE_TYPES[nt.id] = nt
    return nt


def node_type(type_id: str) -> NodeType | None:
    return NODE_TYPES.get(type_id)


def node_params(type_id: str, params: dict | None) -> dict:
    nt = NODE_TYPES.get(type_id)
    return coerce(nt.params, params) if nt else dict(params or {})


# ---------------------------------------------------------------- 상태 조건


class ConditionType:
    """상태 판정에 쓰는 조건 하나."""

    ID: str = ""
    LABEL: str = ""
    ICON: str = "?"
    PARAMS: list[Field] = []

    @classmethod
    def summary(cls, params: dict[str, Any]) -> str:
        return cls.LABEL

    def evaluate(self, params: dict, ctx) -> bool:  # pragma: no cover - 2차
        raise NotImplementedError


CONDITION_TYPES: dict[str, type[ConditionType]] = {}


def register_condition(cls: type[ConditionType]) -> type[ConditionType]:
    if not cls.ID:
        raise ValueError(f"{cls.__name__} 에 ID 가 없습니다")
    if cls.ID in CONDITION_TYPES:
        raise ValueError(f"조건 id 중복: {cls.ID}")
    if not cls.LABEL:
        cls.LABEL = cls.ID
    CONDITION_TYPES[cls.ID] = cls
    return cls


def condition_type(type_id: str) -> type[ConditionType] | None:
    return CONDITION_TYPES.get(type_id)


def condition_summary(type_id: str, params: dict | None) -> str:
    ct = CONDITION_TYPES.get(type_id)
    if ct is None:
        return f"(알 수 없는 조건: {type_id})"
    try:
        return ct.summary(coerce(ct.PARAMS, params))
    except Exception:
        return ct.LABEL


def load_builtins() -> None:
    """기본 액션/노드/조건을 등록한다. 앱 시작과 테스트에서 한 번 호출한다."""
    import itda.actions  # noqa: F401  (import 부작용으로 등록됨)
    import itda.core.nodes  # noqa: F401
    import itda.core.conditions  # noqa: F401
