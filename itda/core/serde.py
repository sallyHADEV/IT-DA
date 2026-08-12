"""데이터클래스 ↔ JSON 딕셔너리 변환.

모델 클래스마다 ``to_dict``/``from_dict`` 를 손으로 쓰면 필드를 추가할 때마다 세 군데를
고쳐야 하고 반드시 하나를 빠뜨린다. 타입 힌트를 읽어 일반적으로 처리한다.

읽을 때 규칙:
* 파일에 없는 키는 데이터클래스의 기본값을 쓴다 → 옛 프로젝트 파일이 그대로 열린다.
* 모델에 없는 키는 버린다 → 미래 버전 파일을 열어도 죽지 않는다.
"""

from __future__ import annotations

import copy
import types
import typing
from dataclasses import MISSING, fields, is_dataclass
from typing import Any, TypeVar

T = TypeVar("T")

_HINT_CACHE: dict[type, dict[str, Any]] = {}


def _hints(cls: type) -> dict[str, Any]:
    if cls not in _HINT_CACHE:
        # 모델 모듈은 `from __future__ import annotations` 를 쓰므로 여기서 해석한다.
        _HINT_CACHE[cls] = typing.get_type_hints(cls)
    return _HINT_CACHE[cls]


def to_dict(obj: Any) -> Any:
    """데이터클래스 트리를 JSON 으로 저장 가능한 값으로 바꾼다."""
    if is_dataclass(obj) and not isinstance(obj, type):
        out: dict[str, Any] = {}
        for f in fields(obj):
            if not f.metadata.get("serialize", True):
                continue
            out[f.name] = to_dict(getattr(obj, f.name))
        return out
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): to_dict(v) for k, v in obj.items()}
    return obj


def from_dict(cls: type[T], data: dict[str, Any] | None) -> T:
    """``cls`` 인스턴스를 딕셔너리에서 복원한다."""
    if not is_dataclass(cls):
        raise TypeError(f"데이터클래스가 아님: {cls!r}")
    data = data or {}
    hints = _hints(cls)
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if not f.init or not f.metadata.get("serialize", True):
            continue
        if f.name not in data:
            continue
        value = data[f.name]
        if value is None and _has_default(f):
            continue
        kwargs[f.name] = _convert(hints.get(f.name, Any), value)
    return cls(**kwargs)  # type: ignore[return-value]


def _has_default(f: Any) -> bool:
    return f.default is not MISSING or f.default_factory is not MISSING  # type: ignore[misc]


def _convert(tp: Any, value: Any) -> Any:
    if tp is Any or tp is None:
        return value

    origin = typing.get_origin(tp)

    if origin in (types.UnionType, typing.Union):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        if value is None:
            return None
        # 첫 갈래만 시도하면 int | str 에 "abc" 가 들어왔을 때 깨진다. 순서대로 시도한다.
        for arg in args:
            try:
                return _convert(arg, value)
            except (TypeError, ValueError):
                continue
        return value

    if origin in (list, typing.List):
        args = typing.get_args(tp)
        inner = args[0] if args else Any
        return [_convert(inner, v) for v in (value or [])]

    if origin in (tuple, typing.Tuple):
        args = typing.get_args(tp)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_convert(args[0], v) for v in (value or []))
        return tuple(_convert(a, v) for a, v in zip(args, value or ()))

    if origin in (dict, typing.Dict):
        args = typing.get_args(tp)
        vt = args[1] if len(args) == 2 else Any
        return {k: _convert(vt, v) for k, v in (value or {}).items()}

    if is_dataclass(tp):
        return from_dict(tp, value if isinstance(value, dict) else {})

    if tp is float and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    if tp is int and isinstance(value, float) and float(value).is_integer():
        return int(value)

    return value


def clone(obj: T) -> T:
    """데이터클래스 트리를 깊은 복사한다.

    직렬화 왕복(to_dict → from_dict)은 매번 타입 힌트 리플렉션을 타서, 복사/붙여넣기와
    되돌리기가 잦을 때 비용이 쌓인다. 모델은 평범한 데이터클래스뿐이라 deepcopy 면 충분하다.
    """
    return copy.deepcopy(obj)
