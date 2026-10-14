"""Event model for the deadlock simulator.

Three kinds of events can be fed to the simulator (``EventType``).  Everything
the simulator *does* in response (including implicit actions such as handing a
lock to a waiting process) is written to the history as a ``HistoryEntry``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional


class SimulationError(Exception):
    """Raised when an event or operation is invalid in the current state."""


class EventType(str, Enum):
    """Operations a simulated process may perform."""

    ACQUIRE = "ACQUIRE"  # take a lock that must currently be free
    REQUEST = "REQUEST"  # take the lock, or wait (block) if someone else holds it
    RELEASE = "RELEASE"  # give a lock back

    @classmethod
    def parse(cls, value: Any) -> "EventType":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().upper())
        except ValueError:
            allowed = ", ".join(e.value for e in cls)
            raise SimulationError(
                f"Unknown operation {value!r}. Supported operations: {allowed}."
            ) from None


# Operation names that appear only in the history (not in scenario input).
OP_GRANT = "GRANT"  # a waiting process was handed a lock that was released
OP_ABORT = "ABORT"  # a process was aborted by the recovery manager

# Result names used in history entries.
RESULT_ACQUIRED = "ACQUIRED"
RESULT_BLOCKED = "BLOCKED"
RESULT_RELEASED = "RELEASED"
RESULT_GRANTED = "GRANTED"
RESULT_ABORTED = "ABORTED"


@dataclass(frozen=True)
class Event:
    """One scripted operation: ``process`` performs ``op`` on ``lock``."""

    process: str
    op: EventType
    lock: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Event":
        if not isinstance(data, Mapping):
            raise SimulationError(f"An event must be an object, got {type(data).__name__}.")
        missing = [k for k in ("process", "op", "lock") if k not in data]
        if missing:
            raise SimulationError(f"Event {dict(data)!r} is missing field(s): {', '.join(missing)}.")
        process, lock = data["process"], data["lock"]
        for label, val in (("process", process), ("lock", lock)):
            if not isinstance(val, str) or not val.strip():
                raise SimulationError(f"Event field '{label}' must be a non-empty string.")
        return cls(process.strip(), EventType.parse(data["op"]), lock.strip())

    def to_dict(self) -> dict:
        return {"process": self.process, "op": self.op.value, "lock": self.lock}

    def __str__(self) -> str:
        return f"{self.process} {self.op.value} {self.lock}"


@dataclass(frozen=True)
class HistoryEntry:
    """A readable record of one thing that happened in the simulation."""

    step: int
    process: str
    operation: str
    lock: Optional[str]
    result: str
    blocked: bool  # True if this operation caused the process to block
    message: str

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "process": self.process,
            "operation": self.operation,
            "lock": self.lock,
            "result": self.result,
            "blocked": self.blocked,
            "message": self.message,
        }
