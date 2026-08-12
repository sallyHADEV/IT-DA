"""입력 주입.

**계획(plan)과 주입(send)을 분리한다.**

* `plan_*` 함수는 순수 함수다. 좌표·시간·키 코드를 계산해 :class:`~itda.engine.input.steps.Step`
  목록을 돌려줄 뿐, 아무것도 건드리지 않는다. 그래서 테스트로 전부 검증할 수 있다.
* :class:`~itda.engine.input.sender.Sender` 가 그 목록을 실제로 주입한다. 테스트와 데모에서는
  기록만 하는 :class:`~itda.engine.input.sender.DryRunSender` 를 쓴다.

이렇게 나눠 두면 "마우스가 어디로 어떤 속도로 갈지" 를 실제로 마우스를 움직이지 않고 확인할 수
있다. 사람처럼 움직이기(:mod:`itda.core.humanize`)도 계획 단계에서 적용된다.
"""

from itda.engine.input.sender import DryRunSender, Sender, Win32Sender  # noqa: F401
from itda.engine.input.steps import Step  # noqa: F401
