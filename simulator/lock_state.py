"""Simulated lock/process state and the rules that govern it.

Model
-----
* Locks are exclusive, non-reentrant and non-preemptible (like a plain mutex).
* A process is RUNNING, BLOCKED (waiting for exactly one lock) or ABORTED.
* A BLOCKED process cannot perform any operation until the lock it waits for is
  handed to it.
* Scheduling policy: each lock has a FIFO queue of waiters.  When the owner
  releases the lock, ownership passes immediately to the *first* waiter, which
  becomes RUNNING again.  The lock is never "free" while someone is waiting.

This is a controlled simulation only; no real OS locks or processes are used.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .events import (
    OP_ABORT,
    OP_GRANT,
    RESULT_ABORTED,
    RESULT_ACQUIRED,
    RESULT_BLOCKED,
    RESULT_GRANTED,
    RESULT_RELEASED,
    Event,
    EventType,
    HistoryEntry,
    SimulationError,
)


class ProcessStatus(str, Enum):
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    ABORTED = "ABORTED"


class LockState:
    """Current ownership/waiting state plus the full event history."""

    def __init__(
        self,
        processes: Optional[Iterable[str]] = None,
        locks: Optional[Iterable[str]] = None,
        strict: bool = False,
    ) -> None:
        """Create a state.

        If ``strict`` is true, only the declared processes and locks may be
        referenced; otherwise unknown names are registered on first use.
        """
        self._strict = strict
        self._status: Dict[str, ProcessStatus] = {}
        self._owner: Dict[str, Optional[str]] = {}
        self._queues: Dict[str, List[str]] = {}
        self._waiting_for: Dict[str, str] = {}
        self._history: List[HistoryEntry] = []
        #: Incremented on every state change; used to detect stale analysis.
        self.version = 0
        for p in processes or ():
            self._register_process(p)
        for l in locks or ():
            self._register_lock(l)

    # ------------------------------------------------------------ registration
    @staticmethod
    def _check_name(kind: str, name: object) -> str:
        if not isinstance(name, str) or not name.strip():
            raise SimulationError(f"A {kind} name must be a non-empty string, got {name!r}.")
        return name.strip()

    def _register_process(self, name: str) -> None:
        name = self._check_name("process", name)
        if name in self._status:
            raise SimulationError(f"Process '{name}' is declared more than once.")
        self._status[name] = ProcessStatus.RUNNING

    def _register_lock(self, name: str) -> None:
        name = self._check_name("lock", name)
        if name in self._owner:
            raise SimulationError(f"Lock '{name}' is declared more than once.")
        self._owner[name] = None
        self._queues[name] = []

    def _resolve(self, process: str, lock: Optional[str]) -> Tuple[str, Optional[str]]:
        process = self._check_name("process", process)
        if process not in self._status:
            if self._strict:
                raise SimulationError(f"Unknown process '{process}'.")
            self._register_process(process)
        if lock is not None:
            lock = self._check_name("lock", lock)
            if lock not in self._owner:
                if self._strict:
                    raise SimulationError(f"Unknown lock '{lock}'.")
                self._register_lock(lock)
        return process, lock

    # ---------------------------------------------------------------- queries
    @property
    def processes(self) -> List[str]:
        return list(self._status)

    @property
    def locks(self) -> List[str]:
        return list(self._owner)

    @property
    def history(self) -> List[HistoryEntry]:
        return list(self._history)

    def status_of(self, process: str) -> ProcessStatus:
        return self._status[process]

    def owner_of(self, lock: str) -> Optional[str]:
        return self._owner[lock]

    def queue_of(self, lock: str) -> List[str]:
        return list(self._queues[lock])

    def waiting_for(self, process: str) -> Optional[str]:
        """The lock ``process`` is blocked on, or None."""
        return self._waiting_for.get(process)

    def held_by(self, process: str) -> List[str]:
        return [l for l, o in self._owner.items() if o == process]

    def blocked_processes(self) -> List[str]:
        return [p for p, s in self._status.items() if s is ProcessStatus.BLOCKED]

    # ----------------------------------------------------------------- events
    def apply(self, event: Event) -> List[HistoryEntry]:
        """Apply a scripted event; return the history entries it produced.

        The first returned entry is the event itself; any further entries are
        consequences (e.g. a waiting process being granted a released lock).
        Raises ``SimulationError`` and leaves the state unchanged if invalid.
        """
        known_processes, known_locks = set(self._status), set(self._owner)
        try:
            process, lock = self._resolve(event.process, event.lock)
            self._require_active(process)
            if event.op is EventType.ACQUIRE:
                return self._acquire(process, lock)
            if event.op is EventType.REQUEST:
                return self._request(process, lock)
            if event.op is EventType.RELEASE:
                return self._release(process, lock)
            raise SimulationError(f"Unknown operation {event.op!r}.")  # pragma: no cover
        except SimulationError:
            # A rejected event must leave no trace, including names registered
            # on the fly (non-strict mode).
            for name in set(self._status) - known_processes:
                del self._status[name]
            for name in set(self._owner) - known_locks:
                del self._owner[name]
                del self._queues[name]
            raise

    def _require_active(self, process: str) -> None:
        status = self._status[process]
        if status is ProcessStatus.ABORTED:
            raise SimulationError(f"{process} has been aborted and cannot perform operations.")
        if status is ProcessStatus.BLOCKED:
            raise SimulationError(
                f"{process} is blocked waiting for lock {self._waiting_for[process]} "
                "and cannot perform another operation."
            )

    def _check_not_reacquired(self, process: str, lock: str, op: str) -> None:
        if self._owner[lock] == process:
            raise SimulationError(
                f"{process} already holds lock {lock}; locks are not re-entrant, so {op} "
                "would make the process wait for itself."
            )

    def _acquire(self, process: str, lock: str) -> List[HistoryEntry]:
        self._check_not_reacquired(process, lock, "ACQUIRE")
        owner = self._owner[lock]
        if owner is not None:
            raise SimulationError(
                f"Lock {lock} is already held by {owner}; ACQUIRE needs a free lock "
                "(use REQUEST to wait for it)."
            )
        self._owner[lock] = process
        return [self._record(process, EventType.ACQUIRE.value, lock, RESULT_ACQUIRED, False,
                             f"{process} acquired lock {lock}.")]

    def _request(self, process: str, lock: str) -> List[HistoryEntry]:
        self._check_not_reacquired(process, lock, "REQUEST")
        owner = self._owner[lock]
        if owner is None:
            self._owner[lock] = process
            return [self._record(process, EventType.REQUEST.value, lock, RESULT_ACQUIRED, False,
                                 f"{process} requested lock {lock}; it was free, so it was acquired.")]
        self._queues[lock].append(process)
        self._status[process] = ProcessStatus.BLOCKED
        self._waiting_for[process] = lock
        return [self._record(process, EventType.REQUEST.value, lock, RESULT_BLOCKED, True,
                             f"{process} requested lock {lock}, held by {owner}; {process} is now blocked.")]

    def _release(self, process: str, lock: str) -> List[HistoryEntry]:
        owner = self._owner[lock]
        if owner != process:
            who = "nobody (the lock is free)" if owner is None else owner
            raise SimulationError(f"{process} cannot release lock {lock}: it is held by {who}.")
        entries = [self._record(process, EventType.RELEASE.value, lock, RESULT_RELEASED, False,
                                f"{process} released lock {lock}.")]
        entries.extend(self._hand_over(lock))
        return entries

    def _hand_over(self, lock: str) -> List[HistoryEntry]:
        """Free ``lock`` and give it to the first waiter (FIFO), if any."""
        queue = self._queues[lock]
        if not queue:
            self._owner[lock] = None
            return []
        nxt = queue.pop(0)
        self._owner[lock] = nxt
        self._status[nxt] = ProcessStatus.RUNNING
        del self._waiting_for[nxt]
        return [self._record(nxt, OP_GRANT, lock, RESULT_GRANTED, False,
                             f"Lock {lock} was handed to waiting process {nxt} (FIFO); {nxt} is running again.")]

    # ------------------------------------------------------------------ abort
    def abort_process(self, process: str) -> List[HistoryEntry]:
        """Abort a simulated process (used by recovery).

        Its locks are released (each handed to the first waiter, FIFO), it is
        removed from any wait queue, and it can no longer act.
        """
        if process not in self._status:
            raise SimulationError(f"Unknown process '{process}'.")
        if self._status[process] is ProcessStatus.ABORTED:
            raise SimulationError(f"{process} has already been aborted.")
        waiting = self._waiting_for.pop(process, None)
        if waiting is not None:
            self._queues[waiting].remove(process)
        held = self.held_by(process)
        self._status[process] = ProcessStatus.ABORTED
        detail = []
        if waiting is not None:
            detail.append(f"removed from the wait queue of {waiting}")
        detail.append("released " + ", ".join(held) if held else "held no locks")
        entries = [self._record(process, OP_ABORT, None, RESULT_ABORTED, False,
                                f"{process} was aborted ({'; '.join(detail)}).")]
        for lock in held:
            entries.extend(self._hand_over(lock))
        return entries

    # -------------------------------------------------------------- internals
    def _record(self, process: str, operation: str, lock: Optional[str], result: str,
                blocked: bool, message: str) -> HistoryEntry:
        entry = HistoryEntry(len(self._history) + 1, process, operation, lock, result, blocked, message)
        self._history.append(entry)
        self.version += 1
        return entry

    # -------------------------------------------------------------- snapshots
    def snapshot(self) -> dict:
        """A plain-data copy of the current state (safe to store or serialise)."""
        return {
            "processes": {
                p: {
                    "status": self._status[p].value,
                    "holds": self.held_by(p),
                    "waiting_for": self._waiting_for.get(p),
                }
                for p in self._status
            },
            "locks": {
                l: {"owner": self._owner[l], "queue": list(self._queues[l])}
                for l in self._owner
            },
        }


def format_snapshot(snapshot: dict) -> List[str]:
    """Render a ``snapshot()`` as readable lines."""
    lines = []
    for lock, info in snapshot["locks"].items():
        owner = info["owner"] or "free"
        queue = f"  (waiting: {', '.join(info['queue'])})" if info["queue"] else ""
        lines.append(f"Lock {lock}: held by {owner}{queue}")
    for proc, info in snapshot["processes"].items():
        holds = ", ".join(info["holds"]) if info["holds"] else "nothing"
        wait = f", waiting for {info['waiting_for']}" if info["waiting_for"] else ""
        lines.append(f"{proc}: {info['status']}, holds {holds}{wait}")
    return lines
