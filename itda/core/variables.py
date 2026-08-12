"""변수와 연산.

매크로 안에서 쓰는 식은 사용자가 직접 적는다. ``eval`` 을 그대로 쓰면 프로젝트 파일 하나로
임의 코드가 실행되므로, AST 를 화이트리스트로 검사해 계산식만 허용한다.
"""

from __future__ import annotations

import ast
import operator as op
import random
import time
from dataclasses import dataclass, field
from typing import Any

_BIN_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
}

_CMP_OPS = {
    ast.Eq: op.eq,
    ast.NotEq: op.ne,
    ast.Lt: op.lt,
    ast.LtE: op.le,
    ast.Gt: op.gt,
    ast.GtE: op.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_UNARY_OPS = {
    ast.UAdd: op.pos,
    ast.USub: op.neg,
    ast.Not: op.not_,
}


def _contains(haystack: Any, needle: Any) -> bool:
    return str(needle) in str(haystack)


#: 식 안에서 부를 수 있는 함수. 파일 접근이나 import 는 없다.
SAFE_FUNCS: dict[str, Any] = {
    "len": len,
    "int": lambda v: int(float(v)) if isinstance(v, str) and v.strip() else int(v),
    "float": float,
    "str": str,
    "bool": bool,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sum": sum,
    "contains": _contains,
    "lower": lambda s: str(s).lower(),
    "upper": lambda s: str(s).upper(),
    "strip": lambda s: str(s).strip(),
    "replace": lambda s, a, b: str(s).replace(str(a), str(b)),
    "digits": lambda s: "".join(ch for ch in str(s) if ch.isdigit()),
    "rand": lambda a, b: random.randint(int(a), int(b)),
    "now": time.time,
}


class ExpressionError(ValueError):
    """식이 허용되지 않는 문법을 쓰거나 계산에 실패했을 때."""


def safe_eval(expr: str, variables: dict[str, Any] | None = None) -> Any:
    """계산식만 허용하는 평가기.

    빈 문자열은 ``""`` 를 돌려준다. 함수 호출은 :data:`SAFE_FUNCS` 에 있는 것만 가능하고
    속성 접근, 대입, 반복문, import 는 전부 거부한다.
    """
    expr = (expr or "").strip()
    if not expr:
        return ""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"식 문법 오류: {expr!r} ({e.msg})") from e
    return _eval_node(tree.body, variables or {})


def _eval_node(node: ast.AST, env: dict[str, Any]) -> Any:
    match node:
        case ast.Constant(value=v):
            return v
        case ast.Name(id=name):
            if name in env:
                return env[name]
            if name in SAFE_FUNCS:
                return SAFE_FUNCS[name]
            if name in ("True", "False", "None"):  # 방어적. 보통은 Constant 로 온다.
                return {"True": True, "False": False, "None": None}[name]
            raise ExpressionError(f"알 수 없는 변수: {name}")
        case ast.BinOp(left=l, op=o, right=r):
            fn = _BIN_OPS.get(type(o))
            if fn is None:
                raise ExpressionError(f"허용되지 않는 연산자: {type(o).__name__}")
            return fn(_eval_node(l, env), _eval_node(r, env))
        case ast.UnaryOp(op=o, operand=v):
            fn = _UNARY_OPS.get(type(o))
            if fn is None:
                raise ExpressionError(f"허용되지 않는 단항 연산자: {type(o).__name__}")
            return fn(_eval_node(v, env))
        case ast.BoolOp(op=o, values=values):
            vals = [_eval_node(v, env) for v in values]
            if isinstance(o, ast.And):
                return all(vals) and vals[-1]
            return next((v for v in vals if v), vals[-1])
        case ast.Compare(left=left, ops=ops, comparators=comps):
            current = _eval_node(left, env)
            for o, comp in zip(ops, comps):
                fn = _CMP_OPS.get(type(o))
                if fn is None:
                    raise ExpressionError(f"허용되지 않는 비교: {type(o).__name__}")
                right = _eval_node(comp, env)
                if not fn(current, right):
                    return False
                current = right
            return True
        case ast.IfExp(test=t, body=b, orelse=e):
            return _eval_node(b, env) if _eval_node(t, env) else _eval_node(e, env)
        case ast.Call(func=ast.Name(id=fname), args=args, keywords=kw):
            if kw:
                raise ExpressionError("키워드 인자는 지원하지 않습니다")
            fn = SAFE_FUNCS.get(fname)
            if fn is None:
                raise ExpressionError(f"허용되지 않는 함수: {fname}")
            return fn(*[_eval_node(a, env) for a in args])
        case ast.List(elts=elts):
            return [_eval_node(e, env) for e in elts]
        case ast.Tuple(elts=elts):
            return tuple(_eval_node(e, env) for e in elts)
        case ast.Dict(keys=keys, values=values):
            return {_eval_node(k, env): _eval_node(v, env) for k, v in zip(keys, values)}
        case ast.Subscript(value=v, slice=s):
            return _eval_node(v, env)[_eval_node(s, env)]
        case ast.Slice(lower=lower, upper=upper, step=step):
            # 파이썬 3.9+ 는 a[1:3] 을 Subscript(slice=Slice(...)) 로 만든다.
            # 이 갈래가 없으면 슬라이싱이 전부 문법 오류로 거부된다.
            return slice(
                _eval_node(lower, env) if lower is not None else None,
                _eval_node(upper, env) if upper is not None else None,
                _eval_node(step, env) if step is not None else None,
            )
        case _:
            raise ExpressionError(f"식에 쓸 수 없는 문법: {type(node).__name__}")


