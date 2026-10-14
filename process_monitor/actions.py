"""Real process-management actions, guarded by explicit safety checks.

Nothing in this module ever runs automatically.  Every operation:

1. needs ``confirmed=True`` (the GUI sets this only after a confirmation dialog
   that shows the exact process name, PID, operation and warning),
2. is refused for protected / unidentifiable / unreadable processes,
3. re-reads the process right before acting and refuses if its PID now belongs to
   a different process (PID reuse) or its name changed,
4. is recorded in an action log (name, PID, operation, outcome; no command line).

Platform notes (honest limits)
------------------------------
* ``terminate``: on Linux/macOS this sends SIGTERM, which a program may handle
  to save work and exit.  On Windows psutil's terminate() ends the process
  immediately (there is no polite close request through psutil), so the
  confirmation text warns about unsaved work.
* ``force_kill``: only offered after a terminate attempt on the same process
  timed out, and never on Windows (where terminate is already forceful).
* ``lower_priority``: nice value 10 on Linux/macOS, BELOW_NORMAL class on Windows.
* ``suspend`` / ``resume``: SIGSTOP/SIGCONT or the Windows suspend API; a
  suspended program freezes (its window stops responding) until resumed.
"""
from __future__ import annotations

import sys
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Iterable, List, Optional, Set

from .models import ProcessKey, ProcessSample, iso_now
from .protection import classify_protection
from .settings import MonitorSettings

TERMINATE = "terminate"
FORCE_KILL = "force_kill"
LOWER_PRIORITY = "lower_priority"
SUSPEND = "suspend"
RESUME = "resume"
OPERATIONS = (TERMINATE, FORCE_KILL, LOWER_PRIORITY, SUSPEND, RESUME)

LABELS = {
    TERMINATE: "Request termination",
    FORCE_KILL: "Force kill",
    LOWER_PRIORITY: "Lower priority",
    SUSPEND: "Suspend (freeze)",
    RESUME: "Resume",
}

OK, REFUSED, FAILED, TIMEOUT, DENIED, UNVERIFIED, GONE = (
    "success", "refused", "failed", "timeout", "denied", "unverified", "process_gone")


@dataclass(frozen=True)
class Availability:
    operation: str
    available: bool
    reason: str = ""        # why it is unavailable (or a note when available)


@dataclass(frozen=True)
class ActionRecord:
    at: str
    operation: str
    pid: int
    name: str
    outcome: str
    detail: str
    user_confirmed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {"at": self.at, "operation": self.operation, "pid": self.pid, "name": self.name,
                "outcome": self.outcome, "detail": self.detail, "user_confirmed": self.user_confirmed,
                "note": "real operating-system action approved by the user; unrelated to the simulation"}


