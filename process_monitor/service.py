"""GUI-independent monitoring service: collect -> track -> recommend.

``MonitoringService.sample_once()`` does one full pass and can be called
directly (tests, "Refresh now").  ``start()`` runs the same pass repeatedly in
ONE background daemon thread.  The thread never touches Tkinter: it only stores
the newest ``MonitorSnapshot`` (under a lock) and the GUI polls ``latest()``
from the Tk main thread with ``after()``.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .activity_tracker import ActivityTracker
from .models import CollectionResult, SystemSample, iso_from_epoch, iso_now
from .monitor import ProcessMonitor
from .recommendations import (CLOSE, HIGH_CPU, HIGH_MEM, IDLE, INVESTIGATE, LOWER, ProcessAssessment,
                              RecommendationEngine)
from .settings import MonitorSettings

#: Categories counted as "resource-management opportunities" in summaries.
ATTENTION = (CLOSE, IDLE, LOWER, HIGH_CPU, HIGH_MEM, INVESTIGATE)


@dataclass
class MonitorSnapshot:
    sequence: int
    sampled_at: float
    system: Optional[SystemSample]
    assessments: List[ProcessAssessment]
    errors: List[str] = field(default_factory=list)
    warming_up: bool = False
    skipped_exited: int = 0
    skipped_denied: int = 0

    def by_cpu(self, n: int = 5) -> List[ProcessAssessment]:
        ok = [a for a in self.assessments if a.sample.cpu_percent is not None]
        return sorted(ok, key=lambda a: a.sample.cpu_percent or 0.0, reverse=True)[:n]

    def by_memory(self, n: int = 5) -> List[ProcessAssessment]:
        ok = [a for a in self.assessments if a.sample.rss_bytes is not None]
        return sorted(ok, key=lambda a: a.sample.rss_bytes or 0, reverse=True)[:n]

    def attention(self) -> List[ProcessAssessment]:
        return [a for a in self.assessments if a.category in ATTENTION]

    def telemetry_dict(self, top_n: int = 5) -> Dict[str, Any]:
        """Export form used by incidents/reports.  Contextual telemetry only."""
        return {
            "available": True,
            "source": "real operating-system processes (psutil)",
            "captured_at": iso_from_epoch(self.sampled_at),
            "disclaimer": ("Contextual system telemetry. It does NOT show that any listed application is "
                           "involved in the simulated deadlock."),
            "warming_up": self.warming_up,
            "system": self.system.to_dict() if self.system else None,
            "process_count": len(self.assessments),
            "top_cpu_consumers": [a.sample.to_dict() for a in self.by_cpu(top_n)],
            "top_memory_consumers": [a.sample.to_dict() for a in self.by_memory(top_n)],
            "recommendations": [a.to_dict() for a in self.attention()[:50]],
            "collection_errors": list(self.errors),
            "skipped_exited": self.skipped_exited,
            "skipped_access_denied": self.skipped_denied,
        }


class MonitoringService:
    def __init__(self, settings: Optional[MonitorSettings] = None, psutil_module: Any = None,
                 own_pids=None) -> None:
        self.settings = (settings or MonitorSettings()).validate()
        self._monitor = ProcessMonitor(psutil_module)
        self.tracker = ActivityTracker(self.settings)
        self.engine = RecommendationEngine(self.settings, own_pids)
        self._own_pids = own_pids
        self._lock = threading.RLock()
        self._latest: Optional[MonitorSnapshot] = None
        self._sequence = 0
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_error: Optional[str] = None

    # ----------------------------------------------------------------- pass
    def sample_once(self) -> MonitorSnapshot:
        """One full collection + analysis pass (safe to call from any thread)."""
        result: CollectionResult = self._monitor.collect()
        with self._lock:
            self.tracker.record(result.samples, result.system)
            assessments = self.engine.assess_all(result.samples, self.tracker)
            self._sequence += 1
            snap = MonitorSnapshot(self._sequence, result.sampled_at, result.system, assessments,
                                   list(result.errors), result.warming_up,
                                   result.skipped_exited, result.skipped_denied)
            self._latest = snap
            self._last_error = result.errors[0] if result.errors and not result.samples else None
        return snap

    # ---------------------------------------------------------------- state
    def latest(self) -> Optional[MonitorSnapshot]:
        with self._lock:
            return self._latest

    @property
    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    def is_running(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    # --------------------------------------------------------------- worker
    def start(self) -> bool:
        """Start background sampling.  Returns False if it was already running."""
        with self._lock:
            if self.is_running():
                return False
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._run, args=(self._stop,),
                                            name="deadlock-detective-monitor", daemon=True)
            self._thread.start()
            return True

    def _run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            started = time.monotonic()
            try:
                self.sample_once()
            except Exception as exc:  # never let the worker die silently
                with self._lock:
                    self._last_error = f"{type(exc).__name__}: {exc}"
            delay = max(0.0, self.settings.sample_interval_s - (time.monotonic() - started))
            if stop.wait(delay):
                break

    def stop(self, timeout: float = 5.0) -> bool:
        """Stop the worker and wait for it.  Returns True if the thread has ended."""
        with self._lock:
            thread, stop = self._thread, self._stop
        stop.set()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout)
        return not self.is_running()

    # ------------------------------------------------------------- settings
    def apply_settings(self, settings: MonitorSettings) -> None:
        settings = settings.validate()
        with self._lock:
            self.settings = settings
            self.tracker.apply_settings(settings)
            self.engine = RecommendationEngine(settings, self._own_pids)

    def clear_history(self) -> None:
        with self._lock:
            self.tracker.clear()
            self._monitor.reset()
            self._latest = None
