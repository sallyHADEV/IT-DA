"""색과 테마.

레퍼런스 UI 킷을 따른다: 딥 네이비 면 + 코럴 악센트, 완전한 플랫(그라데이션·그림자 없음),
넉넉한 라운드 코너, 테두리는 최소한만.

캔버스가 화면 대부분을 차지하므로 캔버스는 패널보다 한 단계 어둡게 두어 노드 카드가 떠 보이게
한다. 실행 상태 색은 노드 테두리에만 쓰고 본문 색은 노드 타입 색을 유지한다 — 그래야 실행
중에도 무슨 노드인지 보인다.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication

#: 한글이 깨지지 않는 순서대로. 먼저 있는 것을 쓴다.
FONT_CANDIDATES = ("Malgun Gothic", "맑은 고딕", "Noto Sans KR", "Pretendard", "Segoe UI")

#: 폰트 DB가 비어 있을 때 직접 읽어 등록할 파일들.
#: Windows 의 offscreen 플랫폼 플러그인은 시스템 폰트 DB 대신 제네릭 DB를 쓰기 때문에
#: 글자가 전부 네모로 나온다. 헤드리스 테스트·스크린샷에서 이걸 막는다.
#: (환경변수 ``QT_QPA_FONTDIR`` 로도 되지만, 폴더 전체를 읽어 느리고 경로가 OS마다 다르다.)
FONT_FILES = (
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\gulim.ttc",
    r"C:\Windows\Fonts\batang.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
)


def ensure_fonts() -> str | None:
    """폰트가 하나도 없으면 한글 폰트를 직접 등록한다.

    Returns:
        등록한 글꼴 이름. 이미 폰트가 있거나 쓸 만한 파일을 못 찾으면 None.
    """
    if QFontDatabase.families():
        return None
    for path in FONT_FILES:
        if not Path(path).is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            return families[0]
    return None

# ---------------------------------------------------------------- 기본 팔레트
BG = QColor("#232936")          # 앱 바탕
SURFACE = QColor("#2a3040")     # 패널·카드
SURFACE_ALT = QColor("#313848") # 입력·헤더
SURFACE_HI = QColor("#3a4356")  # 호버
BORDER = QColor("#39415a")
TEXT = QColor("#e8eaee")
TEXT_DIM = QColor("#a3aab8")
TEXT_FAINT = QColor("#767e8f")

ACCENT = QColor("#ee7f63")      # 코럴 — 선택, 실행 중, 주요 동작
ACCENT_DIM = QColor("#c9674f")
ACCENT_SOFT = QColor("#8a5545")

# ---------------------------------------------------------------- 캔버스
CANVAS_BG = QColor("#1d222d")
GRID_MINOR = QColor("#232936")
GRID_MAJOR = QColor("#2b3243")

# ---------------------------------------------------------------- 노드
NODE_BG = QColor("#2a3040")
NODE_BG_SELECTED = QColor("#333c50")
NODE_TEXT = QColor("#e8eaee")
NODE_SUBTEXT = QColor("#98a1b2")
PORT = QColor("#6d7688")
PORT_HOVER = ACCENT
EDGE = QColor("#5d6678")
EDGE_SELECTED = ACCENT
EDGE_FIRED = QColor("#5fbf9c")

#: 노드 타입 색. 네이비 위에서 채도가 튀지 않는 값들로 맞춰 둔다.
NODE_TYPE_COLORS = {
    "start": "#4fa98a",
    "action_group": "#4a6fa5",
    "branch": "#c98a4b",
    "switch": "#b57b45",
    "loop": "#7a6ba8",
    "subflow": "#3f8f8f",
    "state_gate": "#ee7f63",  # 상황 인식이 이 도구의 간판 기능이라 악센트 색을 준다
    "end": "#6b7383",
    "note": "#71766b",
}

# ---------------------------------------------------------------- 실행 상태
STATUS_COLORS = {
    "idle": QColor("#39415a"),
    "pending": QColor("#8a8f9c"),
    "running": ACCENT,
    "ok": QColor("#5fbf9c"),
    "fail": QColor("#e05a54"),
    "skipped": QColor("#8c86a8"),
    "break": QColor("#d99a4e"),
}

LEVEL_COLORS = {
    "debug": QColor("#767e8f"),
    "info": QColor("#c6ccd8"),
    "warn": QColor("#d9a54e"),
    "error": QColor("#e05a54"),
}

_QSS = """
QWidget { font-size: 12px; }
QMainWindow::separator { background: #232936; width: 5px; height: 5px; }

QDockWidget { font-weight: 600; titlebar-close-icon: none; }
QDockWidget::title {
    background: #232936; color: #a3aab8; padding: 7px 10px;
    text-transform: uppercase; letter-spacing: 1px;
}

QToolBar { background: #232936; border: none; spacing: 3px; padding: 6px 8px; }
QToolBar QToolButton { padding: 5px 10px; border-radius: 8px; color: #d4d9e2; }
QToolBar QToolButton:hover { background: #313848; }
QToolBar QToolButton:pressed { background: #2a3040; }
QToolBar QToolButton:checked { background: #ee7f63; color: #1d222d; }
QToolBar QToolButton:disabled { color: #5c6474; }
QToolBar::separator { background: #39415a; width: 1px; margin: 5px 6px; }

QMenuBar { background: #232936; padding: 2px; }
QMenuBar::item { padding: 5px 10px; border-radius: 6px; }
QMenuBar::item:selected { background: #313848; }
QMenu { background: #2a3040; border: 1px solid #39415a; border-radius: 8px; padding: 5px; }
QMenu::item { padding: 6px 22px 6px 12px; border-radius: 5px; }
QMenu::item:selected { background: #ee7f63; color: #1d222d; }
QMenu::separator { height: 1px; background: #39415a; margin: 5px 8px; }

QStatusBar { background: #232936; color: #a3aab8; }
QStatusBar::item { border: none; }

QTabWidget::pane { border: none; background: #1d222d; }
QTabBar::tab {
    background: #232936; color: #98a1b2; padding: 7px 16px;
    border: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px;
}
QTabBar::tab:selected { background: #2a3040; color: #e8eaee; }
QTabBar::tab:hover:!selected { background: #2a3040; }

QTreeWidget, QTreeView, QListWidget, QListView, QTableWidget, QTableView,
QPlainTextEdit, QTextEdit {
    background: #2a3040; border: none; border-radius: 8px; padding: 2px;
    selection-background-color: #ee7f63; selection-color: #1d222d;
    alternate-background-color: #2d3444;
}
QTreeWidget::item, QListWidget::item { padding: 4px 3px; border-radius: 5px; }
QTreeWidget::item:hover, QListWidget::item:hover { background: #333c50; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #ee7f63; color: #1d222d; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {
    background: #313848; border: 1px solid #39415a; border-radius: 7px;
    padding: 5px 8px; color: #e8eaee; selection-background-color: #ee7f63;
}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover { background: #363e50; border-color: #4a5568; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #ee7f63; background: #313848;
}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: #5c6474; background: #2b3141; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox::down-arrow {
    image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid #a3aab8; margin-right: 6px;
}
QComboBox:editable QLineEdit {
    background: #282e3d; border: 1px solid #ee7f63; border-radius: 5px; padding: 3px 6px;
}
QComboBox QAbstractItemView {
    background: #2a3040; border: 1px solid #39415a; border-radius: 8px;
    selection-background-color: #ee7f63; selection-color: #1d222d; padding: 4px;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 14px; border: none; background: transparent; }

QPushButton {
    background: #313848; border: none; border-radius: 8px; padding: 6px 14px; color: #e8eaee;
}
QPushButton:hover { background: #3a4356; }
QPushButton:pressed { background: #2a3040; }
QPushButton:disabled { color: #5c6474; background: #2b3141; }
QPushButton[accent="true"] { background: #ee7f63; color: #1d222d; font-weight: 600; }
QPushButton[accent="true"]:hover { background: #f28d73; }
QPushButton[accent="true"]:pressed { background: #c9674f; }
QPushButton:checked { background: #ee7f63; color: #1d222d; }

QCheckBox, QRadioButton { spacing: 7px; }
QCheckBox::indicator, QRadioButton::indicator, QListWidget::indicator, QTreeWidget::indicator {
    width: 15px; height: 15px; background: #232936; border: 1px solid #5d6678; border-radius: 4px;
}
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked, QListWidget::indicator:checked, QTreeWidget::indicator:checked {
    background: #ee7f63; border-color: #ffffff;
}
QCheckBox::indicator:hover, QRadioButton::indicator:hover, QListWidget::indicator:hover, QTreeWidget::indicator:hover {
    background: #3a4356; border-color: #ee7f63;
}
QCheckBox::indicator:checked:hover, QListWidget::indicator:checked:hover { background: #f28d73; }
QListWidget::item:selected QListWidget::indicator, QTreeWidget::item:selected QTreeWidget::indicator {
    border: 2px solid #ffffff; background: #1d222d;
}
QListWidget::item:selected QListWidget::indicator:checked, QTreeWidget::item:selected QTreeWidget::indicator:checked {
    border: 2px solid #ffffff; background: #1d222d;
}

QGroupBox {
    background: #262c3a; border: none; border-radius: 10px;
    margin-top: 22px; padding: 12px 8px 10px 8px;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 4px; top: 2px; padding: 0 4px;
    color: #98a1b2; font-weight: 600;
}

QHeaderView::section {
    background: #262c3a; color: #98a1b2; border: none; padding: 6px 8px;
}
QTableView { gridline-color: #333c50; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #3a4356; border-radius: 5px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #4a5568; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #3a4356; border-radius: 5px; min-width: 28px; }
QScrollBar::handle:horizontal:hover { background: #4a5568; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QToolTip {
    background: #2a3040; color: #e8eaee; border: 1px solid #39415a;
    border-radius: 6px; padding: 5px 7px;
}
QSplitter::handle { background: #232936; }
QProgressBar { background: #313848; border: none; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: #ee7f63; border-radius: 6px; }
QSlider::groove:horizontal { background: #313848; height: 5px; border-radius: 3px; }
QSlider::handle:horizontal {
    background: #ee7f63; width: 14px; margin: -5px 0; border-radius: 7px;
}
QSlider::handle:horizontal:disabled { background: #5c6474; }
QSlider::groove:horizontal:disabled { background: #262c39; }
QLabel[role="hint"] { color: #767e8f; }
QLabel[role="title"] { color: #e8eaee; font-weight: 600; font-size: 13px; }
QFrame[role="card"] { background: #2a3040; border-radius: 10px; }
"""


def apply_theme(app: QApplication) -> None:
    """앱 전체에 네이비 플랫 테마를 적용한다."""
    app.setStyle("Fusion")

    loaded = ensure_fonts()
    families = set(QFontDatabase.families())
    for name in (*FONT_CANDIDATES, loaded):
        if name and name in families:
            app.setFont(QFont(name, 9))
            break

    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, BG)
    p.setColor(QPalette.ColorRole.WindowText, TEXT)
    p.setColor(QPalette.ColorRole.Base, SURFACE)
    p.setColor(QPalette.ColorRole.AlternateBase, SURFACE_ALT)
    p.setColor(QPalette.ColorRole.Text, TEXT)
    p.setColor(QPalette.ColorRole.Button, SURFACE_ALT)
    p.setColor(QPalette.ColorRole.ButtonText, TEXT)
    p.setColor(QPalette.ColorRole.Highlight, ACCENT)
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#1d222d"))
    p.setColor(QPalette.ColorRole.ToolTipBase, SURFACE)
    p.setColor(QPalette.ColorRole.ToolTipText, TEXT)
    p.setColor(QPalette.ColorRole.PlaceholderText, TEXT_FAINT)
    p.setColor(QPalette.ColorRole.Link, ACCENT)
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#5c6474"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#5c6474"))
    app.setPalette(p)
    app.setStyleSheet(_QSS)


def status_color(status: str) -> QColor:
    return STATUS_COLORS.get(status, STATUS_COLORS["idle"])


def node_color(type_id: str, fallback: str = "#4a6fa5") -> QColor:
    return QColor(NODE_TYPE_COLORS.get(type_id, fallback))


def lighten(color: QColor, amount: int = 30) -> QColor:
    return QColor(
        min(255, color.red() + amount),
        min(255, color.green() + amount),
        min(255, color.blue() + amount),
    )


def darken(color: QColor, amount: int = 30) -> QColor:
    return QColor(
        max(0, color.red() - amount),
        max(0, color.green() - amount),
        max(0, color.blue() - amount),
    )


def with_alpha(color: QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(alpha)
    return c
