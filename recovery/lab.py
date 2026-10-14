"""Recovery laboratory: compare simulated victims *before* applying one.

Each option is evaluated by aborting the victim in a deep COPY of the simulated
state, so the prediction is produced by exactly the same code that later
performs the real (simulated) recovery.  Nothing here touches real processes.

Ranking criteria (documented heuristic, NOT claimed to be globally optimal):

1. victims inside a detected cycle come first (aborting an outsider cannot break the cycle),
2. options that resolve every deadlock come before options that do not,
3. fewer locks held by the victim (less work undone),
4. fewer processes still blocked afterwards,
5. process name (to keep the order deterministic).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from detector.cycle_detector import find_cycles, format_cycle
from simulator.lock_state import LockState, ProcessStatus
from simulator.wait_for_graph import build_wait_for_graph

from .recovery_manager import RecoveryResult

CRITERIA = [
    "Victims inside a detected cycle rank first.",
    "Options that remove every cycle rank before options that do not.",
    "Fewer locks held by the victim ranks higher (less work undone).",
    "Fewer processes left blocked afterwards ranks higher.",
    "Ties are broken by process name. This is a heuristic, not a proof of optimality.",
]


@dataclass
class RecoveryOption:
    victim: str
    held_locks: List[str]
    handoffs: List[Tuple[str, str]]          # (lock, process that would receive it)
    in_cycle: bool
    predicted_resolved: bool
    predicted_cycles_after: List[List[str]]
    predicted_changes: List[str]
    blocked_before: int
    blocked_after: int
    predicted_after: dict
    rank: int = 0
    suggested: bool = False

    def sort_key(self) -> tuple:
        return (not self.in_cycle, not self.predicted_resolved, len(self.held_locks),
                self.blocked_after, self.victim)

    def summary_lines(self) -> List[str]:
        lines = [f"Abort {self.victim} (simulated)."]
        lines.append("Holds: " + (", ".join(self.held_locks) if self.held_locks else "no locks") + ".")
        if self.handoffs:
            lines.append("Locks would pass to waiting processes: " +
                         "; ".join(f"{l} -> {p}" for l, p in self.handoffs) + ".")
        elif self.held_locks:
            lines.append("Its locks have no waiters and would simply become free.")
        lines.append("In a detected cycle: " + ("yes" if self.in_cycle else "no (aborting it cannot break a cycle by itself)") + ".")
        if self.predicted_cycles_after:
            lines.append("Predicted result: deadlock remains: " +
                         ", ".join(format_cycle(c) for c in self.predicted_cycles_after) + ".")
        else:
            lines.append("Predicted result: no cycle remains in the Wait-For Graph.")
        lines.append(f"Blocked processes: {self.blocked_before} now -> {self.blocked_after} after.")
        return lines

    def to_dict(self) -> Dict[str, Any]:
        return {
            "victim": self.victim, "rank": self.rank, "suggested": self.suggested,
            "held_locks": list(self.held_locks), "lock_handoffs": [list(h) for h in self.handoffs],
            "in_cycle": self.in_cycle, "predicted_resolved": self.predicted_resolved,
            "predicted_cycles_after": self.predicted_cycles_after,
            "blocked_before": self.blocked_before, "blocked_after": self.blocked_after,
            "predicted_changes": list(self.predicted_changes),
        }


def _blocked(state: LockState) -> int:
    return len(state.blocked_processes())


def preview_options(state: LockState) -> List[RecoveryOption]:
    """Evaluate aborting each live process; the state is NOT modified."""
    cycles = find_cycles(build_wait_for_graph(state))
    in_cycle = {p for c in cycles for p in c}
    options: List[RecoveryOption] = []
    for victim in state.processes:
        if state.status_of(victim) is ProcessStatus.ABORTED:
            continue
        held = state.held_by(victim)
        handoffs = [(l, state.queue_of(l)[0]) for l in held if state.queue_of(l)]
        clone = copy.deepcopy(state)
        entries = clone.abort_process(victim)
        after_cycles = find_cycles(build_wait_for_graph(clone))
        options.append(RecoveryOption(
            victim=victim, held_locks=held, handoffs=handoffs, in_cycle=victim in in_cycle,
            predicted_resolved=not after_cycles, predicted_cycles_after=after_cycles,
            predicted_changes=[e.message for e in entries], blocked_before=_blocked(state),
            blocked_after=_blocked(clone), predicted_after=clone.snapshot()))
    options.sort(key=RecoveryOption.sort_key)
    suggested = None
    if cycles:
        members = sorted(in_cycle, key=lambda p: (len(state.held_by(p)), p))
        suggested = members[0]
    for i, opt in enumerate(options, 1):
        opt.rank = i
        opt.suggested = opt.victim == suggested
    return options


@dataclass
class PredictionCheck:
    matched: bool
    differences: List[str] = field(default_factory=list)


def check_prediction(option: RecoveryOption, result: RecoveryResult) -> PredictionCheck:
    """Compare what the lab predicted with what recovery actually did."""
    diffs = []
    if option.predicted_cycles_after != result.cycles_after:
        diffs.append("Remaining cycles differ from the prediction.")
    if option.predicted_after != result.after:
        diffs.append("The resulting lock state differs from the prediction.")
    return PredictionCheck(not diffs, diffs)
