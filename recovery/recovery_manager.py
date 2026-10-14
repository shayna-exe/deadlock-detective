"""Simulated deadlock recovery by process abort.

Only the in-memory simulation is changed; no real process or mutex is touched.
Aborting a process releases every lock it holds, and each released lock is
handed to its first waiter (the simulator's FIFO policy), which may unblock
other processes.  Detection is re-run afterwards to verify the result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from detector.cycle_detector import find_cycles
from simulator.events import SimulationError
from simulator.lock_state import LockState, ProcessStatus
from simulator.wait_for_graph import build_wait_for_graph


@dataclass
class RecoveryResult:
    action: str
    victim: str
    reason: str
    victim_was_in_cycle: bool
    before: dict                       # LockState.snapshot() before the action
    after: dict                        # ... and after
    cycles_before: List[List[str]]
    cycles_after: List[List[str]]
    changes: List[str]                 # history messages produced by the action
    released_locks: List[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        """True if the state has no deadlock cycle after the action."""
        return not self.cycles_after

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "victim": self.victim,
            "reason": self.reason,
            "victim_was_in_cycle": self.victim_was_in_cycle,
            "released_locks": list(self.released_locks),
            "state_before": self.before,
            "state_after": self.after,
            "cycles_before": self.cycles_before,
            "cycles_after": self.cycles_after,
            "changes": list(self.changes),
            "deadlock_resolved": self.resolved,
        }


class RecoveryManager:
    """Applies recovery actions to a ``LockState`` and logs them."""

    ABORT = "abort_process"

    def __init__(self, state: LockState) -> None:
        self.state = state
        self.log: List[RecoveryResult] = []

    def _cycles(self) -> List[List[str]]:
        return find_cycles(build_wait_for_graph(self.state))

    def candidates(self) -> List[str]:
        """Processes that may be aborted (anything not already aborted)."""
        return [p for p in self.state.processes if self.state.status_of(p) is not ProcessStatus.ABORTED]

    def suggest_victim(self) -> Optional[Tuple[str, str]]:
        """Pick a victim from the current deadlock: fewest held locks, then name.

        Returns ``(process, reason)`` or ``None`` when there is no deadlock.
        """
        cycles = self._cycles()
        if not cycles:
            return None
        members = sorted({p for c in cycles for p in c},
                         key=lambda p: (len(self.state.held_by(p)), p))
        victim = members[0]
        return victim, (f"{victim} holds the fewest locks ({len(self.state.held_by(victim))}) "
                        "among the deadlocked processes, so aborting it undoes the least work.")

    def abort_process(self, victim: str, reason: str = "chosen manually") -> RecoveryResult:
        """Abort ``victim``; raises ``SimulationError`` if that is not possible."""
        if victim not in self.state.processes:
            raise SimulationError(f"Unknown process '{victim}'.")
        cycles_before = self._cycles()
        before = self.state.snapshot()
        released = self.state.held_by(victim)
        entries = self.state.abort_process(victim)  # raises if already aborted
        result = RecoveryResult(
            action=self.ABORT,
            victim=victim,
            reason=reason,
            victim_was_in_cycle=any(victim in c for c in cycles_before),
            before=before,
            after=self.state.snapshot(),
            cycles_before=cycles_before,
            cycles_after=self._cycles(),
            changes=[e.message for e in entries],
            released_locks=released,
        )
        self.log.append(result)
        return result

    def auto_recover(self) -> RecoveryResult:
        """Abort the suggested victim of the current deadlock."""
        choice = self.suggest_victim()
        if choice is None:
            raise SimulationError("There is no deadlock to recover from.")
        victim, reason = choice
        return self.abort_process(victim, reason)
