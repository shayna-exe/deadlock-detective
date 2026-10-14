"""Actionable recommendations, derived from the detected cycles and warnings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from detector.cycle_detector import cycle_edges
from detector.lock_order_analyzer import LockOrderWarning

CONFIRMED = "confirmed deadlock"
RISK = "potential risk"
GENERAL = "general"


@dataclass(frozen=True)
class Recommendation:
    category: str
    text: str

    def to_dict(self) -> dict:
        return {"category": self.category, "text": self.text}


def recommend(graph, cycles: Sequence[Sequence[str]],
              warnings: Sequence[LockOrderWarning]) -> List[Recommendation]:
    recs: List[Recommendation] = []
    for cycle in cycles:
        cycle = list(cycle)
        locks = sorted({lock for _, _, lock in cycle_edges(graph, cycle)})
        order = " before ".join(locks)
        recs.append(Recommendation(CONFIRMED, (
            f"Break the current deadlock ({' and '.join(cycle)}) with the recovery panel: abort one "
            "of these processes so its locks are released and the others can continue."
        )))
        recs.append(Recommendation(CONFIRMED, (
            f"Prevent it from recurring: make every process acquire the locks involved "
            f"({', '.join(locks)}) in one fixed global order, e.g. {order}."
        )))
    for w in warnings:
        a, b = w.locks
        recs.append(Recommendation(RISK, (
            f"Review the code paths of {w.first.process} (step {w.first.step}) and "
            f"{w.second.process} (step {w.second.step}): they take locks {a} and {b} in opposite "
            f"orders. Pick one order (for example {a} before {b}) and use it everywhere."
        )))
    if cycles or warnings:
        recs.extend([
            Recommendation(GENERAL, "Acquire shared locks in a consistent global order (a lock hierarchy)."),
            Recommendation(GENERAL, "Reduce unnecessary lock holding: release a lock before requesting another when you can."),
            Recommendation(GENERAL, "Consider safer designs where appropriate: one coarser lock, try-lock with back-off, or lock-free/message-passing structures."),
            Recommendation(GENERAL, "Edit the simulated event sequence to follow the new order and run the scenario again to retest."),
        ])
    else:
        recs.append(Recommendation(GENERAL, (
            "No action needed for this run. Keep acquiring locks in a consistent order and "
            "re-run detection whenever the execution sequence changes."
        )))
    return recs
