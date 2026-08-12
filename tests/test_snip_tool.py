"""스크린샷 도구 — 끄는 동안에도 확대경이 보여야 한다.

드래그가 시작되면 확대경이 사라져서, 정작 끝나는 모서리를 픽셀 단위로 맞춰야 하는 순간에
아무것도 볼 수 없었다. 캡처 정확도가 목적인 도구에서 가장 필요할 때 정보가 없어지는 셈이다.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QPixmap
from PyQt6.QtWidgets import QApplication

from itda.gui.tools.snip_tool import SnipTool


@pytest.fixture
def tool(qapp):
    made = SnipTool()
    made.resize(400, 300)
    return made


def _drawn_during_paint(tool) -> list[str]:
    """paintEvent 가 무엇을 그렸는지 기록한다."""
    drawn: list[str] = []
    tool.draw_magnifier = lambda *a, **k: drawn.append("magnifier")
    tool.draw_crosshair = lambda *a, **k: drawn.append("crosshair")
    tool.draw_hint = lambda *a, **k: drawn.append("hint")
    tool.render(QPixmap(tool.size()))
    return drawn


def test_magnifier_is_shown_before_dragging(tool):
    assert "magnifier" in _drawn_during_paint(tool)


def test_magnifier_stays_while_dragging(tool):
    """여기가 원래 사라지던 지점이다."""
    tool.origin = QPoint(50, 50)
    tool.current = QPoint(200, 160)
    assert tool.selection().width() > 0  # 정말 끄는 중인 상태

    drawn = _drawn_during_paint(tool)

    assert "magnifier" in drawn
    assert "hint" in drawn  # 안내문도 계속 보여야 한다


def test_drag_reports_the_size_next_to_the_magnifier(tool):
    """끌고 있는 크기를 확대경 옆에 같이 적어 준다."""
    captured: list = []
    tool.draw_magnifier = lambda painter, extra_lines=None: captured.append(extra_lines)
    tool.origin = QPoint(50, 50)
    tool.current = QPoint(150, 130)
    tool.render(QPixmap(tool.size()))

    assert captured and captured[0]
    # QRect 는 경계를 포함하므로 50~150 은 101px 이다
    assert "101" in captured[0][0] and "81" in captured[0][0]


def test_no_size_line_before_the_drag_starts(tool):
    captured: list = []
    tool.draw_magnifier = lambda painter, extra_lines=None: captured.append(extra_lines)
    tool.render(QPixmap(tool.size()))

    assert captured == [None]
