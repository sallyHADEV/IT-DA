"""캔버스 화면 이동(패닝).

플로우 캔버스와 액션 시퀀스 뷰가 같은 조작으로 움직여야 한다 — 가운데 버튼 드래그,
또는 Alt/Shift + 좌드래그. 이벤트는 뷰가 아니라 **``viewport()``** 로 보내야 핸들러에
도달한다(QAbstractScrollArea 구조 때문. 뷰로 보내면 아무 일도 안 일어나 통과해 버린다).
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from itda.core import registry
from itda.core.model import Action, Node
from itda.gui.canvas.scene import FlowScene
from itda.gui.canvas.sequence_scene import SequenceScene, SequenceView
from itda.gui.canvas.view import FlowView

NO_MOD = Qt.KeyboardModifier.NoModifier
START = QPoint(200, 150)
END = QPoint(150, 100)


def _mouse(kind, pos, button, buttons, mods=NO_MOD) -> QMouseEvent:
    return QMouseEvent(kind, QPointF(pos), QPointF(pos), button, buttons, mods)


def _drag(view, button, mods, start=START, end=END) -> tuple[int, int, bool]:
    """끌어 보고 (가로이동, 세로이동, 드래그 중 손 모양이었나) 를 돌려준다."""
    viewport = view.viewport()
    QApplication.sendEvent(
        viewport, _mouse(QMouseEvent.Type.MouseButtonPress, start, button, button, mods)
    )
    QApplication.sendEvent(
        viewport,
        _mouse(QMouseEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, button, mods),
    )
    grabbed = view.cursor().shape() == Qt.CursorShape.ClosedHandCursor
    before = (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
    QApplication.sendEvent(
        viewport,
        _mouse(QMouseEvent.Type.MouseButtonRelease, end, button, Qt.MouseButton.NoButton, mods),
    )
    return before, grabbed


@pytest.fixture
def flow_view(qapp, project):
    scene = FlowScene(project, project.flow("main"), "main")
    view = FlowView(scene)
    view.resize(400, 300)
    view.show()
    scene.setSceneRect(-2000, -2000, 4000, 4000)  # 스크롤 여지를 만든다
    QApplication.processEvents()
    return view


def _reset(view, x: int = 500, y: int = 500) -> tuple[int, int]:
    view._panning = False
    view.horizontalScrollBar().setValue(x)
    view.verticalScrollBar().setValue(y)
    return view.horizontalScrollBar().value(), view.verticalScrollBar().value()


@pytest.mark.parametrize(
    "button,mods,label",
    [
        (Qt.MouseButton.MiddleButton, NO_MOD, "가운데 버튼"),
        (Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, "Alt+좌클릭"),
        (Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, "Shift+좌클릭"),
    ],
)
def test_drag_moves_the_canvas(flow_view, button, mods, label):
    h0, v0 = _reset(flow_view)
    (during_h, during_v), grabbed = _drag(flow_view, button, mods)

    assert (during_h - h0, during_v - v0) == (50, 50), label
    assert grabbed, f"{label} 드래그 중에는 손 모양이어야 한다"
    assert flow_view.cursor().shape() == Qt.CursorShape.ArrowCursor  # 놓으면 복원
    assert flow_view._panning is False


def test_plain_left_drag_does_not_pan(flow_view):
    """수식키 없는 좌드래그는 고무줄 선택이다 — 화면이 움직이면 안 된다."""
    h0, v0 = _reset(flow_view)
    (during_h, during_v), grabbed = _drag(flow_view, Qt.MouseButton.LeftButton, NO_MOD)

    assert (during_h, during_v) == (h0, v0)
    assert not grabbed


def test_rubber_band_selection_still_works(qapp, project):
    """팬이 좌드래그를 가로채 선택을 망가뜨리지 않았는지."""
    flow = project.flow("main")
    for i in range(3):
        flow.add_node(Node(type="action_group", title=f"N{i}", x=i * 40, y=0))
    scene = FlowScene(project, flow, "main")
    view = FlowView(scene)
    view.resize(600, 400)
    view.show()
    QApplication.processEvents()
    view.fit_all()
    QApplication.processEvents()

    box = None
    for item in scene.node_items.values():
        rect = item.sceneBoundingRect()
        box = rect if box is None else box.united(rect)
    top_left = view.mapFromScene(box.topLeft()) - QPoint(20, 20)
    bottom_right = view.mapFromScene(box.bottomRight()) + QPoint(20, 20)

    scene.clearSelection()
    _drag(view, Qt.MouseButton.LeftButton, NO_MOD, top_left, bottom_right)

    assert len(scene.selectedItems()) >= len(scene.node_items)


def test_panning_survives_the_run_lock(flow_view):
    """실행 중에는 편집만 잠근다 — 실행 상황을 따라가려면 화면 이동은 살아 있어야 한다."""
    flow_view.set_read_only(True)
    h0, v0 = _reset(flow_view)

    (during_h, _), _ = _drag(flow_view, Qt.MouseButton.MiddleButton, NO_MOD)

    assert during_h - h0 == 50


def test_sequence_view_pans_the_same_way(qapp, project):
    node = project.flow("main").nodes[1]
    node.actions = [
        Action(type="sleep", params=registry.action_params("sleep", None)) for _ in range(30)
    ]
    scene = FlowScene(project, project.flow("main"), "main")
    view = SequenceView(SequenceScene(scene, node))
    view.resize(300, 200)
    view.show()
    QApplication.processEvents()

    assert view.verticalScrollBar().maximum() > 0, "스크롤 여지가 있어야 시험이 된다"
    _reset(view, 0, 200)
    y0 = view.verticalScrollBar().value()

    (_, during_v), grabbed = _drag(view, Qt.MouseButton.MiddleButton, NO_MOD)

    assert during_v - y0 == 50
    assert grabbed
    assert view.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_both_views_share_one_implementation():
    """한쪽만 고치고 다른 쪽을 잊는 일이 없도록 구현은 한 곳이어야 한다."""
    from itda.gui.canvas.panning import PanMixin

    assert issubclass(FlowView, PanMixin)
    assert issubclass(SequenceView, PanMixin)
    for name in ("mousePressEvent", "mouseMoveEvent", "mouseReleaseEvent"):
        assert name not in FlowView.__dict__, f"{name} 을 다시 따로 구현했다"
        assert name not in SequenceView.__dict__, f"{name} 을 다시 따로 구현했다"
