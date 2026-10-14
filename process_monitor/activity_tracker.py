"""Bounded history of real process samples and sustained-activity maths.

Memory is bounded three ways: a fixed number of samples per process
(``max_samples_per_process``), history of processes that disappeared is dropped
immediately, and the system-wide and timeline deques have a ``maxlen``.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Sequence, Tuple

from .models import ProcessKey, ProcessSample, SystemSample, iso_from_epoch
from .settings import MonitorSettings


@dataclass(frozen=True)
class Point:
    """What we remember about one process at one moment."""
    t: float                         # epoch seconds
    cpu: Optional[float]             # system-normalised %, None if not measurable
    rss: Optional[int]
    cpu_time: Optional[float]        # cumulative CPU seconds


@dataclass(frozen=True)
class WindowStats:
    """Result of looking back over contiguous samples that satisfy a condition."""
    seconds: float                   # span covered, first to last qualifying sample
    samples: int                     # number of qualifying samples
    min_cpu: Optional[float] = None
    max_cpu: Optional[float] = None
    mean_cpu: Optional[float] = None


@dataclass(frozen=True)
class TimelineEvent:
    t: float
    pid: int
    name: str
    category: str
    summary: str

    def to_dict(self) -> dict:
        return {"at": iso_from_epoch(self.t), "pid": self.pid, "name": self.name,
                "category": self.category, "summary": self.summary}


EMPTY = WindowStats(0.0, 0)


class ActivityTracker:
    def __init__(self, settings: MonitorSettings) -> None:
        self.settings = settings
        self._points: Dict[ProcessKey, Deque[Point]] = {}
        self._names: Dict[ProcessKey, str] = {}
        self._last_category: Dict[ProcessKey, str] = {}
        self.system: Deque[SystemSample] = deque(maxlen=settings.max_system_samples)
        self.timeline: Deque[TimelineEvent] = deque(maxlen=settings.max_timeline_events)
        self.passes = 0

    # -------------------------------------------------------------- config
    def apply_settings(self, settings: MonitorSettings) -> None:
        """Adopt new retention limits, keeping the newest data."""
        self.settings = settings
        for key, pts in list(self._points.items()):
            self._points[key] = deque(pts, maxlen=settings.max_samples_per_process)
        self.system = deque(self.system, maxlen=settings.max_system_samples)
        self.timeline = deque(self.timeline, maxlen=settings.max_timeline_events)

    # ------------------------------------------------------------ recording
    def record(self, samples: Iterable[ProcessSample], system: Optional[SystemSample]) -> None:
        samples = list(samples)
        live = set()
        for s in samples:
            live.add(s.key)
            pts = self._points.get(s.key)
            if pts is None:
                pts = deque(maxlen=self.settings.max_samples_per_process)
                self._points[s.key] = pts
            self._names[s.key] = s.name
            # Only samples with a real CPU baseline count as observations of activity.
            pts.append(Point(s.sampled_at, s.cpu_percent if s.cpu_ready else None,
                             s.rss_bytes, s.cpu_time_total_s))
        for key in set(self._points) - live:     # process exited (or PID was reused)
            self._points.pop(key, None)
            self._names.pop(key, None)
            self._last_category.pop(key, None)
        if system is not None:
            self.system.append(system)
        self.passes += 1

    def clear(self) -> None:
        self._points.clear()
        self._names.clear()
        self._last_category.clear()
        self.system.clear()
        self.timeline.clear()
        self.passes = 0

    # -------------------------------------------------------------- queries
    def samples_observed(self, key: ProcessKey) -> int:
        """Samples that carried a valid CPU measurement."""
        return sum(1 for p in self._points.get(key, ()) if p.cpu is not None)

    def points(self, key: ProcessKey) -> List[Point]:
        return list(self._points.get(key, ()))

    def _trailing(self, key: ProcessKey, accept) -> WindowStats:
        """Walk back from the newest sample while ``accept(point)`` holds."""
        pts = self._points.get(key)
        if not pts:
            return EMPTY
        run: List[Point] = []
        for p in reversed(pts):
            if p.cpu is None or not accept(p.cpu):
                break
            run.append(p)
        if not run:
            return EMPTY
        cpus = [p.cpu for p in run if p.cpu is not None]
        return WindowStats(run[0].t - run[-1].t, len(run), min(cpus), max(cpus), sum(cpus) / len(cpus))

    def low_activity(self, key: ProcessKey) -> WindowStats:
        """How long CPU use has stayed at or below ``idle_cpu_percent``."""
        limit = self.settings.idle_cpu_percent
        return self._trailing(key, lambda c: c <= limit)

    def high_activity(self, key: ProcessKey, threshold: float) -> WindowStats:
        """How long CPU use has stayed at or above ``threshold``."""
        return self._trailing(key, lambda c: c >= threshold)

    def memory_growth_mb(self, key: ProcessKey, min_samples: int) -> Optional[Tuple[float, int]]:
        """(growth in MB, samples) from the oldest to newest of the last ``min_samples``
        readings, but only if memory never shrank by more than 5 % between readings."""
        rss = [p.rss for p in self._points.get(key, ()) if p.rss is not None]
        if len(rss) < min_samples:
            return None
        window = rss[-min_samples:]
        if any(b < a * 0.95 for a, b in zip(window, window[1:])):
            return None
        return (window[-1] - window[0]) / (1024 * 1024), len(window)

    # ------------------------------------------------------------ analytics
    def series(self, key: ProcessKey) -> List[Point]:
        return self.points(key)

    def tracked(self) -> List[ProcessKey]:
        return list(self._points)

    def name_of(self, key: ProcessKey) -> str:
        return self._names.get(key, f"<pid {key[0]}>")

    def top_by_cpu(self, n: int = 5) -> List[Tuple[ProcessKey, float]]:
        latest = [(k, pts[-1].cpu) for k, pts in self._points.items() if pts and pts[-1].cpu is not None]
        return sorted(latest, key=lambda kv: kv[1], reverse=True)[:n]

    def top_by_memory(self, n: int = 5) -> List[Tuple[ProcessKey, int]]:
        latest = [(k, pts[-1].rss) for k, pts in self._points.items() if pts and pts[-1].rss is not None]
        return sorted(latest, key=lambda kv: kv[1], reverse=True)[:n]

    def sustained_low_activity(self, min_seconds: float) -> List[Tuple[ProcessKey, WindowStats]]:
        out = []
        for key in self._points:
            w = self.low_activity(key)
            if w.seconds >= min_seconds:
                out.append((key, w))
        return sorted(out, key=lambda kw: kw[1].seconds, reverse=True)

    def note_category(self, sample: ProcessSample, category: str, summary: str) -> None:
        """Add a timeline entry when a process's recommendation category changes
        (``Keep Running`` is the quiet default and is not logged)."""
        prev = self._last_category.get(sample.key, "Keep Running")
        self._last_category[sample.key] = category
        if category != prev and category not in ("Keep Running",):
            self.timeline.append(TimelineEvent(sample.sampled_at, sample.pid, sample.name, category, summary))
