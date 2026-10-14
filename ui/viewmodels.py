"""Tk-free helpers that prepare data for the GUI (so they can be unit-tested without a display)."""
from __future__ import annotations

import time
from typing import Iterable, List, Optional, Sequence, Tuple

from process_monitor.recommendations import (CATEGORIES, CLOSE, HIGH_CPU, HIGH_MEM, IDLE, INVESTIGATE, KEEP, LOWER,
                                             PROTECTED, UNAVAILABLE, ProcessAssessment, fmt_duration)

SORT_OPTIONS = ("CPU %", "Memory", "CPU time", "Name")
ALL = "All"

#: Symbol + colour per category.  The symbol/text carries the meaning, colour only reinforces it.
BADGES = {
    KEEP: ("✔", "#1b7a3d"),
    HIGH_CPU: ("▲", "#b42318"),
    HIGH_MEM: ("▲", "#b7791f"),
    IDLE: ("●", "#2b5c8a"),
    CLOSE: ("◆", "#8a5a00"),
    LOWER: ("▼", "#b7791f"),
    INVESTIGATE: ("?", "#7c3aed"),
    PROTECTED: ("■", "#52606d"),
    UNAVAILABLE: ("…", "#52606d"),
}


def badge_text(category: str) -> str:
    return f"{BADGES.get(category, ('', ''))[0]} {category}".strip()


def fmt_cpu_percent(a: ProcessAssessment) -> str:
    p = a.sample.cpu_percent
    return "warming up" if p is None else f"{p:.1f}"


def fmt_cpu_time(a: ProcessAssessment) -> str:
    t = a.sample.cpu_time_total_s
    return "n/a" if t is None else fmt_duration(t)


def fmt_ram(a: ProcessAssessment) -> str:
    mb = a.sample.rss_mb
    return "n/a" if mb is None else f"{mb:,.0f} MB"


def fmt_mem_percent(a: ProcessAssessment) -> str:
    p = a.sample.mem_percent
    return "n/a" if p is None else f"{p:.1f}%"


def fmt_clock(epoch: Optional[float]) -> str:
    return "-" if epoch is None else time.strftime("%H:%M:%S", time.localtime(epoch))


def process_row(a: ProcessAssessment) -> Tuple[str, ...]:
    s = a.sample
    return (s.name, str(s.pid), fmt_cpu_percent(a), fmt_cpu_time(a), fmt_ram(a), fmt_mem_percent(a),
            s.status or "n/a", badge_text(a.category), fmt_clock(s.sampled_at))


def _sort_value(a: ProcessAssessment, sort: str):
    s = a.sample
    if sort == "CPU %":
        return s.cpu_percent if s.cpu_percent is not None else -1.0
    if sort == "Memory":
        return s.rss_bytes if s.rss_bytes is not None else -1
    if sort == "CPU time":
        return s.cpu_time_total_s if s.cpu_time_total_s is not None else -1.0
    return s.name.lower()


def filter_and_sort(assessments: Iterable[ProcessAssessment], query: str = "", category: str = ALL,
                    status: str = ALL, sort: str = "CPU %", descending: Optional[bool] = None
                    ) -> List[ProcessAssessment]:
    """Search by name or PID, filter by recommendation category / process status, then sort."""
    q = query.strip().lower()
    out = []
    for a in assessments:
        if q and q not in a.sample.name.lower() and q != str(a.sample.pid) and q not in str(a.sample.pid):
            continue
        if category != ALL and a.category != category:
            continue
        if status != ALL and (a.sample.status or "n/a") != status:
            continue
        out.append(a)
    if descending is None:
        descending = sort != "Name"
    out.sort(key=lambda a: (_sort_value(a, sort), a.sample.pid), reverse=descending)
    return out


def statuses(assessments: Iterable[ProcessAssessment]) -> List[str]:
    return sorted({a.sample.status or "n/a" for a in assessments})


def scale_series(values: Sequence[Optional[float]], width: float, height: float, pad: Tuple[float, float, float, float],
                 y_max: float) -> List[Optional[Tuple[float, float]]]:
    """Map values to canvas coordinates.  ``None`` stays ``None`` (a gap in the line).

    ``pad`` is (left, top, right, bottom).  y_max <= 0 is treated as 1.
    """
    left, top, right, bottom = pad
    plot_w, plot_h = max(1.0, width - left - right), max(1.0, height - top - bottom)
    y_max = y_max if y_max > 0 else 1.0
    n = len(values)
    points: List[Optional[Tuple[float, float]]] = []
    for i, v in enumerate(values):
        if v is None:
            points.append(None)
            continue
        x = left + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)
        y = top + plot_h * (1 - min(max(v, 0.0), y_max) / y_max)
        points.append((x, y))
    return points


def nice_max(value: float, floor: float = 10.0) -> float:
    """A round upper bound for a chart axis."""
    value = max(value, floor)
    for step in (10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000):
        if value <= step:
            return float(step)
    return float(value)


def overview_attention(assessments: Sequence[ProcessAssessment], limit: int = 5) -> List[ProcessAssessment]:
    """Most important recommendations for the overview (actionable first, strongest evidence first)."""
    order = {CLOSE: 0, LOWER: 1, INVESTIGATE: 2, HIGH_CPU: 3, IDLE: 4, HIGH_MEM: 5}
    strength = {"Strong": 0, "Moderate": 1, "Weak": 2}
    items = [a for a in assessments if a.category in order]
    items.sort(key=lambda a: (order[a.category], strength.get(a.strength, 3), -(a.sample.rss_bytes or 0)))
    return items[:limit]


def card_parts(a: Optional[ProcessAssessment]) -> List[Tuple[str, str]]:
    """Text of an explainable recommendation card as (text, tag) pairs.

    Sections keep INFORMATION (measured facts), ADVICE (suggestion) and
    LIMITATIONS separate; real operations live in the buttons below the text.
    """
    if a is None:
        return [("Select a process", "h"),
                ("Choose a row to see the evidence, the rule that fired and a suggested next step.", "muted")]
    s = a.sample
    tone = {"Keep Running": "good", "Protected / Action Not Recommended": "muted",
            "Monitoring Unavailable": "muted"}.get(a.category, "warn")
    parts: List[Tuple[str, str]] = [
        (f"{s.name}  (PID {s.pid})", "h"),
        (badge_text(a.category), tone),
        (a.headline, "item"),
        ("INFORMATION: what was measured", "h"),
    ]
    parts.extend((e, "item") for e in a.evidence)
    parts.append((f"Rule: {a.rule_id}  |  thresholds: {a.rule_detail}", "muted"))
    parts.append((f"Evidence strength: {a.strength}", "item"))
    if a.also:
        parts.extend((f"Also noted: {n}", "item") for n in a.also)
    if a.memory_estimate_mb is not None:
        parts.append((f"Estimated memory that might become available if it exited: about "
                      f"{a.memory_estimate_mb:,.0f} MB. This is an ESTIMATE; shared memory, caches and child "
                      "processes mean the real figure can differ.", "item"))
    parts.append(("ADVICE: suggested next step", "h"))
    parts.append((a.next_step, "item"))
    parts.append(("LIMITATIONS", "h"))
    parts.extend((l, "item") for l in a.limitations)
    return parts
