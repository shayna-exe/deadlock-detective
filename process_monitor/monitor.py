"""Collect real operating-system process metrics with ``psutil``.

This module only *collects*.  Analysis lives in ``activity_tracker.py``,
recommendations in ``recommendations.py`` and actions in ``actions.py``.

Robustness rules
----------------
* One unreadable process never aborts a pass: each attribute is read
  separately and failures are recorded in ``ProcessSample.missing``.
* Processes that exit while being read are counted and skipped.
* Process identity is ``(pid, create_time)`` so a reused PID is never confused
  with the process that used to own it.
* CPU percentage: psutil's ``cpu_percent(None)`` measures the time since the
  *previous call for that process*, so the first reading is meaningless.  The
  first sample of every process therefore has ``cpu_percent=None`` and
  ``cpu_ready=False`` instead of a misleading 0.0.

The ``psutil`` module is injected, which lets the tests use a fake one.
"""
from __future__ import annotations

import contextlib
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import CollectionResult, ProcessKey, ProcessSample, SystemSample

MAX_ERROR_MESSAGES = 20


class ProcessMonitor:
    def __init__(self, psutil_module: Any = None) -> None:
        if psutil_module is None:
            import psutil as psutil_module  # imported lazily so tests can inject a fake
        self._ps = psutil_module
        self._baseline: Set[ProcessKey] = set()     # keys whose CPU baseline exists
        self._pid_created: Dict[int, float] = {}    # pid -> create_time last seen
        self._system_primed = False
        self._cpu_count = max(1, self._safe_cpu_count())

    # ------------------------------------------------------------- helpers
    def _safe_cpu_count(self) -> int:
        try:
            return int(self._ps.cpu_count(logical=True) or 1)
        except Exception:  # pragma: no cover - psutil returns None on odd platforms
            return 1

    @property
    def _gone(self) -> tuple:
        return (self._ps.NoSuchProcess,)

    @property
    def _unreadable(self) -> tuple:
        types = [self._ps.AccessDenied]
        if hasattr(self._ps, "ZombieProcess"):
            types.append(self._ps.ZombieProcess)
        types.extend([OSError, ValueError, NotImplementedError, AttributeError])
        return tuple(types)

    def _read(self, label: str, getter, missing: List[str]) -> Any:
        """Call ``getter``; record ``label`` as missing if it cannot be read.

        ``NoSuchProcess`` is *not* caught: it means the process is gone.
        """
        try:
            return getter()
        except self._gone:
            raise
        except self._unreadable:
            missing.append(label)
            return None

    # ------------------------------------------------------------- system
    def _system_sample(self, now: float, process_count: int, errors: List[str]) -> Optional[SystemSample]:
        try:
            cpu = self._ps.cpu_percent(interval=None)
            cpu = cpu if self._system_primed else None  # first call has no baseline
            self._system_primed = True
            mem = self._ps.virtual_memory()
            return SystemSample(now, cpu, float(mem.percent), int(mem.total), int(mem.available),
                                self._cpu_count, process_count)
        except Exception as exc:
            errors.append(f"System-wide metrics unavailable: {type(exc).__name__}: {exc}")
            return None

    # ------------------------------------------------------------- process
    def _sample_process(self, proc: Any, now: float, mem_total: Optional[int]) -> ProcessSample:
        missing: List[str] = []
        ctx = proc.oneshot() if hasattr(proc, "oneshot") else contextlib.nullcontext()
        with ctx:
            pid = int(proc.pid)
            name = self._read("name", proc.name, missing)
            created = self._read("create_time", proc.create_time, missing)
            ppid = self._read("ppid", proc.ppid, missing)
            exe = self._read("exe", proc.exe, missing)
            status = self._read("status", proc.status, missing)
            times = self._read("cpu_times", proc.cpu_times, missing)
            mem = self._read("memory", proc.memory_info, missing)
            threads = self._read("num_threads", proc.num_threads, missing)
            nice = self._read("nice", proc.nice, missing)
            raw_cpu = self._read("cpu_percent", lambda: proc.cpu_percent(interval=None), missing)

        # PID reuse: same PID, different creation time -> a different process.
        reused = False
        if created is not None:
            old = self._pid_created.get(pid)
            if old is not None and abs(old - created) > 1e-3:
                reused = True
                self._baseline.discard((pid, old))
            self._pid_created[pid] = created
        key: ProcessKey = (pid, created if created is not None else -1.0)

        ready = key in self._baseline and raw_cpu is not None
        if raw_cpu is not None:
            self._baseline.add(key)
        per_core = float(raw_cpu) if ready else None
        normalised = None if per_core is None else min(100.0, per_core / self._cpu_count)

        rss = int(mem.rss) if mem is not None and hasattr(mem, "rss") else None
        mem_percent = (rss / mem_total * 100.0) if (rss is not None and mem_total) else None
        user = float(times.user) if times is not None and hasattr(times, "user") else None
        system = float(times.system) if times is not None and hasattr(times, "system") else None

        useful = [x for x in (rss, user, raw_cpu) if x is not None]
        access = "denied" if not useful else ("partial" if missing else "ok")
        return ProcessSample(
            pid=pid, name=name or f"<pid {pid}>", sampled_at=now, ppid=ppid, exe=exe,
            status=str(status) if status is not None else None, create_time=created,
            cpu_percent=normalised, cpu_percent_per_core=per_core, cpu_ready=ready,
            cpu_time_user_s=user, cpu_time_system_s=system, rss_bytes=rss,
            mem_percent=mem_percent, num_threads=threads, nice=nice, access=access,
            missing=tuple(missing), pid_reused=reused,
        )

    # ---------------------------------------------------------------- API
    def collect(self) -> CollectionResult:
        """Take one sample of every visible process.  Never raises."""
        now = time.time()
        errors: List[str] = []
        samples: List[ProcessSample] = []
        exited = denied = 0

        mem_total: Optional[int] = None
        try:
            mem_total = int(self._ps.virtual_memory().total)
        except Exception:
            pass  # reported by _system_sample below

        try:
            procs = list(self._ps.process_iter())
        except Exception as exc:
            errors.append(f"Could not list processes: {type(exc).__name__}: {exc}")
            procs = []

        first_pass = not self._baseline
        for proc in procs:
            try:
                sample = self._sample_process(proc, now, mem_total)
            except self._gone:
                exited += 1
                continue
            except Exception as exc:  # a bug or odd platform must not kill monitoring
                if len(errors) < MAX_ERROR_MESSAGES:
                    errors.append(f"PID {getattr(proc, 'pid', '?')}: {type(exc).__name__}: {exc}")
                continue
            if sample.access == "denied":
                denied += 1
            samples.append(sample)

        # Forget baselines of processes that disappeared (keeps memory bounded).
        seen: Set[ProcessKey] = {s.key for s in samples}
        self._baseline &= seen
        live_pids = {s.pid for s in samples}
        self._pid_created = {p: c for p, c in self._pid_created.items() if p in live_pids}

        system = self._system_sample(now, len(samples), errors)
        return CollectionResult(samples=samples, system=system, sampled_at=now,
                                skipped_exited=exited, skipped_denied=denied,
                                errors=errors, warming_up=first_pass)

    def reset(self) -> None:
        """Forget all CPU baselines (the next pass is a warm-up pass again)."""
        self._baseline.clear()
        self._pid_created.clear()
        self._system_primed = False
