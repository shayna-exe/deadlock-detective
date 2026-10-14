"""Build the Wait-For Graph (WFG) from a simulation state.

Nodes are processes.  A directed edge ``P1 -> P2`` means "P1 is blocked waiting
for a lock that P2 currently holds"; the edge keeps the lock in ``lock``.
This module only *builds* the graph; finding cycles is the detector's job.
"""
from __future__ import annotations

import networkx as nx

from .lock_state import LockState


def build_wait_for_graph(state: LockState) -> "nx.DiGraph":
    graph = nx.DiGraph()
    for proc in state.processes:
        graph.add_node(
            proc,
            status=state.status_of(proc).value,
            holds=tuple(state.held_by(proc)),
            waiting_for=state.waiting_for(proc),
        )
    for proc in state.blocked_processes():
        lock = state.waiting_for(proc)
        holder = state.owner_of(lock)
        if holder is None:  # cannot happen: a lock with waiters always has an owner
            continue
        graph.add_edge(proc, holder, lock=lock)
    return graph


def graph_to_dict(graph: "nx.DiGraph") -> dict:
    """Plain-data form of a WFG (used by reports)."""
    return {
        "nodes": [
            {
                "process": n,
                "status": d.get("status"),
                "holds": list(d.get("holds", ())),
                "waiting_for": d.get("waiting_for"),
            }
            for n, d in graph.nodes(data=True)
        ],
        "edges": [
            {"from": u, "to": v, "lock": d.get("lock")} for u, v, d in graph.edges(data=True)
        ],
    }
