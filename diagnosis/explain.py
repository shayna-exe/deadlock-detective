"""Plain-language explanation of the current state, generated from real data.

Inputs are the simulation state, its Wait-For Graph and the detected cycles;
nothing here is tied to a particular scenario.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

from detector.cycle_detector import cycle_edges, format_cycle
from detector.lock_order_analyzer import LockOrderWarning
from simulator.events import RESULT_BLOCKED, OP_ABORT
from simulator.lock_state import LockState

STATUS_DEADLOCK = "DEADLOCK_DETECTED"
STATUS_NONE = "NO_DEADLOCK"


@dataclass
class Diagnosis:
    status: str
    headline: str
    cycles: List[List[str]]
    explanation: List[str]        # paragraphs about confirmed deadlock(s) / blocked processes
    ownership: List[str]          # who holds which lock
    waiting: List[str]            # who waits for what
    lock_order_notes: List[str]   # potential risks from history (separate from deadlock!)

    @property
    def deadlock(self) -> bool:
        return self.status == STATUS_DEADLOCK

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "headline": self.headline,
            "cycles": [list(c) for c in self.cycles],
            "explanation": list(self.explanation),
            "lock_ownership": list(self.ownership),
            "waiting": list(self.waiting),
            "lock_order_notes": list(self.lock_order_notes),
        }


def _holds_text(state: LockState, process: str) -> str:
    held = state.held_by(process)
    return "lock " + ", ".join(held) if len(held) == 1 else (
        "locks " + ", ".join(held) if held else "no locks")


def _block_step(state: LockState, process: str, lock: str) -> int:
    """History step at which ``process`` started waiting for ``lock`` (0 if unknown)."""
    step = 0
    for e in state.history:
        if e.process == process and e.result == RESULT_BLOCKED and e.lock == lock:
            step = e.step
    return step


def _explain_cycle(state: LockState, graph, cycle: List[str], index: int) -> List[str]:
    edges = cycle_edges(graph, cycle)
    locks = [lock for _, _, lock in edges]
    lines = [
        f"Deadlock {index}: circular wait {format_cycle(cycle)} "
        f"({len(cycle)} process{'es' if len(cycle) != 1 else ''}, "
        f"{len(set(locks))} lock{'s' if len(set(locks)) != 1 else ''})."
    ]
    for waiter, holder, lock in edges:
        lines.append(
            f"  - {waiter} holds {_holds_text(state, waiter)} and is waiting for lock {lock}, "
            f"which is held by {holder}. So {waiter} waits for {holder}."
        )
    timeline = sorted(((_block_step(state, w, l), w, h, l) for w, h, l in edges))
    if all(step for step, *_ in timeline):
        formed = "; ".join(f"step {s}: {w} blocked on {l} (held by {h})" for s, w, h, l in timeline)
        last = timeline[-1]
        lines.append(
            f"  How it formed: {formed}. The loop closed at step {last[0]} when {last[1]} "
            f"requested lock {last[3]}."
        )
    lines.append(
        "  Why nobody can proceed: every process in the cycle needs a lock owned by the next one, "
        "locks cannot be taken away (no preemption), and a blocked process cannot release the "
        "locks it holds. The cycle can only be broken from outside, e.g. by aborting one process."
    )
    return lines


def _stuck_behind(graph, cycles: Sequence[Sequence[str]], process: str) -> bool:
    """Does following 'waits-for' edges from ``process`` lead into a deadlock cycle?"""
    in_cycle = {n for c in cycles for n in c}
    seen = set()
    while process not in seen:
        if process in in_cycle:
            return True
        seen.add(process)
        nxt = list(graph.successors(process))
        if not nxt:
            return False
        process = nxt[0]
    return False


def explain(state: LockState, graph, cycles: Sequence[Sequence[str]],
            warnings: Sequence[LockOrderWarning]) -> Diagnosis:
    cycles = [list(c) for c in cycles]
    ownership = [
        f"Lock {lock} is held by {state.owner_of(lock)}." if state.owner_of(lock)
        else f"Lock {lock} is free."
        for lock in state.locks
    ]
    waiting = []
    for proc in state.blocked_processes():
        lock = state.waiting_for(proc)
        waiting.append(f"{proc} is waiting for lock {lock}, held by {state.owner_of(lock)}.")

    explanation: List[str] = []
    in_cycle = {n for c in cycles for n in c}
    if cycles:
        status = STATUS_DEADLOCK
        headline = (
            f"Deadlock detected: {len(cycles)} circular wait{'s' if len(cycles) != 1 else ''} "
            "in the Wait-For Graph."
        )
        for i, cycle in enumerate(cycles, 1):
            explanation.extend(_explain_cycle(state, graph, cycle, i))
        for proc in state.blocked_processes():
            if proc not in in_cycle and _stuck_behind(graph, cycles, proc):
                lock = state.waiting_for(proc)
                explanation.append(
                    f"{proc} is not part of a cycle but is stuck behind one: it waits for lock "
                    f"{lock} held by {state.owner_of(lock)}, who cannot proceed."
                )
    else:
        status = STATUS_NONE
        headline = "No current deadlock detected: the Wait-For Graph has no cycle."
        blocked = state.blocked_processes()
        if blocked:
            explanation.append(
                f"{len(blocked)} process{'es are' if len(blocked) != 1 else ' is'} blocked "
                f"({', '.join(blocked)}), but every wait chain ends at a process that is not "
                "waiting, so it can still finish and release its locks. Waiting alone is not a deadlock."
            )
        else:
            explanation.append("No process is blocked; every process can keep running.")
        if any(e.operation == OP_ABORT for e in state.history):
            explanation.append("Note: at least one process was aborted earlier in this run.")

    notes = [w.message for w in warnings]
    return Diagnosis(status, headline, cycles, explanation, ownership, waiting, notes)
