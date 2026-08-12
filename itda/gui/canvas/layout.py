"""계층적 자동 정렬 (Sugiyama).

깊이만으로 열을 나누면 합류·역방향 간선이 있는 순간 노드가 겹치고 선이 꼬인다.
교차를 줄이는 표준 절차를 따른다.

1. **역방향 간선 뒤집기** — 되돌아오는 연결(재시도 루프)을 임시로 반대로 봐서 비순환으로 만든다.
2. **레이어 배정** — 들어오는 간선이 모두 앞 레이어에 오도록 세로줄(열)을 정한다.
3. **더미 노드** — 레이어를 건너뛰는 긴 간선을 한 칸씩 쪼갠다. 선이 다른 노드를 관통하지 않는다.
4. **교차 줄이기** — 이웃 레이어의 중앙값으로 순서를 다시 매긴다(median heuristic, 몇 번 반복).
5. **좌표 배정** — 열 간격과 행 간격을 곱해 실제 위치로.

외부 의존성(graphviz)은 쓰지 않는다 — 배포를 단순하게 유지하려고.
"""

from __future__ import annotations

from dataclasses import dataclass, field

COLUMN_WIDTH = 260
ROW_HEIGHT = 110
SWEEP_PASSES = 4


@dataclass
class _Graph:
    """정렬 계산용 가벼운 그래프. 노드 id 만 다룬다."""

    nodes: list[str]
    edges: list[tuple[str, str]]
    reversed_edges: set[tuple[str, str]] = field(default_factory=set)

    def successors(self, node: str) -> list[str]:
        return [dst for src, dst in self.edges if src == node]

    def predecessors(self, node: str) -> list[str]:
        return [src for src, dst in self.edges if dst == node]


def compute_positions(
    node_ids: list[str],
    edges: list[tuple[str, str]],
    start_id: str | None = None,
    column_width: int = COLUMN_WIDTH,
    row_height: int = ROW_HEIGHT,
) -> dict[str, tuple[float, float]]:
    """노드 배치를 계산한다. 결과는 ``{노드 id: (x, y)}``."""
    if not node_ids:
        return {}

    graph = _Graph(nodes=list(node_ids), edges=_clean(edges, set(node_ids)))
    _break_cycles(graph, start_id)

    layers = _assign_layers(graph, start_id)
    order = _initial_order(graph, layers, start_id)
    order = _reduce_crossings(graph, order)

    positions: dict[str, tuple[float, float]] = {}
    for layer_index in sorted(order):
        for row, node in enumerate(order[layer_index]):
            if node.startswith("__dummy"):
                continue
            positions[node] = (float(layer_index * column_width), float(row * row_height))
    return positions


def count_crossings(
    positions: dict[str, tuple[float, float]], edges: list[tuple[str, str]]
) -> int:
    """배치 품질 지표 — 간선이 서로 몇 번 교차하는지(같은 열 구간 안에서)."""
    crossings = 0
    spans = []
    for src, dst in edges:
        if src not in positions or dst not in positions:
            continue
        (x1, y1), (x2, y2) = positions[src], positions[dst]
        if x1 == x2:
            continue
        spans.append((x1, y1, x2, y2))

    for i, (ax1, ay1, ax2, ay2) in enumerate(spans):
        for bx1, by1, bx2, by2 in spans[i + 1:]:
            if (ax1, ax2) != (bx1, bx2):
                continue  # 같은 열 사이를 지나는 것끼리만 비교
            if (ay1 - by1) * (ay2 - by2) < 0:
                crossings += 1
    return crossings


# ---------------------------------------------------------------- 단계별


def _clean(edges: list[tuple[str, str]], known: set[str]) -> list[tuple[str, str]]:
    """없는 노드를 가리키거나 자기 자신으로 도는 간선을 버린다."""
    seen = set()
    result = []
    for src, dst in edges:
        if src not in known or dst not in known or src == dst:
            continue
        if (src, dst) in seen:
            continue
        seen.add((src, dst))
        result.append((src, dst))
    return result