class ProcessController:
    def __init__(self, settings: MonitorSettings, psutil_module: Any = None,
                 own_pids: Optional[Iterable[int]] = None, platform: Optional[str] = None) -> None:
        if psutil_module is None:
            import psutil as psutil_module
        self._ps = psutil_module
        self.settings = settings
        self.own_pids: Optional[Set[int]] = set(own_pids) if own_pids is not None else None
        self.platform = platform or sys.platform
        self.log: Deque[ActionRecord] = deque(maxlen=200)
        self._suspended: Dict[ProcessKey, str] = {}
        self._term_timed_out: Set[ProcessKey] = set()

    # ----------------------------------------------------------- availability
    @property
    def _windows(self) -> bool:
        return self.platform == "win32"

    def suspended_processes(self) -> List[tuple]:
        """[(pid, name)] of processes this program suspended and has not resumed."""
        return [(k[0], n) for k, n in self._suspended.items()]

    def availability(self, sample: ProcessSample) -> Dict[str, Availability]:
        result: Dict[str, Availability] = {}
        prot = classify_protection(sample, self.settings, self.own_pids)
        blocked = ""
        if prot.protected:
            blocked = "Protected process: " + prot.reason
        elif sample.access == "denied":
            blocked = "The process cannot be read (access denied), so its safety cannot be verified."
        elif sample.create_time is None:
            blocked = "The process start time is unknown, so its identity cannot be verified."
        for op in OPERATIONS:
            if blocked:
                result[op] = Availability(op, False, blocked)
                continue
            if op == FORCE_KILL:
                if self._windows:
                    result[op] = Availability(op, False, "On Windows, terminate is already immediate.")
                elif not self.settings.allow_force_kill:
                    result[op] = Availability(op, False, "Force kill is disabled in the settings.")
                elif sample.key not in self._term_timed_out:
                    result[op] = Availability(op, False, "Only offered after a termination request timed out.")
                else:
                    result[op] = Availability(op, True, "Last resort: the program cannot clean up.")
            elif op == RESUME:
                stopped = sample.key in self._suspended or (sample.status or "").lower() == "stopped"
                result[op] = Availability(op, stopped, "" if stopped else "Process is not suspended.")
            elif op == SUSPEND and not hasattr(self._ps.Process, "suspend"):
                result[op] = Availability(op, False, "Not supported on this platform.")
            elif op == SUSPEND and (sample.status or "").lower() == "stopped":
                result[op] = Availability(op, False, "Already suspended.")
            else:
                result[op] = Availability(op, True)
        return result

    def describe(self, sample: ProcessSample, operation: str) -> str:
        """Exact text for the confirmation dialog."""
        warnings = {
            TERMINATE: ("On Windows this ends the program IMMEDIATELY; unsaved work is lost."
                        if self._windows else
                        "Sends a termination signal. The program may save and exit, or ignore it. Unsaved work may be lost."),
            FORCE_KILL: "Kills the program instantly. It cannot clean up or save. Unsaved work is lost.",
            LOWER_PRIORITY: "The program keeps running but gets less CPU time when programs compete.",
            SUSPEND: "Freezes the program (its window stops responding) until you resume it.",
            RESUME: "Lets a suspended program continue running.",
        }
        return (f"Operation: {LABELS[operation]}\nProcess: {sample.name}\nPID: {sample.pid}\n\n"
                f"{warnings[operation]}\n\nThis acts on a REAL program on this computer.")

    # ---------------------------------------------------------------- execute
    def _record(self, op: str, sample: ProcessSample, outcome: str, detail: str, confirmed: bool) -> ActionRecord:
        rec = ActionRecord(iso_now(), op, sample.pid, sample.name, outcome, detail, confirmed)
        self.log.append(rec)
        return rec

    def execute(self, sample: ProcessSample, operation: str, confirmed: bool) -> ActionRecord:
        """Run ``operation`` on the real process described by ``sample``.  Never raises."""
        if operation not in OPERATIONS:
            return self._record(operation, sample, REFUSED, "Unknown operation.", confirmed)
        if not confirmed:
            return self._record(operation, sample, REFUSED, "Explicit confirmation is required.", False)
        avail = self.availability(sample)[operation]
        if not avail.available:
            return self._record(operation, sample, REFUSED, avail.reason, True)

        # --- revalidate identity right before acting -------------------------
        ps = self._ps
        try:
            proc = ps.Process(sample.pid)
            created = proc.create_time()
            name = proc.name()
        except ps.NoSuchProcess:
            return self._record(operation, sample, GONE, "The process had already exited.", True)
        except ps.AccessDenied:
            return self._record(operation, sample, DENIED, "Access denied while verifying the process.", True)
        except Exception as exc:
            return self._record(operation, sample, REFUSED,
                                f"Could not verify the process ({type(exc).__name__}); refusing to act.", True)
        if abs(created - (sample.create_time or 0.0)) > 1e-3 or name != sample.name:
            return self._record(operation, sample, REFUSED,
                                "PID now belongs to a different process; nothing was changed.", True)

        try:
            return self._perform(proc, sample, operation)
        except ps.NoSuchProcess:
            return self._record(operation, sample, GONE, "The process exited during the operation.", True)
        except ps.AccessDenied:
            return self._record(operation, sample, DENIED, "The operating system denied permission.", True)
        except NotImplementedError:
            return self._record(operation, sample, FAILED, "Not supported on this platform.", True)
        except Exception as exc:
            return self._record(operation, sample, FAILED, f"{type(exc).__name__}: {exc}", True)

    def _perform(self, proc: Any, sample: ProcessSample, op: str) -> ActionRecord:
        ps, timeout = self._ps, self.settings.terminate_timeout_s
        if op in (TERMINATE, FORCE_KILL):
            proc.terminate() if op == TERMINATE else proc.kill()
            try:
                proc.wait(timeout=timeout)
            except ps.TimeoutExpired:
                if op == TERMINATE:
                    self._term_timed_out.add(sample.key)
                return self._record(op, sample, TIMEOUT,
                                    f"Still running after {timeout:g} s; the program may be ignoring the request.", True)
            self._term_timed_out.discard(sample.key)
            self._suspended.pop(sample.key, None)
            alive = proc.is_running()
            return self._record(op, sample, UNVERIFIED if alive else OK,
                                "The process is still listed after the request." if alive else "The process has exited.", True)
        if op == LOWER_PRIORITY:
            target = ps.BELOW_NORMAL_PRIORITY_CLASS if self._windows and hasattr(ps, "BELOW_NORMAL_PRIORITY_CLASS") else 10
            proc.nice(target)
            now = proc.nice()
            ok = now == target
            return self._record(op, sample, OK if ok else UNVERIFIED,
                                f"Priority set (now {now})." if ok else f"Requested {target} but the system reports {now}.", True)
        if op == SUSPEND:
            proc.suspend()
            self._suspended[sample.key] = sample.name
            stopped = str(proc.status()).lower() == "stopped"
            return self._record(op, sample, OK if stopped else UNVERIFIED,
                                "The process is suspended." if stopped else "Suspend requested; the status could not be confirmed.", True)
        if op == RESUME:
            proc.resume()
            self._suspended.pop(sample.key, None)
            running = str(proc.status()).lower() != "stopped"
            return self._record(op, sample, OK if running else UNVERIFIED,
                                "The process was resumed." if running else "Resume requested; it still reports stopped.", True)
        return self._record(op, sample, REFUSED, "Unknown operation.", True)  # pragma: no cover

    def log_as_dicts(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self.log]
