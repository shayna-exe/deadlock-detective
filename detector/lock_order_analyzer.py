"""Historical lock-order analysis (inspired by go-deadlock's ``lockOrder.order`` map).

Idea: whenever a process *attempts* to take lock B while holding lock A, record
the ordering "A before B".  If both "A before B" and "B before A" have been
observed (by any processes), the code paths use inconsistent lock ordering.
That is a **potential** deadlock - it only becomes real if the two paths run
concurrently and interleave badly.  It is NOT proof of a current deadlock; the
Wait-For Graph cycle detector is what proves that.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Set, Tuple

from simulator.events import (
    OP_GRANT,
    RESULT_ABORTED,
    RESULT_ACQUIRED,
    RESULT_RELEASED,
    EventType,
    HistoryEntry,
)


@dataclass(frozen=True)
class OrderObservation:
    before: str
    after: str
    process: str
    step: int


@dataclass(frozen=True)
class LockOrderWarning:
    locks: Tuple[str, str]
    first: OrderObservation   # one ordering, e.g. A before B
    second: OrderObservation  # the opposite ordering, e.g. B before A
    message: str

    def to_dict(self) -> dict:
        return {
            "locks": list(self.locks),
            "first_order": {"before": self.first.before, "after": self.first.after,
                            "process": self.first.process, "step": self.first.step},
            "opposite_order": {"before": self.second.before, "after": self.second.after,
                               "process": self.second.process, "step": self.second.step},
            "kind": "potential deadlock risk (not a confirmed deadlock)",
            "message": self.message,
        }


class LockOrderAnalyzer:
    """Replays a history and reports inconsistent lock orderings."""

    def analyze(self, history: Iterable[HistoryEntry]) -> List[LockOrderWarning]:
        held: Dict[str, List[str]] = {}
        seen: Dict[Tuple[str, str], OrderObservation] = {}
        warned: Set[frozenset] = set()
        warnings: List[LockOrderWarning] = []
        attempts = {EventType.ACQUIRE.value, EventType.REQUEST.value}

        for entry in history:
            mine = held.setdefault(entry.process, [])
            if entry.operation in attempts:
                # Like go-deadlock's preLock: order is recorded at the *attempt*,
                # relative to every lock this process already holds.
                for earlier in mine:
                    if earlier == entry.lock:
                        continue
                    pair = (earlier, entry.lock)
                    if pair not in seen:
                        seen[pair] = OrderObservation(earlier, entry.lock, entry.process, entry.step)
                    reverse = seen.get((entry.lock, earlier))
                    key = frozenset(pair)
                    if reverse is not None and key not in warned:
                        warned.add(key)
                        warnings.append(self._warning(reverse, seen[pair]))
                if entry.result == RESULT_ACQUIRED:
                    mine.append(entry.lock)
            elif entry.operation == OP_GRANT:
                mine.append(entry.lock)
            elif entry.result == RESULT_RELEASED and entry.lock in mine:
                mine.remove(entry.lock)
            elif entry.result == RESULT_ABORTED:
                held[entry.process] = []
        return warnings

    @staticmethod
    def _warning(first: OrderObservation, second: OrderObservation) -> LockOrderWarning:
        a, b = first.before, first.after
        message = (
            f"Inconsistent lock order between {a} and {b}: {first.process} took {a} before {b} "
            f"(step {first.step}), but {second.process} took {b} before {a} (step {second.step}). "
            f"If these two code paths ever run at the same time, one could hold {a} while waiting "
            f"for {b} and the other hold {b} while waiting for {a}, which is a circular wait. "
            "This is a potential risk inferred from history, not proof of a current deadlock."
        )
        return LockOrderWarning((a, b), first, second, message)