def _break_cycles(graph: _Graph, start_id: str | None) -> None:
    """깊이 우선으로 돌며 뒤로 가는 간선을 뒤집어 비순환으로 만든다."""
    visiting: set[str] = set()
    done: set[str] = set()
    flipped: list[tuple[str, str]] = []

    def walk(node: str) -> None:
        visiting.add(node)
        for dst in list(graph.successors(node)):
            if dst in visiting:
                flipped.append((node, dst))  # 되돌아오는 간선
            elif dst not in done:
                walk(dst)
        visiting.discard(node)
        done.add(node)

    roots = [start_id] if start_id in graph.nodes else []
    roots += [n for n in graph.nodes if not graph.predecessors(n)]
    for node in roots + graph.nodes:
        if node not in done:
            walk(node)

    for src, dst in flipped:
        graph.edges.remove((src, dst))
        if (dst, src) not in graph.edges:
            graph.edges.append((dst, src))
            graph.reversed_edges.add((dst, src))


def _assign_layers(graph: _Graph, start_id: str | None) -> dict[str, int]:
    """가장 긴 경로 기준 레이어. 들어오는 간선은 모두 앞 레이어에서 온다."""
    layers: dict[str, int] = {}

    def depth(node: str, guard: frozenset[str] = frozenset()) -> int:
        if node in layers:
            return layers[node]
        if node in guard:
            return 0
        parents = graph.predecessors(node)
        value = 0 if not parents else 1 + max(
            depth(p, guard | {node}) for p in parents
        )
        layers[node] = value
        return value

    for node in graph.nodes:
        depth(node)

    # 시작 노드는 항상 맨 왼쪽
    if start_id in layers and layers[start_id] != 0:
        shift = layers[start_id]
        for node in layers:
            layers[node] = max(0, layers[node] - shift)
        layers[start_id] = 0
    return layers


def _initial_order(
    graph: _Graph, layers: dict[str, int], start_id: str | None
) -> dict[int, list[str]]:
    """레이어별 초기 순서 + 긴 간선을 더미로 쪼갠다."""
    order: dict[int, list[str]] = {}
    for node, layer in layers.items():
        order.setdefault(layer, []).append(node)
    for layer in order:
        order[layer].sort(key=lambda n: (n != start_id, n))

    dummy_count = 0
    for src, dst in list(graph.edges):
        gap = layers[dst] - layers[src]
        if gap <= 1:
            continue
        previous = src
        for step in range(1, gap):
            dummy = f"__dummy{dummy_count}"
            dummy_count += 1
            layer = layers[src] + step
            layers[dummy] = layer
            order.setdefault(layer, []).append(dummy)
            graph.edges.append((previous, dummy))
            previous = dummy
        graph.edges.remove((src, dst))
        graph.edges.append((previous, dst))
    return order


def _reduce_crossings(graph: _Graph, order: dict[int, list[str]]) -> dict[int, list[str]]:
    """이웃 레이어의 중앙값으로 순서를 다시 매긴다. 앞뒤로 몇 번 훑는다."""
    layer_numbers = sorted(order)
    for sweep in range(SWEEP_PASSES):
        forward = sweep % 2 == 0
        sequence = layer_numbers if forward else list(reversed(layer_numbers))
        for layer in sequence:
            neighbours = graph.predecessors if forward else graph.successors
            reference = order.get(layer - 1 if forward else layer + 1, [])
            if not reference:
                continue
            index = {node: i for i, node in enumerate(reference)}

            def key(node: str) -> tuple[float, str]:
                spots = [index[n] for n in neighbours(node) if n in index]
                return (_median(spots), node)

            order[layer] = sorted(order[layer], key=key)
    return order


def _median(values: list[int]) -> float:
    """이웃이 없으면 맨 뒤로 보낸다."""
    if not values:
        return float("inf")
    values = sorted(values)
    middle = len(values) // 2
    if len(values) % 2:
        return float(values[middle])
    return (values[middle - 1] + values[middle]) / 2
