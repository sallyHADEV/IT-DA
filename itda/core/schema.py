"""파라미터 스키마.

액션과 조건은 자기 파라미터를 :class:`Field` 목록으로 선언하기만 한다.
속성 패널(:mod:`itda.gui.widgets.schema_form`)이 그 선언을 읽어 폼을 자동으로 만들기 때문에
액션을 추가할 때 UI 코드를 손댈 필요가 없다. 이 프로젝트에서 가장 중요한 규약이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 지원하는 필드 타입. schema_form 이 이 문자열을 보고 위젯을 고른다.
FIELD_TYPES = (
    "int",        # QSpinBox
    "float",      # QDoubleSpinBox
    "str",        # QLineEdit
    "text",       # QPlainTextEdit (여러 줄)
    "bool",       # QCheckBox
    "enum",       # QComboBox (options 사용)
    "point",      # x,y 스핀 + 좌표 도구 버튼
    "rect",       # x,y,w,h 스핀 + 영역 캡처 버튼
    "color",      # 색상 선택
    "key",        # 키 조합 입력 (예: "ctrl+shift+s")
    "var",        # 변수 이름 입력 (자동완성)
    "expr",       # 식 입력
    "file",       # 파일 경로 + 찾아보기
    "object_ref",       # 객체 저장소의 객체 하나
    "object_ref_list",  # 객체 여러 개 (예외 상황 대비 다중 이미지)
    "flow_ref",         # 프로젝트 내 플로우 하나
    "state_ref",        # 상태 하나
    "node_ref",         # 같은 플로우 안의 노드 하나 (예외 처리 이동 대상)
    "point_list",       # 멀티터치/드래그 경로용 좌표 목록
    "match_threshold",  # 이미지 일치 임계값 — 슬라이더 + "기본값 사용" 체크박스, 0=상속
)


@dataclass(slots=True)
class Field:
    """파라미터 하나의 선언.

    Args:
        name: 파라미터 키. ``params`` 딕셔너리의 키가 된다.
        type: :data:`FIELD_TYPES` 중 하나.
        label: 화면에 보일 이름. 비우면 ``name`` 을 쓴다.
        default: 기본값.
        options: ``enum`` 일 때 ``(값, 표시이름)`` 목록.
        minimum/maximum/step/suffix: 숫자 위젯 설정.
        help: 툴팁.
        depends_on: ``(다른_필드명, 값)`` — 그 필드가 해당 값일 때만 폼에 보인다.
            값 자리에 튜플/리스트를 주면 그 중 하나이기만 하면 된다.
        group: 폼에서 묶어 보여줄 그룹 이름.
    """

    name: str
    type: str = "str"
    label: str = ""
    default: Any = None
    options: list[tuple[Any, str]] = field(default_factory=list)
    minimum: float | None = None
    maximum: float | None = None
    step: float = 1
    suffix: str = ""
    help: str = ""
    depends_on: tuple[str, Any] | None = None
    group: str = ""

    def __post_init__(self) -> None:
        if self.type not in FIELD_TYPES:
            raise ValueError(f"알 수 없는 필드 타입: {self.type!r} (필드 {self.name!r})")
        if not self.label:
            self.label = self.name
        if self.default is None:
            self.default = _implicit_default(self.type, self.options)

    def is_visible(self, params: dict[str, Any]) -> bool:
        """``depends_on`` 조건을 만족해 폼에 표시해야 하는지."""
        if not self.depends_on:
            return True
        key, expected = self.depends_on
        current = params.get(key)
        if isinstance(expected, (tuple, list, set)):
            return current in expected
        return current == expected


def _implicit_default(ftype: str, options: list[tuple[Any, str]]) -> Any:
    match ftype:
        case "int":
            return 0
        case "float":
            return 0.0
        case "bool":
            return False
        case "enum":
            return options[0][0] if options else ""
        case "point":
            return [0, 0]
        case "rect":
            return [0, 0, 0, 0]
        case "object_ref_list" | "point_list":
            return []
        case "match_threshold":
            return 0.0  # 0 = 상속. 빈 문자열이 들어가면 프로젝트 파일에 문자열이 저장된다
        case "color":
            return "#000000"
        case _:
            return ""


def defaults_for(fields: list[Field]) -> dict[str, Any]:
    """스키마의 기본값만으로 채워진 params 딕셔너리를 만든다."""
    out: dict[str, Any] = {}
    for f in fields:
        value = f.default
        if isinstance(value, (list, dict)):
            value = type(value)(value)  # 기본값 리스트를 공유하지 않도록 복사
        out[f.name] = value
    return out


def coerce(fields: list[Field], params: dict[str, Any] | None) -> dict[str, Any]:
    """저장된 params 를 스키마에 맞춘다.

    없는 키는 기본값으로 채우고, 스키마에서 사라진 키는 버린다.
    오래된 프로젝트 파일을 열어도 깨지지 않게 하는 지점이다.
    """
    result = defaults_for(fields)
    if not params:
        return result
    for f in fields:
        if f.name in params:
            result[f.name] = params[f.name]
    return result