def find_placeholders(text: str) -> list[tuple[int, int, str]]:
    """``${...}`` 자리들을 찾는다. ``(시작, 끝, 식)`` 목록.

    정규식 ``\\$\\{([^}]*)\\}`` 로는 식 안에 중괄호가 들어간 경우
    (``${ {'a': 1}['a'] }`` 같은) 첫 ``}`` 에서 잘려 버린다. 중괄호 깊이를 세고
    따옴표 안은 건너뛴다.
    """
    spots: list[tuple[int, int, str]] = []
    i, n = 0, len(text or "")
    while i < n - 1:
        if text[i] != "$" or text[i + 1] != "{":
            i += 1
            continue
        depth = 1
        j = i + 2
        quote = ""
        while j < n:
            ch = text[j]
            if quote:
                if ch == "\\":
                    j += 2
                    continue
                if ch == quote:
                    quote = ""
            elif ch in "'\"":
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= n or depth != 0:
            break  # 닫히지 않았다 — 남은 부분은 그대로 둔다
        spots.append((i, j + 1, text[i + 2:j]))
        i = j + 1
    return spots


def interpolate(text: str, variables: dict[str, Any] | None = None) -> str:
    """``"안녕 ${name}"`` 처럼 문자열 안의 ``${식}`` 을 값으로 바꾼다."""
    if not text or "${" not in text:
        return text or ""

    out: list[str] = []
    cursor = 0
    for start, end, expr in find_placeholders(text):
        out.append(text[cursor:start])
        try:
            out.append(str(safe_eval(expr, variables)))
        except ExpressionError:
            out.append(text[start:end])  # 못 풀면 원문 유지 — 편집 중에 깨져 보이지 않게
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def referenced_names(text: str) -> list[str]:
    """문자열/식 안에서 참조하는 변수 이름을 모은다 (유효성 검사용)."""
    names: set[str] = set()
    if "${" in (text or ""):
        candidates = [expr for _s, _e, expr in find_placeholders(text)]
    else:
        candidates = [text or ""]
    for src in candidates:
        try:
            tree = ast.parse(src.strip() or "0", mode="eval")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id not in SAFE_FUNCS:
                names.add(node.id)
    return sorted(names)


@dataclass
class VariableStore:
    """실행 중 변수 저장소. 전역 / 플로우 두 단계만 둔다.

    노드 지역 변수까지 만들면 사용자가 헷갈리기만 하고 이득이 없다.
    """

    globals: dict[str, Any] = field(default_factory=dict)
    flow: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        """식 평가에 쓸 병합 뷰. 플로우 변수가 전역을 가린다."""
        merged = dict(self.globals)
        merged.update(self.flow)
        return merged

    def get(self, name: str, default: Any = None) -> Any:
        if name in self.flow:
            return self.flow[name]
        return self.globals.get(name, default)

    def set(self, name: str, value: Any, scope: str = "flow") -> None:
        if scope == "global":
            self.globals[name] = value
        else:
            self.flow[name] = value

    def eval(self, expr: str) -> Any:
        return safe_eval(expr, self.snapshot())

    def format(self, text: str) -> str:
        return interpolate(text, self.snapshot())


def cast_value(raw: str, type_name: str) -> Any:
    """변수 선언의 기본값 문자열을 선언 타입으로 변환한다."""
    text = (raw or "").strip()
    try:
        match type_name:
            case "int":
                return int(float(text)) if text else 0
            case "float":
                return float(text) if text else 0.0
            case "bool":
                return text.lower() in ("1", "true", "yes", "y", "참", "on")
            case _:
                return text
    except ValueError:
        return {"int": 0, "float": 0.0, "bool": False}.get(type_name, text)
