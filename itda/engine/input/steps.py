"""입력 한 단계.

계획 단계의 산출물이자 주입 단계의 입력. 플랫폼을 모른다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 단계 종류
MOVE = "move"        # 절대 좌표로 커서 이동 (물리 픽셀)
BUTTON = "button"    # 마우스 버튼 누름/뗌
WHEEL = "wheel"      # 휠
KEY = "key"          # 가상 키 코드 누름/뗌
CHAR = "char"        # 유니코드 문자 입력 (한글 안전)
DELAY = "delay"      # 아무것도 하지 않고 기다림
TOUCH = "touch"      # 터치 접점 상태 변경


@dataclass(frozen=True)
class Step:
    """입력 한 단계. ``delay_ms`` 는 이 단계를 실행하기 **전** 대기 시간."""

    kind: str
    delay_ms: float = 0.0
    x: int = 0
    y: int = 0
    #: left | right | middle
    button: str = "left"
    #: 누름(True) / 뗌(False)
    down: bool = True
    #: 휠 칸 수 (양수=위)
    amount: int = 0
    #: 가상 키 코드
    vk: int = 0
    #: CHAR 단계의 문자
    char: str = ""
    #: TOUCH 단계의 접점 번호
    pointer: int = 0

    def describe(self) -> str:
        match self.kind:
            case "move":
                return f"이동 ({self.x}, {self.y})"
            case "button":
                return f"{self.button} 버튼 {'누름' if self.down else '뗌'}"
            case "wheel":
                return f"휠 {self.amount}"
            case "key":
                return f"키 0x{self.vk:02X} {'누름' if self.down else '뗌'}"
            case "char":
                return f"문자 {self.char!r}"
            case "delay":
                return f"{self.delay_ms:.0f}ms 대기"
            case "touch":
                state = "누름" if self.down else "뗌"
                return f"터치#{self.pointer} {state} ({self.x}, {self.y})"
            case _:
                return self.kind


def total_duration_ms(steps: list[Step]) -> float:
    """계획 전체에 걸리는 시간."""
    return sum(step.delay_ms for step in steps)


def summarize(steps: list[Step], limit: int = 6) -> str:
    """로그용 요약."""
    head = " → ".join(step.describe() for step in steps[:limit])
    tail = f" … (총 {len(steps)}단계)" if len(steps) > limit else ""
    return head + tail
