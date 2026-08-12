"""앱 진입점."""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from itda import APP_NAME, APP_NAME_EN, APP_VERSION
from itda.core import registry


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    # 창을 띄우지 않는 옵션들 — 빌드 결과를 검증할 때 쓴다
    if "--version" in argv:
        print(f"{APP_NAME}({APP_NAME_EN}) {APP_VERSION}")
        return 0
    if "--selftest" in argv:
        return selftest()

    # QApplication 보다 먼저 선언해야 한다. 늦으면 Windows 가 화면을 가상화해서
    # 캡처 해상도와 실제 픽셀이 어긋나고, 배율 150% 환경에서 클릭이 전부 빗나간다.
    from itda.vision.coords import enable_dpi_awareness

    dpi_mode = enable_dpi_awareness()

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, False)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME_EN)
    app.setApplicationDisplayName(f"{APP_NAME} ({APP_NAME_EN})")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("IT-DA")

    registry.load_builtins()

    from itda.gui.style import apply_theme
    from itda.gui.main_window import MainWindow

    apply_theme(app)

    window = MainWindow()
    window.show()

    from itda.core.events import BUS
    from itda.vision.coords import current_screens, describe

    BUS.log(f"화면: {describe(current_screens())} · DPI 모드 {dpi_mode}", level="info")

    # 명령줄로 프로젝트 폴더를 넘기면 바로 연다: python -m itda C:\path\to\project
    for arg in argv[1:]:
        if not arg.startswith("-"):
            window.open_project_path(arg)
            break

    return app.exec()


def selftest() -> int:
    """창 없이 핵심 경로를 점검한다.

    묶어서 배포한 실행 파일이 제대로 만들어졌는지 확인하는 용도다 — PyQt 플러그인, OpenCV,
    액션 레지스트리, 프로젝트 저장/로드가 전부 살아 있어야 통과한다.
    """
    import tempfile
    from pathlib import Path

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, fn) -> None:
        try:
            detail = fn() or ""
            checks.append((name, True, str(detail)))
        except Exception as e:
            checks.append((name, False, f"{type(e).__name__}: {e}"))

    def load_registry() -> str:
        registry.load_builtins()
        return f"액션 {len(registry.ACTION_TYPES)}개 · 노드 {len(registry.NODE_TYPES)}개"

    def vision() -> str:
        import cv2
        import numpy as np

        image = np.zeros((40, 40, 3), dtype=np.uint8)
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return f"OpenCV {cv2.__version__}"

    def gui() -> str:
        from PyQt6.QtCore import QT_VERSION_STR
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from itda.gui.main_window import MainWindow  # 임포트만으로 배선을 확인한다

        assert MainWindow is not None
        assert app is not None
        return f"Qt {QT_VERSION_STR}"

    def project_io() -> str:
        from itda.core.project import Project

        with tempfile.TemporaryDirectory() as folder:
            project = Project.create_default("자체 점검")
            project.save(Path(folder) / "p")
            reopened = Project.load(Path(folder) / "p")
            assert reopened.flow("main") is not None
        return "저장/열기 정상"

    def engine() -> str:
        from itda.engine.input import DryRunSender, planner
        from itda.engine.runner import Engine  # noqa: F401

        steps = planner.plan_click((10, 10), start=(0, 0))
        sender = DryRunSender()
        sender.run(steps)
        return f"입력 계획 {len(steps)}단계"

    def ocr_backend() -> str:
        from itda.vision import ocr

        return "Tesseract 있음" if ocr.is_available() else "Tesseract 없음 (OCR 액션만 제한)"

    check("액션 레지스트리", load_registry)
    check("영상 처리", vision)
    check("GUI 배선", gui)
    check("프로젝트 입출력", project_io)
    check("실행 엔진", engine)
    check("OCR 백엔드", ocr_backend)

    print(f"{APP_NAME}({APP_NAME_EN}) {APP_VERSION} 자체 점검")
    for name, ok, detail in checks:
        print(f"  [{'OK' if ok else '실패'}] {name}: {detail}")

    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        print(f"\n실패: {', '.join(failed)}")
        return 1
    print("\n모두 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
