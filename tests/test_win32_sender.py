"""실주입기의 구조체 조립.

**이 경로는 지금까지 테스트가 한 번도 밟지 않았다.** conftest 가 `Win32Sender.apply` 를
막아 두었기 때문인데(사용자 마우스를 움직이면 안 되니 당연하다), 그 바람에 SendInput 에
넘길 구조체를 만드는 코드에 버그가 있어도 아무도 몰랐다 — 실제로 `dwExtraInfo` 에 `None`
을 넣고 있었고, 클릭할 때마다
``TypeError: 'NoneType' object cannot be interpreted as an integer`` 로 터졌다.

여기서는 **SendInput 만 가짜로 바꿔** 구조체 조립까지는 진짜로 시키고 주입만 막는다.
"""

from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 전용")

from itda.engine.input.sender import Win32Sender  # noqa: E402
from itda.engine.input.steps import Step  # noqa: E402


@pytest.fixture
def sender(monkeypatch):
    """SendInput 을 가로챈 실주입기. 구조체는 진짜로 만들지만 아무것도 주입하지 않는다."""
    from itda.vision.coords import Rect, ScreenInfo

    sent: list = []
    made = Win32Sender(screens=[ScreenInfo(name="가짜", logical=Rect(0, 0, 1920, 1080))])

    def fake_send_input(count, pointer, size):
        sent.append((count, size))
        return 1  # 성공했다고 알린다

    monkeypatch.setattr(made._user32, "SendInput", fake_send_input)
    made.sent = sent
    return made


def _apply(sender, step) -> None:
    """안전장치를 우회해 **진짜** apply 를 부른다. 주입은 가짜 SendInput 이 막는다."""
    type(sender)._real_apply(sender, step)


def test_move_builds_a_valid_input_struct(sender):
    _apply(sender, Step("move", x=100, y=200))
    assert len(sender.sent) == 1


@pytest.mark.parametrize("button", ["left", "right", "middle"])
@pytest.mark.parametrize("down", [True, False])
def test_button_builds_a_valid_input_struct(sender, button, down):
    """클릭이 여기서 터졌다 — dwExtraInfo 에 None 을 넣고 있었다."""
    _apply(sender, Step("button", button=button, down=down))
    assert len(sender.sent) == 1


def test_wheel_builds_a_valid_input_struct(sender):
    _apply(sender, Step("wheel", amount=-3))
    assert len(sender.sent) == 1


def test_key_builds_a_valid_input_struct(sender):
    _apply(sender, Step("key", vk=0x41, down=True))
    _apply(sender, Step("key", vk=0x41, down=False))
    assert len(sender.sent) == 2


def test_korean_characters_go_through_as_unicode(sender):
    """한글은 입력기 상태와 무관하게 유니코드로 넣는다 — 글자당 누름/뗌 두 번."""
    _apply(sender, Step("char", char="가"))
    assert len(sender.sent) == 2


def test_a_whole_click_sequence_builds(sender):
    """계획부터 주입까지 실제 클릭 한 번이 통째로 조립되는지."""
    from itda.core.humanize import HumanProfile
    from itda.core.timing import TimingProfile
    from itda.engine.input import planner

    steps = planner.plan_click(
        (400, 300), start=(10, 10), human=HumanProfile(), timing=TimingProfile()
    )
    for step in steps:
        _apply(sender, step)

    assert len(sender.sent) >= 3  # 이동 여러 번 + 누름 + 뗌
