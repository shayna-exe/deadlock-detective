"""Plain data models for real operating-system process telemetry.

Terminology (kept strict on purpose):

* ``cpu_percent``            current CPU use over the last sampling interval
                             (system-normalised: 100 % = every core fully busy).
* ``cpu_percent_per_core``   psutil's raw figure (can exceed 100 on multi-core).
* ``cpu_time_total_s``       cumulative CPU seconds the process has consumed since
                             it started.  This is NOT elapsed wall-clock time and
                             NOT a percentage.
* ``rss_bytes``              resident memory currently in RAM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ProcessKey = Tuple[int, float]  # (pid, create_time): survives PID reuse

MB = 1024 * 1024


def iso_now() -> str:
    """ISO 8601 UTC timestamp with seconds precision."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iso_from_epoch(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ProcessSample:
    """One observation of one real process.  ``None`` means "not available"."""

    pid: int
    name: str
    sampled_at: float                       # epoch seconds
    ppid: Optional[int] = None
    exe: Optional[str] = None
    status: Optional[str] = None
    create_time: Optional[float] = None
    cpu_percent: Optional[float] = None     # system-normalised; None until a baseline exists
    cpu_percent_per_core: Optional[float] = None
    cpu_ready: bool = False                 # False on the first sample of a process
    cpu_time_user_s: Optional[float] = None
    cpu_time_system_s: Optional[float] = None
    rss_bytes: Optional[int] = None
    mem_percent: Optional[float] = None
    num_threads: Optional[int] = None
    nice: Optional[int] = None
    access: str = "ok"                      # ok | partial | denied
    missing: Tuple[str, ...] = ()           # attributes that could not be read
    pid_reused: bool = False                # this PID previously belonged to another process

    @property
    def key(self) -> ProcessKey:
        return (self.pid, self.create_time if self.create_time is not None else -1.0)

    @property
    def cpu_time_total_s(self) -> Optional[float]:
        if self.cpu_time_user_s is None and self.cpu_time_system_s is None:
            return None
        return (self.cpu_time_user_s or 0.0) + (self.cpu_time_system_s or 0.0)

    @property
    def rss_mb(self) -> Optional[float]:
        return None if self.rss_bytes is None else self.rss_bytes / MB

    def to_dict(self) -> Dict[str, Any]:
        """Export form.  Deliberately has NO command line, NO user name and NO path."""
        total = self.cpu_time_total_s
        return {
            "pid": self.pid, "ppid": self.ppid, "name": self.name, "status": self.status,
            "started_at": iso_from_epoch(self.create_time),
            "sampled_at": iso_from_epoch(self.sampled_at),
            "cpu_percent": None if self.cpu_percent is None else round(self.cpu_percent, 2),
            "cpu_percent_note": "system-normalised current CPU use (100 = all cores busy)",
            "cpu_time_total_s": None if total is None else round(total, 2),
            "cpu_time_user_s": self.cpu_time_user_s,
            "cpu_time_system_s": self.cpu_time_system_s,
            "rss_mb": None if self.rss_mb is None else round(self.rss_mb, 1),
            "mem_percent": None if self.mem_percent is None else round(self.mem_percent, 2),
            "num_threads": self.num_threads, "access": self.access,
            "unavailable_metrics": list(self.missing),
        }


@dataclass(frozen=True)
class SystemSample:
    sampled_at: float
    cpu_percent: Optional[float]
    mem_percent: Optional[float]
    mem_total_bytes: Optional[int]
    mem_available_bytes: Optional[int]
    cpu_count: int
    process_count: int

    def to_dict(self) -> Dict[str, Any]:
        def mb(v: Optional[int]) -> Optional[int]:
            return None if v is None else round(v / MB)
        return {
            "sampled_at": iso_from_epoch(self.sampled_at),
            "cpu_percent": self.cpu_percent, "mem_percent": self.mem_percent,
            "mem_total_mb": mb(self.mem_total_bytes),
            "mem_available_mb": mb(self.mem_available_bytes),
            "cpu_count": self.cpu_count, "process_count": self.process_count,
        }


@dataclass
class CollectionResult:
    """Everything one collection pass produced, including what went wrong."""

    samples: List[ProcessSample]
    system: Optional[SystemSample]
    sampled_at: float
    skipped_exited: int = 0                 # processes that vanished mid-collection
    skipped_denied: int = 0                 # processes with no readable data at all
    errors: List[str] = field(default_factory=list)
    warming_up: bool = False                # True when no CPU baseline existed yet
