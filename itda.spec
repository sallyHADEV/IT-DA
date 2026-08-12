# PyInstaller 빌드 명세.
#
#     python tools/build.py            (권장 — 아이콘 생성부터 검증까지)
#     pyinstaller itda.spec --noconfirm
#
# 기본은 onedir 다. onefile 은 실행할 때마다 임시 폴더에 통째로 풀어서 시작이 느리고,
# 매크로처럼 자주 켜는 프로그램에는 맞지 않는다. 배포는 폴더째 압축해 넘긴다.

from pathlib import Path

ROOT = Path(SPECPATH)
ICON = ROOT / "itda" / "resources" / "itda.ico"

# 개발 환경에 깔려 있지만 잇다가 쓰지 않는 무거운 것들 — 들어가면 용량만 커진다
EXCLUDES = [
    "streamlit", "pandas", "plotly", "altair", "pyarrow", "yfinance",
    "matplotlib", "scipy", "IPython", "notebook", "tkinter", "playwright",
    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtQml",
    "PyQt6.QtQuick", "PyQt6.Qt3DCore", "PyQt6.QtMultimedia", "PyQt6.QtBluetooth",
    "PyQt6.QtNetwork", "PyQt6.QtSql", "PyQt6.QtTest", "PyQt6.QtDesigner",
]

# import 부작용으로만 등록되는 모듈들 — PyInstaller 가 못 찾을 수 있다
HIDDEN = [
    "itda.actions",
    "itda.actions.data_actions",
    "itda.actions.flow_actions",
    "itda.actions.input_actions",
    "itda.actions.tool_actions",
    "itda.actions.vision_actions",
    "itda.core.conditions",
    "itda.core.nodes",
    "itda.engine.executors",
]

# 쓰지 않는데 따라 들어오는 큰 파일들. 지우면 50MB 넘게 줄어든다.
#   ffmpeg      — 동영상 입출력. 잇다는 화면만 찍는다.
#   opengl32sw  — Qt 의 소프트웨어 OpenGL. QWidget(래스터) 만 쓰므로 필요 없다.
#   Qt6Pdf      — PDF 출력. 안 쓴다.
#   Qt6Network / libcrypto / libssl — 네트워크. 잇다는 아무 데도 접속하지 않는다.
DROP_BINARIES = (
    "opencv_videoio_ffmpeg",
    "opengl32sw",
    "qt6pdf",
    "qt6network",
    "libcrypto-",
    "libssl-",
    "d3dcompiler_47",
)


def _trim(binaries):
    kept = []
    for entry in binaries:
        name = entry[0].lower()
        if any(marker in name for marker in DROP_BINARIES):
            continue
        kept.append(entry)
    return kept


analysis = Analysis(
    ["itda/__main__.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ICON), "itda/resources")] if ICON.exists() else [],
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

analysis.binaries = _trim(analysis.binaries)

pyz = PYZ(analysis.pure)

# 평소에 쓰는 창 프로그램 — 콘솔 없이 뜬다
app = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="itda",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICON) if ICON.exists() else None,
)

# 같은 코드의 콘솔 판. `itda-check.exe --selftest` 로 빌드 결과를 확인한다.
# 창 프로그램은 stdout 이 없어서 출력이 보이지 않기 때문에 따로 둔다.
checker = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="itda-check",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(ICON) if ICON.exists() else None,
)

collect = COLLECT(
    app,
    checker,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="itda",
)
