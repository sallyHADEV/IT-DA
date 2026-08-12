"""테스트 공통 설정.

GUI 테스트는 오프스크린 플랫폼에서 돌린다. 창이 뜨지 않으므로 CI 에서도 그대로 동작한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from itda.core import registry  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _load_builtins():
    registry.load_builtins()


@pytest.fixture(scope="session", autouse=True)
def _isolate_settings(tmp_path_factory):
    """테스트가 사용자의 실제 설정(최근 프로젝트 등)을 건드리지 않게 한다.

    격리하지 않으면 테스트가 임시 폴더 경로를 '최근 프로젝트' 로 저장해 버리고,
    다음 실행 때 그 죽은 경로를 열려다 실패한다. 실제로 겪은 문제라 못을 박아 둔다.
    """
    from PyQt6.QtCore import QSettings

    folder = tmp_path_factory.mktemp("settings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(folder)
    )
    yield


@pytest.fixture(scope="session", autouse=True)
def _forbid_real_input():
    """테스트가 실제 마우스·키보드·터치를 건드리면 즉시 실패시킨다.

    입력 계층은 계획(pure)과 주입(side-effect)이 분리돼 있어서 테스트는 DryRunSender 만
    쓴다. 그 약속이 깨지는 순간 조용히 사용자의 마우스가 움직이는 대신 테스트가 터지도록
    실주입 경로를 막아 둔다.
    """
    from itda.engine import window as window_module
    from itda.engine.input import sender as sender_module
    from itda.engine.input import touch as touch_module

    def refuse(*_args, **_kwargs):
        raise AssertionError(
            "테스트에서 실제 입력 주입이 호출되었습니다. DryRunSender 를 쓰세요."
        )

    originals = (
        sender_module.Win32Sender.apply,
        touch_module.TouchInjector.flush,
        window_module.WindowController.apply,
    )
    # 진짜 구현을 남겨 둔다. SendInput 자체를 가짜로 막고 **구조체 조립까지만** 시험하는
    # 테스트가 있어서다(tests/test_win32_sender.py) — 그 경로에 버그가 있어도 이 안전장치
    # 때문에 아무도 못 밟고 있었다.
    sender_module.Win32Sender._real_apply = originals[0]
    sender_module.Win32Sender.apply = refuse
    touch_module.TouchInjector.flush = refuse
    window_module.WindowController.apply = refuse  # 남의 창을 옮기지 않는다
    try:
        yield
    finally:
        (
            sender_module.Win32Sender.apply,
            touch_module.TouchInjector.flush,
            window_module.WindowController.apply,
        ) = originals


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication

    from itda.gui.style import ensure_fonts

    app = QApplication.instance() or QApplication([])
    # offscreen 플랫폼은 시스템 폰트를 못 읽는다. 등록해 두지 않으면 위젯을 캡처했을 때
    # 글자가 전부 네모로 나와 화면 확인이 불가능하다.
    ensure_fonts()
    yield app


@pytest.fixture
def project():
    from itda.core.project import Project

    return Project.create_default("테스트 프로젝트")


@pytest.fixture
def scene(qapp, project):
    """main 플로우를 그리는 씬."""
    from itda.gui.canvas.scene import FlowScene

    return FlowScene(project, project.flow("main"), "main")
