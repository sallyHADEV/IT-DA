"""자동 정렬 테스트.

좋은 배치의 조건: 흐름이 왼쪽에서 오른쪽으로 가고, 같은 열에서 겹치지 않으며,
선이 덜 꼬인다. 마지막 것은 교차 수로 잰다.
"""

from __future__ import annotations

import pytest

from itda.gui.canvas.layout import compute_positions, count_crossings


def positions_of(nodes, edges, start="A"):
    return compute_positions(nodes, edges, start_id=start)


def columns(result) -> dict[float, list[str]]:
    grouped: dict[float, list[str]] = {}
    for node, (x, _y) in result.items():
        grouped.setdefault(x, []).append(node)
    return grouped


# ---------------------------------------------------------------- 기본


def test_empty_graph():
    assert compute_positions([], []) == {}


def test_single_node_at_origin():
    assert compute_positions(["A"], [], start_id="A") == {"A": (0.0, 0.0)}


def test_chain_goes_left_to_right():
    result = positions_of(["A", "B", "C"], [("A", "B"), ("B", "C")])
    assert result["A"][0] < result["B"][0] < result["C"][0]


def test_every_node_is_placed():
    nodes = ["A", "B", "C", "D"]
    result = positions_of(nodes, [("A", "B"), ("A", "C")])
    assert set(result) == set(nodes)


def test_isolated_nodes_do_not_overlap():
    result = compute_positions(["A", "B", "C"], [], start_id="A")
    assert len(set(result.values())) == 3


def test_branch_children_share_a_column_and_differ_in_row():
    result = positions_of(["A", "B", "C"], [("A", "B"), ("A", "C")])
    assert result["B"][0] == result["C"][0]
    assert result["B"][1] != result["C"][1]


def test_join_places_the_target_after_both_parents():
    result = positions_of(
        ["A", "B", "C", "D"], [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
    )
    assert result["D"][0] > result["B"][0]
    assert result["D"][0] > result["C"][0]


# ---------------------------------------------------------------- 순환 / 되돌림


def test_cycle_does_not_hang_or_stack_nodes():
    """재시도 루프(C → B)가 있어도 멈추지 않고, 노드가 겹치지 않아야 한다."""
    result = positions_of(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "B")])
    assert len(set(result.values())) == 3


def test_self_loop_is_ignored():
    result = positions_of(["A", "B"], [("A", "B"), ("B", "B")])
    assert result["A"][0] < result["B"][0]


def test_edges_to_unknown_nodes_are_ignored():
    result = positions_of(["A", "B"], [("A", "B"), ("B", "없는노드")])
    assert set(result) == {"A", "B"}


def test_long_back_edge_keeps_forward_flow():
    nodes = list("ABCDE")
    edges = [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E"), ("E", "B")]
    result = positions_of(nodes, edges)
    assert result["B"][0] < result["C"][0] < result["D"][0] < result["E"][0]


# ---------------------------------------------------------------- 겹침 / 교차


def test_no_two_nodes_share_a_position():
    nodes = list("ABCDEFGH")
    edges = [
        ("A", "B"), ("A", "C"), ("B", "D"), ("C", "D"),
        ("D", "E"), ("D", "F"), ("E", "G"), ("F", "G"), ("G", "H"),
    ]
    result = positions_of(nodes, edges)
    assert len(set(result.values())) == len(nodes)


def test_crossings_are_reduced_versus_naive_depth_layout():
    """예전 방식(깊이 + 이름순)보다 선이 덜 꼬여야 한다."""
    nodes = list("ABCDEF")
    edges = [
        ("A", "B"), ("A", "C"),
        ("B", "F"), ("C", "E"), ("A", "D"), ("D", "E"),
    ]
    smart = positions_of(nodes, edges)

    # 순진한 배치: 깊이로 열을 나누고 이름순으로 세로 배치
    depth = {"A": 0, "B": 1, "C": 1, "D": 1, "E": 2, "F": 2}
    naive: dict[str, tuple[float, float]] = {}
    rows: dict[int, int] = {}
    for node in sorted(nodes):
        column = depth[node]
        row = rows.get(column, 0)
        rows[column] = row + 1
        naive[node] = (column * 260.0, row * 110.0)

    assert count_crossings(smart, edges) <= count_crossings(naive, edges)


def test_long_edge_gets_room_via_dummy_nodes():
    """A → D 처럼 레이어를 건너뛰는 간선이 다른 노드를 관통하지 않게 자리를 비운다."""
    nodes = list("ABCD")
    edges = [("A", "B"), ("B", "C"), ("C", "D"), ("A", "D")]
    result = positions_of(nodes, edges)

    assert result["A"][0] < result["B"][0] < result["C"][0] < result["D"][0]
    assert len(set(result.values())) == 4


def test_count_crossings_basics():
    edges = [("A", "D"), ("B", "C")]
    crossed = {"A": (0, 0), "B": (0, 110), "C": (260, 0), "D": (260, 110)}
    parallel = {"A": (0, 0), "B": (0, 110), "C": (260, 110), "D": (260, 0)}
    assert count_crossings(crossed, edges) == 1
    assert count_crossings(parallel, edges) == 0


# ---------------------------------------------------------------- 씬 연동


def test_scene_auto_layout_uses_the_new_algorithm(scene):
    from PyQt6.QtCore import QPointF

    from itda.gui.commands import AddEdgeCommand

    flow = scene.flow
    start = flow.start_node()
    first = flow.nodes[1]
    second = scene.add_node("action_group", QPointF(0, 0))
    third = scene.add_node("action_group", QPointF(0, 0))

    for src, dst in ((first.id, second.id), (first.id, third.id)):
        edge = flow.connect(src, "ok", dst)
        flow.edges.remove(edge)
        scene.undo_stack.push(AddEdgeCommand(scene, edge))

    scene.auto_layout()

    placed = {n.id: (n.x, n.y) for n in flow.nodes}
    assert len(set(placed.values())) == len(flow.nodes)  # 겹치지 않는다
    assert placed[start.id][0] < placed[first.id][0]     # 시작이 맨 왼쪽
    assert placed[second.id][0] == placed[third.id][0]   # 형제는 같은 열


def test_scene_auto_layout_is_undoable(scene):
    before = [(n.x, n.y) for n in scene.flow.nodes]
    scene.auto_layout()
    scene.undo_stack.undo()
    assert [(n.x, n.y) for n in scene.flow.nodes] == before
