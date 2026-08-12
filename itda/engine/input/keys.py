"""키 이름 → 가상 키 코드.

사용자는 ``ctrl+shift+s`` 처럼 적는다. 이걸 Windows 가상 키 코드로 바꾼다.
한글 문자는 키 코드로 보내지 않고 유니코드로 직접 넣는다(입력기 상태에 좌우되지 않게).
"""

from __future__ import annotations

#: 이름 → 가상 키 코드
VK: dict[str, int] = {
    # 조합 키
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12, "menu": 0x12,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C, "cmd": 0x5B,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3,
    "lalt": 0xA4, "ralt": 0xA5,
    # 편집
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "space": 0x20, "backspace": 0x08,
    "bs": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "esc": 0x1B,
    "escape": 0x1B, "capslock": 0x14,
    # 이동
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdn": 0x22,
    # 기타
    "printscreen": 0x2C, "scrolllock": 0x91, "pause": 0x13, "apps": 0x5D,
    "numlock": 0x90,
    # 한글 키보드
    "hangul": 0x15, "한/영": 0x15, "hanja": 0x19, "한자": 0x19,
    # 기호 (VK_OEM_*)
    "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA,
    "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    # 숫자패드
    "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63, "num4": 0x64,
    "num5": 0x65, "num6": 0x66, "num7": 0x67, "num8": 0x68, "num9": 0x69,
    "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
}

# F1~F24
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i

#: 조합 키로 취급하는 이름 (누른 채로 다른 키를 누른다)
MODIFIERS = {"shift", "ctrl", "control", "alt", "menu", "win", "lwin", "rwin", "cmd",
             "lshift", "rshift", "lctrl", "rctrl", "lalt", "ralt"}


class KeyError_(ValueError):
    """알 수 없는 키 이름."""


def key_code(name: str) -> int:
    """키 이름 하나를 가상 키 코드로."""
    key = (name or "").strip().lower()
    if not key:
        raise KeyError_("빈 키 이름")
    if key in VK:
        return VK[key]
    if len(key) == 1 and (key.isascii() and (key.isalnum())):
        return ord(key.upper())
    raise KeyError_(f"알 수 없는 키: {name}")


def parse_combo(combo: str) -> tuple[list[int], int]:
    """``"ctrl+shift+s"`` → (조합키 목록, 마지막 키).

    조합 키만 적으면(``"ctrl"``) 마지막 키는 그 자신이 된다.
    """
    parts = [p for p in (combo or "").replace(" ", "").split("+") if p]
    if not parts:
        raise KeyError_("빈 키 조합")

    # 마지막 '+' 자체를 키로 쓰는 경우(예: "ctrl++")를 살린다
    if (combo or "").endswith("++"):
        parts.append("=")

    modifiers = [key_code(p) for p in parts[:-1] if p.lower() in MODIFIERS]
    unknown_mods = [p for p in parts[:-1] if p.lower() not in MODIFIERS]
    if unknown_mods:
        raise KeyError_(f"조합 키가 아닌 이름이 앞에 있습니다: {', '.join(unknown_mods)}")

    return modifiers, key_code(parts[-1])


def is_known(combo: str) -> bool:
    """편집기에서 미리 검사할 때 쓴다."""
    try:
        parse_combo(combo)
        return True
    except (KeyError_, ValueError):
        return False


def describe(combo: str) -> str:
    """사람이 읽는 표기로 정규화. 못 읽으면 원문 그대로."""
    try:
        modifiers, final = parse_combo(combo)
    except (KeyError_, ValueError):
        return combo
    # 같은 코드에 이름이 여러 개다(ctrl/control). 먼저 선언한 쪽을 대표 이름으로 쓴다.
    names: dict[int, str] = {}
    for name, code in VK.items():
        names.setdefault(code, name)
    parts = [names.get(m, hex(m)).upper() for m in modifiers]
    parts.append(names.get(final, chr(final) if 0x20 < final < 0x7F else hex(final)).upper())
    return " + ".join(parts)
