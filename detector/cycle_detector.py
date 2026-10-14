"""Deadlock detection = cycle detection on the Wait-For Graph, using our own DFS.

The DFS colours every node:

* WHITE - not visited yet
* GRAY  - on the current DFS path (the "recursion stack")
* BLACK - fully explored, no cycle can be found through it that we have not seen

Meeting a GRAY node while exploring an edge means we walked back onto our own
current path, i.e. we found a cycle: the slice of the path from that node on.
NetworkX is used only to *store* the graph, never to find cycles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Hashable, List, Tuple

WHITE, GRAY, BLACK = 0, 1, 2

Cycle = List[Hashable]  # [P1, P2] means P1 -> P2 -> P1


def _canonical(cycle: Cycle) -> Cycle:
    """Rotate a cycle so it starts at its smallest node (stable identity)."""
    start = min(range(len(cycle)), key=lambda i: str(cycle[i]))
    return cycle[start:] + cycle[:start]


def find_cycles(graph) -> List[Cycle]:
    """Return the cycles found by a depth-first search of ``graph``.

    * Handles empty and disconnected graphs (every node is used as a start).
    * One cycle is reported per DFS back edge; a cycle of length 1 is a self-loop
      (the simulator forbids it, but a hand-built graph may contain one).
    * Deterministic: nodes and successors are visited in sorted order.
    * Recursive, which is fine for classroom-sized graphs.
    """
    color = {node: WHITE for node in graph.nodes}
    path: List[Hashable] = []
    cycles: List[Cycle] = []
    seen = set()

    def visit(u: Hashable) -> None:
        color[u] = GRAY
        path.append(u)
        for v in sorted(graph.successors(u), key=str):
            if color[v] == WHITE:
                visit(v)
            elif color[v] == GRAY:  # back edge u -> v closes a cycle
                cycle = _canonical(path[path.index(v):])
                key = tuple(cycle)
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
        path.pop()
        color[u] = BLACK

    for node in sorted(graph.nodes, key=str):
        if color[node] == WHITE:
            visit(node)
    return cycles


def cycle_edges(graph, cycle: Cycle) -> List[Tuple[Hashable, Hashable, object]]:
    """The edges (waiter, holder, lock) that make up ``cycle``."""
    return [
        (u, v, graph.edges[u, v].get("lock"))
        for u, v in zip(cycle, cycle[1:] + cycle[:1])
    ]


def format_cycle(cycle: Cycle) -> str:
    """``['P1', 'P2']`` -> ``'P1 -> P2 -> P1'`` (with arrow characters)."""
    return " → ".join(str(n) for n in cycle + cycle[:1])


@dataclass
class DetectionResult:
    cycles: List[Cycle]
    #: Cycles that were not part of the previous detection run.
    new_cycles: List[Cycle] = field(default_factory=list)

    @property
    def deadlock(self) -> bool:
        return bool(self.cycles)

    @property
    def repeated(self) -> bool:
        """True if deadlocks exist but all were already reported before."""
        return self.deadlock and not self.new_cycles


class CycleDetector:
    """Stateful wrapper that avoids re-announcing an unchanged deadlock.

    A cycle is identified by its edges *and* their locks.  It counts as "new"
    unless the immediately preceding detection run reported the same cycle, so
    a deadlock that is resolved and later recreated is reported again.
    """

    def __init__(self) -> None:
        self._last = frozenset()

    def detect(self, graph) -> DetectionResult:
        cycles = find_cycles(graph)
        signatures = {tuple(cycle_edges(graph, c)): c for c in cycles}
        new = [c for sig, c in signatures.items() if sig not in self._last]
        self._last = frozenset(signatures)
        return DetectionResult(cycles, new)

    def reset(self) -> None:
        self._last = frozenset()
