"""액션 실행부.

편집기 쪽(스키마·요약)은 ``itda/actions/*.py`` 에 그대로 두고, 실행부만 여기 모은다.
액션 파일이 OpenCV·win32 를 끌어들이지 않아 편집기 시작이 가벼워진다.

새 액션에 실행을 붙이는 방법::

    @executor("my_action")
    def _my_action(action, ctx) -> ActionResult:
        ctx.log("무언가 했다")
        return ActionResult(ok=True)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from itda.engine.context import ActionResult, ExecutionContext
from itda.engine.input import planner, touch
from itda.vision.matcher import SearchStats

Executor = Callable[[object, ExecutionContext], ActionResult]

EXECUTORS: dict[str, Executor] = {}


def executor(type_id: str) -> Callable[[Executor], Executor]:
    def register(fn: Executor) -> Executor:
        EXECUTORS[type_id] = fn
        return fn

    return register


def get(type_id: str) -> Executor | None:
    return EXECUTORS.get(type_id)


class StopFlow(Exception):
    """`중단` 액션. ``scope`` 가 all 이면 전체를 멈춘다."""

    def __init__(self, scope: str = "flow", reason: str = "") -> None:
        super().__init__(reason or "중단")
        self.scope = scope
        self.reason = reason


def run_sequence(
    actions, ctx: ExecutionContext, flow_key: str = "", node_id: str = ""
) -> str | None:
    """액션 시퀀스를 순서대로 실행한다. 오류 메시지를 돌려준다(성공이면 None).

    노드 안의 액션과 상황 전이의 이동 동작이 같은 코드를 쓴다.
    """
    from itda.core import registry
    from itda.core.events import BUS, FAIL, OK, RUNNING, SKIPPED

    for action in actions:
        ctx.check_stop()
        if not action.enabled:
            if node_id:
                BUS.action_status.emit(flow_key, node_id, action.id, SKIPPED)
            continue

        at = registry.action_type(action.type)
        ctx.action_title = action.title or (at.LABEL if at else action.type)
        if node_id:
            BUS.action_status.emit(flow_key, node_id, action.id, RUNNING)

        run = EXECUTORS.get(action.type)
        if run is None:
            if node_id:
                BUS.action_status.emit(flow_key, node_id, action.id, FAIL)
            return f"실행부가 없는 액션입니다: {action.type}"

        ctx.delay_before(action.timing)
        result = run(action, ctx)
        ctx.delay_after(action.timing)

        if not result.ok:
            if node_id:
                BUS.action_status.emit(flow_key, node_id, action.id, FAIL)
            return result.message or f"{ctx.action_title} 실패"

        if node_id:
            BUS.action_status.emit(flow_key, node_id, action.id, OK)
        if result.message == "skip_rest":
            ctx.log("조건이 거짓이라 남은 액션을 건너뜁니다", level="debug")
            break

    ctx.action_title = ""
    return None


# ---------------------------------------------------------------- 보조


def _region(params: dict) -> tuple[int, int, int, int] | None:
    """검색 범위 파라미터 → ROI."""
    mode = params.get("region_mode", "full")
    if mode == "rect":
        rect = params.get("region") or [0, 0, 0, 0]
        if rect[2] > 0 and rect[3] > 0:
            return (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
    return None


def _target_point(params: dict, ctx: ExecutionContext) -> tuple[int, int] | None:
    """click/move 계열의 목표 좌표를 구한다."""
    mode = params.get("target_mode", "fixed")
    offset = params.get("offset") or [0, 0]

    match mode:
        case "object":
            point = ctx.object_point(
                params.get("object", ""), params.get("object_lookup", "cache_or_search")
            )
        case "var":
            value = ctx.variables.get(params.get("var", ""))
            point = tuple(value) if isinstance(value, (list, tuple)) and len(value) >= 2 else None
        case "current":
            point = ctx.cursor
        case _:
            raw = params.get("point") or [0, 0]
            point = (int(raw[0]), int(raw[1]))

    if point is None:
        return None
    return (int(point[0]) + int(offset[0]), int(point[1]) + int(offset[1]))


def _store_position(action, ctx: ExecutionContext, point: tuple[int, int] | None) -> None:
    """결과 변수에 좌표와 파생 변수를 담는다."""
    name = getattr(action, "out_var", "")
    if not name:
        return
    if point is None:
        ctx.set_var(name, [])
        ctx.set_var(f"{name}_ok", False)
        return
    ctx.set_var(name, [int(point[0]), int(point[1])])
    ctx.set_var(f"{name}_x", int(point[0]))
    ctx.set_var(f"{name}_y", int(point[1]))
    ctx.set_var(f"{name}_ok", True)


# ---------------------------------------------------------------- 인식


@executor("image_search")
def _image_search(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    names = [n for n in (params.get("objects") or []) if n]
    if not names:
        return ActionResult.failed("찾을 객체가 지정되지 않았습니다")

    required = params.get("required", True)
    deadline = (
        time.perf_counter() + max(0, params.get("retry_ms", 0)) / 1000
        if required else float("inf")
    )
    stats = SearchStats()
    while True:
        ctx.check_stop()
        match = ctx.find_object(
            names,
            threshold=params.get("threshold", 0.0),
            mode=params.get("mode", "any"),
            roi=_region(params),
            stats=stats,
        )
        if match is not None:
            ctx.log(f"찾음 {match.center} (점수 {match.score:.3f}) · {stats.describe()}",
                    level="debug")
            _store_position(action, ctx, match.center)
            return ActionResult(ok=True, value=list(match.center))
        if time.perf_counter() >= deadline:
            break
        ctx.sleep(120, jitter_pct=0)
        ctx.invalidate_frame()

    _store_position(action, ctx, None)
    message = f"찾지 못했습니다: {', '.join(names)}"
    return ActionResult.failed(message)


@executor("wait_image")
def _wait_image(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    names = [n for n in (params.get("objects") or []) if n]
    if not names:
        return ActionResult.failed("대상 객체가 지정되지 않았습니다")

    want_visible = params.get("until", "appear") == "appear"
    timeout = max(0, params.get("timeout_ms", 5000)) / 1000
    poll = max(10, params.get("poll_ms", 200))
    deadline = time.perf_counter() + timeout

    while True:
        ctx.check_stop()
        ctx.invalidate_frame()
        match = ctx.find_object(
            names,
            threshold=params.get("threshold", 0.0),
            roi=_region(params),
            # 사라짐 판정은 이전 위치만 보면 다른 위치로 이동한 이미지를 놓친다.
            use_hint=(params.get("remember_position", True) and want_visible),
        )
        visible = match is not None
        if visible == want_visible:
            if visible and params.get("remember_position", True):
                # 위치는 객체 캐시에 기억하고 결과 변수는 성공 여부로 유지한다.
                if action.out_var:
                    ctx.set_var(action.out_var, True)
            elif action.out_var:
                ctx.set_var(action.out_var, True)
            return ActionResult(ok=True, value=True)
        if time.perf_counter() >= deadline:
            break
        ctx.sleep(poll, jitter_pct=0)

    if action.out_var:
        ctx.set_var(action.out_var, False)
    message = f"시간 초과: {', '.join(names)} ({'나타나지' if want_visible else '사라지지'} 않음)"
    if params.get("required", True):
        return ActionResult.failed(message)
    ctx.log(message, level="warn")
    return ActionResult(ok=True, value=False)


@executor("pixel_check")
def _pixel_check(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    point = params.get("point") or [0, 0]
    frame = ctx.screen(fresh=True)
    x, y = int(point[0]), int(point[1])
    if not (0 <= y < frame.shape[0] and 0 <= x < frame.shape[1]):
        return ActionResult.failed(f"화면 밖 좌표입니다 ({x}, {y})")

    blue, green, red = (int(v) for v in frame[y, x][:3])
    expected = str(params.get("color", "#ffffff")).lstrip("#")
    try:
        er, eg, eb = (int(expected[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return ActionResult.failed(f"색 형식이 잘못되었습니다: {params.get('color')}")

    tolerance = int(params.get("tolerance", 12))
    close = all(abs(a - b) <= tolerance for a, b in ((red, er), (green, eg), (blue, eb)))
    if action.out_var:
        ctx.set_var(action.out_var, close)
    if not close and params.get("required", False):
        return ActionResult.failed(
            f"색이 다릅니다 — 실제 #{red:02x}{green:02x}{blue:02x} / 기대 #{expected}"
        )
    return ActionResult(ok=True, value=close)


@executor("ocr_read")
def _ocr_read(action, ctx: ExecutionContext) -> ActionResult:
    from itda.vision import ocr

    params = action.params
    rect = params.get("region") or [0, 0, 0, 0]
    if rect[2] <= 0 or rect[3] <= 0:
        return ActionResult.failed("인식 영역이 지정되지 않았습니다")

    frame = ctx.screen(fresh=True)
    patch = frame[rect[1]:rect[1] + rect[3], rect[0]:rect[0] + rect[2]]
    result = ocr.read(patch, lang=params.get("lang", "kor+eng"),
                      scale=params.get("scale", 2.0), binarize=params.get("binarize", True),
                      layout=params.get("layout", ocr.DEFAULT_PSM))
    if not result.ok:
        return ActionResult.failed(result.message)

    text = ocr.post_process(result.text, params.get("post", "trim"))
    if action.out_var:
        ctx.set_var(action.out_var, text)
    ctx.log(f"읽음: {text!r}", level="debug")
    return ActionResult(ok=True, value=text)


# ---------------------------------------------------------------- 입력


@executor("click")
def _click(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    point = _target_point(params, ctx)
    if point is None:
        return ActionResult.failed("클릭할 위치를 찾지 못했습니다")
    steps = planner.plan_click(
        point,
        start=ctx.cursor,
        button=params.get("button", "left"),
        click_type=params.get("click_type", "single"),
        human=ctx.human(params),
        timing=ctx.timing,
        rng=ctx.rng,
        move_first=params.get("move_first", True),
    )
    ctx.send(steps)
    return ActionResult(ok=True, value=list(point))


@executor("move")
def _move(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    point = _target_point(params, ctx)
    if point is None:
        return ActionResult.failed("이동할 위치를 찾지 못했습니다")
    ctx.send(
        planner.plan_move(
            ctx.cursor, point, ctx.human(params), ctx.timing,
            duration_ms=params.get("duration_ms") or None, rng=ctx.rng,
        )
    )
    return ActionResult(ok=True, value=list(point))


@executor("drag")
def _drag(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    start = tuple(params.get("from_point") or [0, 0])
    end = tuple(params.get("to_point") or [0, 0])
    ctx.send(
        planner.plan_drag(
            start, end, button=params.get("button", "left"),
            duration_ms=params.get("duration_ms", 300), human=ctx.human(params),
            timing=ctx.timing, rng=ctx.rng, cursor=ctx.cursor,
        )
    )
    return ActionResult(ok=True)


@executor("scroll")
def _scroll(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    point = _target_point(params, ctx) if params.get("target_mode") != "current" else None
    ctx.send(
        planner.plan_scroll(
            params.get("amount", 0), point, ctx.human(params), ctx.rng,
            timing=ctx.timing, cursor=ctx.cursor,
        )
    )
    return ActionResult(ok=True)


@executor("key_press")
def _key_press(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    combo = params.get("keys", "")
    if not combo:
        return ActionResult.failed("키가 지정되지 않았습니다")
    try:
        steps = planner.plan_key(
            combo, action=params.get("action", "tap"), repeat=params.get("repeat", 1),
            human=ctx.human(params), rng=ctx.rng,
        )
    except ValueError as e:
        return ActionResult.failed(str(e))
    ctx.send(steps)
    return ActionResult(ok=True)


@executor("type_text")
def _type_text(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    text = ctx.text(params.get("text", ""))
    if params.get("clear_first"):
        ctx.send(planner.plan_key("ctrl+a", human=ctx.human(params), rng=ctx.rng))
        ctx.send(planner.plan_key("delete", human=ctx.human(params), rng=ctx.rng))

    if params.get("method") == "clipboard":
        _set_clipboard(text)
        ctx.send(planner.plan_key("ctrl+v", human=ctx.human(params), rng=ctx.rng))
        return ActionResult(ok=True, value=text)

    ctx.send(
        planner.plan_text(text, interval_ms=params.get("interval_ms", 30),
                          human=ctx.human(params), rng=ctx.rng)
    )
    return ActionResult(ok=True, value=text)


@executor("touch_point")
def _touch_point(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    point = _target_point(params, ctx)
    if point is None:
        return ActionResult.failed("터치할 위치를 찾지 못했습니다")
    ctx.send(touch.plan_tap([point], hold_ms=params.get("hold_ms", 60)))
    return ActionResult(ok=True, value=list(point))


@executor("touch_multi")
def _touch_multi(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    points = [(int(p[0]), int(p[1])) for p in (params.get("points") or []) if len(p) >= 2]
    if not points:
        return ActionResult.failed("접점이 지정되지 않았습니다")

    gesture = params.get("gesture", "tap")
    if gesture in ("pinch_in", "pinch_out") and len(points) >= 2:
        center = ((points[0][0] + points[1][0]) // 2, (points[0][1] + points[1][1]) // 2)
        distance = int(params.get("distance", 80))
        inward = gesture == "pinch_in"
        steps = touch.plan_pinch(
            center,
            start_distance=distance * 2 if inward else distance,
            end_distance=distance // 2 if inward else distance * 2,
        )
    elif gesture == "rotate" and len(points) >= 2:
        center = ((points[0][0] + points[1][0]) // 2, (points[0][1] + points[1][1]) // 2)
        radius = max(10, abs(points[1][0] - points[0][0]) // 2)
        steps = touch.plan_rotate(center, radius, float(params.get("angle", 90)))
    else:
        steps = touch.plan_tap(points, hold_ms=params.get("hold_ms", 120))

    ctx.send(steps)
    return ActionResult(ok=True)


@executor("touch_drag")
def _touch_drag(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    path = [(int(p[0]), int(p[1])) for p in (params.get("path") or []) if len(p) >= 2]
    if len(path) < 2:
        return ActionResult.failed("경로에 점이 두 개 이상 필요합니다")
    ctx.send(
        touch.plan_touch_drag(
            path, duration_ms=params.get("duration_ms", 400),
            hold_start_ms=params.get("hold_start_ms", 80),
        )
    )
    return ActionResult(ok=True)


# ---------------------------------------------------------------- 흐름


@executor("sleep")
def _sleep(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    jitter = params.get("jitter_pct", -1.0)
    ctx.sleep(params.get("ms", 0), None if jitter is None or jitter < 0 else jitter)
    return ActionResult(ok=True)


@executor("if")
def _if(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    if ctx.truthy(params.get("expr", "")):
        return ActionResult(ok=True, value=True)
    match params.get("on_false", "skip_rest"):
        case "fail":
            return ActionResult.failed(f"조건이 거짓입니다: {params.get('expr', '')}")
        case "continue":
            return ActionResult(ok=True, value=False)
        case _:
            return ActionResult(ok=True, value=False, message="skip_rest")


@executor("stop")
def _stop(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    raise StopFlow(params.get("scope", "flow"), ctx.text(params.get("reason", "")))


@executor("run_flow")
def _run_flow(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    if ctx.run_flow is None:
        return ActionResult.failed("플로우 실행기가 연결되지 않았습니다")
    target = params.get("flow", "")
    if not target:
        return ActionResult.failed("대상 플로우가 지정되지 않았습니다")
    ok = ctx.run_flow(
        target,
        _parse_args(ctx, params.get("args", "")),
        params.get("wait", True),
        params.get("priority", 0),
    )
    if action.out_var:
        ctx.set_var(action.out_var, ok)
    return ActionResult(ok=ok, message="" if ok else f"'{target}' 실행 실패")


def _parse_args(ctx: ExecutionContext, text: str) -> dict:
    """``name=value`` 줄 단위 인자."""
    args: dict[str, object] = {}
    for line in (text or "").splitlines():
        if "=" not in line:
            continue
        name, _, raw = line.partition("=")
        args[name.strip()] = ctx.text(raw.strip())
    return args


@executor("goto_state")
def _goto_state(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    target = params.get("target_state", "")
    if ctx.states is None:
        return ActionResult.failed("상황 머신이 연결되지 않았습니다")
    if not target:
        return ActionResult.failed("목표 상황이 지정되지 않았습니다")

    ok = ctx.states.ensure(target, params.get("timeout_ms", 10000))
    if action.out_var:
        ctx.set_var(action.out_var, ok)
    if not ok and params.get("required", True):
        return ActionResult.failed(f"'{target}' 상황으로 이동하지 못했습니다")
    return ActionResult(ok=True, value=ok)


@executor("wait_state")
def _wait_state(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    target = params.get("target_state", "")
    if ctx.states is None:
        return ActionResult.failed("상황 머신이 연결되지 않았습니다")
    if not target:
        return ActionResult.failed("기다릴 상황이 지정되지 않았습니다")

    ok = ctx.states.wait_for(
        target, params.get("timeout_ms", 10000), params.get("poll_ms", 300)
    )
    if action.out_var:
        ctx.set_var(action.out_var, ok)
    if not ok and params.get("required", True):
        return ActionResult.failed(f"'{target}' 상황이 되지 않았습니다 (시간 초과)")
    return ActionResult(ok=True, value=ok)


# ---------------------------------------------------------------- 데이터


@executor("set_var")
def _set_var(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    name = params.get("name", "")
    if not name:
        return ActionResult.failed("변수 이름이 없습니다")
    try:
        value = ctx.value(params.get("value", ""))
    except Exception as e:
        return ActionResult.failed(f"값 계산 실패: {e}")
    ctx.set_var(name, value, params.get("scope", "flow"))
    return ActionResult(ok=True, value=value)


@executor("calc")
def _calc(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    name = params.get("name", "")
    if not name:
        return ActionResult.failed("대상 변수가 없습니다")
    current = ctx.variables.get(name, 0)
    try:
        operand = ctx.value(params.get("operand", "0"))
        result = _apply_op(params.get("op", "add"), current, operand)
    except Exception as e:
        return ActionResult.failed(f"연산 실패: {e}")

    if params.get("clamp"):
        result = max(params.get("min", 0.0), min(params.get("max", 100.0), result))
    ctx.set_var(name, result)
    if action.out_var:
        ctx.set_var(action.out_var, result)
    return ActionResult(ok=True, value=result)


def _apply_op(op: str, left, right):
    left = float(left or 0) if op != "set" else left
    match op:
        case "add":
            return left + float(right)
        case "sub":
            return left - float(right)
        case "mul":
            return left * float(right)
        case "div":
            return left / float(right)
        case "mod":
            return left % float(right)
        case _:
            return right


@executor("clipboard")
def _clipboard(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    if params.get("mode") == "write":
        text = ctx.text(str(params.get("value", "")))
        _set_clipboard(text)
        return ActionResult(ok=True, value=text)
    text = _get_clipboard()
    if action.out_var:
        ctx.set_var(action.out_var, text)
    return ActionResult(ok=True, value=text)


def _set_clipboard(text: str) -> None:
    import pyperclip

    pyperclip.copy(text)


def _get_clipboard() -> str:
    import pyperclip

    return pyperclip.paste()


@executor("log")
def _log(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    ctx.log(ctx.text(params.get("message", "")), level=params.get("level", "info"))
    return ActionResult(ok=True)


# ---------------------------------------------------------------- 도구


@executor("beep")
def _beep(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    repeat = max(1, int(params.get("repeat", 1)))
    for index in range(repeat):
        ctx.check_stop()
        if index:
            ctx.sleep(120, jitter_pct=0)
        _play_sound(params)
    return ActionResult(ok=True)


def _play_sound(params: dict) -> None:
    if sys.platform != "win32":  # pragma: no cover - 다른 OS
        return
    import winsound

    sound = params.get("sound", "beep")
    if sound == "file" and params.get("path"):
        winsound.PlaySound(params["path"], winsound.SND_FILENAME | winsound.SND_ASYNC)
        return
    aliases = {
        "asterisk": winsound.MB_ICONASTERISK,
        "exclamation": winsound.MB_ICONEXCLAMATION,
        "critical": winsound.MB_ICONHAND,
    }
    if sound in aliases:
        winsound.MessageBeep(aliases[sound])
        return
    winsound.Beep(int(params.get("freq", 880)), int(params.get("duration_ms", 300)))


@executor("screenshot")
def _screenshot(action, ctx: ExecutionContext) -> ActionResult:
    """스크린샷 저장.

    ``capture.grab_array()`` + ``save_bgr()`` 로 찍고 쓴다 — 둘 다 작업 스레드에서도
    안전하다(Windows 는 GDI, 저장은 cv2). ``QPixmap``/``save_pixmap`` 을 쓰면 이 액션이
    멀티 플로우의 작업 스레드에서 실행될 때 Qt 가 그 자리에서 죽인다.
    """
    from itda.vision import capture

    params = action.params
    if params.get("region_mode") == "rect":
        rect = tuple(int(v) for v in (params.get("region") or [0, 0, 0, 0]))
        array = capture.grab_array(rect)
    else:
        array = capture.grab_array()

    if array.size == 0:
        return ActionResult.failed("화면 캡처 실패")

    raw = params.get("path", "captures/${timestamp}.png")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    relative = ctx.text(raw).replace("${timestamp}", stamp)
    base = ctx.project.path or Path.cwd()
    target = Path(relative) if os.path.isabs(relative) else Path(base) / relative
    if not capture.save_bgr(array, target):
        return ActionResult.failed(f"저장 실패: {target}")
    if action.out_var:
        ctx.set_var(action.out_var, str(target))
    ctx.log(f"스크린샷 저장: {target}", level="debug")
    return ActionResult(ok=True, value=str(target))


@executor("window")
def _window(action, ctx: ExecutionContext) -> ActionResult:
    return run_window_op(action.params, ctx, out_var=getattr(action, "out_var", ""))


def run_window_op(params: dict, ctx: ExecutionContext, out_var: str = "") -> ActionResult:
    """창 제어 — 액션과 `창 맞추기` 노드가 함께 쓴다."""
    from itda.engine.window import WindowController

    title = ctx.text(params.get("title", "")) or ctx.project.settings.target_window
    controller = WindowController()
    window = controller.find(title, params.get("match", "contains"))
    if window is None:
        if out_var:
            ctx.set_var(out_var, False)
        message = f"창을 찾지 못했습니다: {title or '(제목 미지정)'}"
        if params.get("required", True):
            return ActionResult.failed(message)
        ctx.log(message, level="warn")
        return ActionResult(ok=True, value=False)

    if params.get("op") == "exists":
        if out_var:
            ctx.set_var(out_var, True)
        return ActionResult(ok=True, value=True)

    target = controller.plan(params, window)
    ok = controller.apply(params, window)
    ctx.invalidate_frame()
    if target is not None:
        ctx.log(f"창 '{window.title}' → {target.as_tuple()}", level="debug")
    # 창 제어에는 변동계수를 걸지 않는다 — 창은 매번 같은 자리여야 좌표가 어긋나지 않는다
    ctx.sleep(params.get("settle_ms", 200), jitter_pct=0)

    if ok and target is not None:
        # 창이 요청을 그대로 받아들였는지 확인한다. 최소 크기가 정해진 창이나 스냅이 걸린
        # 창은 조용히 다른 크기가 되는데, 그러면 이후 좌표가 전부 어긋난다.
        actual = controller.box_of(window.handle)
        if actual.as_tuple() != target.as_tuple():
            ctx.log(
                f"창 '{window.title}' 이 요청한 위치·크기를 그대로 받지 않았습니다 — "
                f"요청 {target.as_tuple()} / 실제 {actual.as_tuple()}",
                level="warn",
            )
    if out_var:
        ctx.set_var(out_var, ok)
    return ActionResult(ok=ok, message="" if ok else "창 제어 실패")


@executor("run_program")
def _run_program(action, ctx: ExecutionContext) -> ActionResult:
    params = action.params
    path = ctx.text(params.get("path", ""))
    if not path:
        return ActionResult.failed("실행 파일이 지정되지 않았습니다")
    args = [a for a in ctx.text(params.get("args", "")).split(" ") if a]
    workdir = ctx.text(params.get("workdir", "")) or None

    try:
        process = subprocess.Popen([path, *args], cwd=workdir)
    except OSError as e:
        return ActionResult.failed(f"실행 실패: {e}")

    if not params.get("wait", False):
        if action.out_var:
            ctx.set_var(action.out_var, process.pid)
        return ActionResult(ok=True, value=process.pid)

    timeout = params.get("timeout_ms", 0) / 1000 or None
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return ActionResult.failed("프로그램이 제한시간 안에 끝나지 않았습니다")
    if action.out_var:
        ctx.set_var(action.out_var, code)
    return ActionResult(ok=code == 0, message="" if code == 0 else f"종료 코드 {code}")
