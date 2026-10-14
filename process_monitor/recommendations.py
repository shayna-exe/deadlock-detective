"""Transparent, rule-based recommendations for real processes.

This is a plain set of if-rules over measured values, NOT machine learning.
Every result carries the evidence, the rule and thresholds that fired, an
evidence-strength label, a suggested next step and the limitations of the
conclusion.  Low CPU alone never proves that an application is unused.

Rule order (first match becomes the primary category; the rest become notes):

    R1 protected -> R2 unavailable -> R3 lower priority -> R4 high CPU
    -> R5 investigate -> R6 consider closing -> R7 potentially idle
    -> R8 high memory -> R9 keep running
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .activity_tracker import ActivityTracker, WindowStats
from .models import MB, ProcessSample
from .protection import classify_protection
from .settings import MonitorSettings

KEEP = "Keep Running"
HIGH_CPU = "High CPU Usage"
HIGH_MEM = "High Memory Usage"
IDLE = "Potentially Idle Resource Consumer"
CLOSE = "Consider Closing"
LOWER = "Consider Lowering Priority"
INVESTIGATE = "Investigate"
PROTECTED = "Protected / Action Not Recommended"
UNAVAILABLE = "Monitoring Unavailable"

CATEGORIES = (KEEP, HIGH_CPU, HIGH_MEM, IDLE, CLOSE, LOWER, INVESTIGATE, PROTECTED, UNAVAILABLE)

#: Evidence-strength labels (they describe the measurements, not certainty about intent).
WEAK, MODERATE, STRONG, NOT_APPLICABLE = "Weak", "Moderate", "Strong", "n/a"

#: One-line, plain-language meaning of each category (shown as tooltips / legend).
CATEGORY_HELP: Dict[str, str] = {
    KEEP: "Looks active or ordinary. No strong evidence that any action is needed.",
    HIGH_CPU: "Sustained high CPU use. This may be perfectly normal for the work being done.",
    HIGH_MEM: "Large memory footprint compared with your configured limits.",
    IDLE: "Low CPU for a long time while still holding memory. It may simply be waiting for you.",
    CLOSE: "Low activity for a long time and not protected. Closing is an option; check first.",
    LOWER: "Heavy CPU use by a non-critical process; a lower priority may help other programs.",
    INVESTIGATE: "Unusual pattern (such as steadily growing memory). Worth a closer look.",
    PROTECTED: "Critical, protected or unidentifiable process. Management actions are disabled.",
    UNAVAILABLE: "Not enough reliable data yet (too few samples, no CPU baseline or access denied).",
}


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {sec} s" if sec else f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


def fmt_mb(mb: Optional[float]) -> str:
    if mb is None:
        return "n/a"
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


@dataclass
class ProcessAssessment:
    sample: ProcessSample
    category: str
    headline: str
    evidence: List[str]
    rule_id: str
    rule_detail: str                    # the thresholds that were applied
    strength: str                       # Weak / Moderate / Strong / n/a
    next_step: str
    limitations: List[str]
    samples_observed: int
    low_activity_s: float = 0.0
    memory_estimate_mb: Optional[float] = None   # an ESTIMATE of RAM that might be freed
    also: List[str] = field(default_factory=list)  # secondary observations
    protected: bool = False
    protected_reason: str = ""

    @property
    def pid(self) -> int:
        return self.sample.pid

    @property
    def name(self) -> str:
        return self.sample.name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "process": self.sample.to_dict(),
            "recommendation": self.category,
            "headline": self.headline,
            "evidence": list(self.evidence),
            "rule_id": self.rule_id,
            "rule_thresholds": self.rule_detail,
            "evidence_strength": self.strength,
            "suggested_next_step": self.next_step,
            "limitations": list(self.limitations),
            "samples_observed": self.samples_observed,
            "low_activity_seconds": round(self.low_activity_s, 1),
            "estimated_memory_release_mb": (None if self.memory_estimate_mb is None
                                            else round(self.memory_estimate_mb, 1)),
            "memory_estimate_note": ("Estimate only: actual released memory can differ because of shared "
                                     "memory, caches, child processes and delayed clean-up."
                                     if self.memory_estimate_mb is not None else None),
            "other_observations": list(self.also),
            "protected": self.protected,
            "protected_reason": self.protected_reason or None,
        }


GENERIC_LIMITS = [
    "Based only on CPU time and memory measurements; the program's purpose and your intent are unknown.",
    "Low CPU use can also mean the program is waiting for input, sleeping normally or waiting on a resource.",
]


def _already_low_priority(nice: Optional[int]) -> bool:
    if nice is None:
        return False
    if sys.platform == "win32":
        return nice in (64, 16384)      # IDLE_PRIORITY_CLASS, BELOW_NORMAL_PRIORITY_CLASS
    return nice >= 10


class RecommendationEngine:
    def __init__(self, settings: MonitorSettings, own_pids: Optional[Iterable[int]] = None) -> None:
        self.settings = settings
        self.own_pids = set(own_pids) if own_pids is not None else None

    # --------------------------------------------------------------- helpers
    def _evidence_basics(self, s: ProcessSample, n: int) -> List[str]:
        cpu = "not yet measurable" if s.cpu_percent is None else f"{s.cpu_percent:.1f}% of total CPU capacity"
        total = s.cpu_time_total_s
        return [
            f"Current CPU use: {cpu}.",
            "Cumulative CPU time: " + ("n/a" if total is None else fmt_duration(total)) +
            " (CPU seconds consumed since start, not elapsed time).",
            f"Memory in RAM: {fmt_mb(s.rss_mb)}" +
            ("" if s.mem_percent is None else f" ({s.mem_percent:.1f}% of physical memory)") + ".",
            f"Samples with a valid CPU reading: {n}.",
        ]

    def _memory_flag(self, s: ProcessSample) -> Optional[str]:
        st = self.settings
        if s.rss_mb is None:
            return None
        if s.rss_mb >= st.high_memory_mb:
            return (f"absolute rule: {fmt_mb(s.rss_mb)} is at or above the configured "
                    f"{fmt_mb(st.high_memory_mb)}")
        if s.mem_percent is not None and s.mem_percent >= st.high_memory_percent:
            return (f"percentage rule: {s.mem_percent:.1f}% of physical memory is at or above the "
                    f"configured {st.high_memory_percent:g}%")
        return None

    # ----------------------------------------------------------------- core
    def assess(self, s: ProcessSample, tracker: ActivityTracker) -> ProcessAssessment:
        st = self.settings
        n = tracker.samples_observed(s.key)
        base = self._evidence_basics(s, n)
        prot = classify_protection(s, st, self.own_pids)

        def make(category: str, headline: str, rule_id: str, rule_detail: str, strength: str,
                 next_step: str, limits: Sequence[str], evidence: Optional[List[str]] = None,
                 low: float = 0.0, estimate: bool = False, also: Optional[List[str]] = None) -> ProcessAssessment:
            return ProcessAssessment(
                sample=s, category=category, headline=headline,
                evidence=(evidence if evidence is not None else []) + base,
                rule_id=rule_id, rule_detail=rule_detail, strength=strength, next_step=next_step,
                limitations=list(limits), samples_observed=n, low_activity_s=low,
                memory_estimate_mb=s.rss_mb if estimate else None, also=also or [],
                protected=prot.protected, protected_reason=prot.reason)

        # --- R1 protected -------------------------------------------------
        if prot.protected:
            return make(PROTECTED, f"Protected: {prot.reason}", "R1",
                        "protected-name list, reserved IDs, OS folders, own process, unidentifiable name",
                        NOT_APPLICABLE,
                        "Leave this process alone. Terminating, suspending or re-prioritising it is disabled.",
                        ["Closing critical system processes can crash or freeze the computer."],
                        also=self._secondary(s, tracker))

        # --- R2 monitoring unavailable -----------------------------------
        needed = st.min_samples_for_analysis
        if s.access == "denied":
            return make(UNAVAILABLE, "Monitoring unavailable: this process cannot be read (access denied).",
                        "R2", "access == denied", NOT_APPLICABLE,
                        "Run Deadlock Detective with higher privileges only if you really need these numbers; "
                        "otherwise treat this process as unknown.",
                        ["Permission restrictions hide this process's metrics; management actions are disabled."])
        if not s.cpu_ready or s.cpu_percent is None:
            return make(UNAVAILABLE, "Monitoring unavailable: waiting for a CPU baseline "
                        "(the first reading of a process is not meaningful).", "R2",
                        "cpu baseline required", NOT_APPLICABLE,
                        "Wait for the next refresh.", ["Fewer than two readings so far."])
        if n < needed:
            return make(UNAVAILABLE, f"Monitoring unavailable: only {n} of the {needed} samples needed for analysis.",
                        "R2", f"min_samples_for_analysis={needed}", NOT_APPLICABLE,
                        "Keep monitoring; conclusions need more samples.", ["Too little history to judge a pattern."])

        low = tracker.low_activity(s.key)
        mem_flag = self._memory_flag(s)
        also = self._secondary(s, tracker)

        # --- R3 lower priority ---------------------------------------------
        hi_lower = tracker.high_activity(s.key, st.lower_priority_cpu_percent)
        if (hi_lower.seconds >= st.lower_priority_min_seconds and s.nice is not None
                and not _already_low_priority(s.nice)):
            return make(LOWER,
                        f"Consider lowering priority: CPU stayed at or above {st.lower_priority_cpu_percent:g}% "
                        f"for {fmt_duration(hi_lower.seconds)} ({hi_lower.samples} samples, mean "
                        f"{hi_lower.mean_cpu:.0f}%).",
                        "R3", f"lower_priority_cpu_percent={st.lower_priority_cpu_percent:g}, "
                              f"lower_priority_min_seconds={st.lower_priority_min_seconds:g}",
                        STRONG if hi_lower.seconds >= 3 * st.lower_priority_min_seconds else MODERATE,
                        "If other programs feel slow, you may lower this process's priority so it yields CPU "
                        "time. It keeps running; the work simply gets less CPU when there is competition.",
                        ["Heavy CPU use may be exactly what you want (a render, build or download).",
                         "Lowering priority can make this program finish later.",
                         "Priority only matters while processes compete for the CPU."],
                        evidence=[f"CPU range during the window: {hi_lower.min_cpu:.0f}%–{hi_lower.max_cpu:.0f}%."],
                        also=also)

        # --- R4 high CPU ---------------------------------------------------
        hi = tracker.high_activity(s.key, st.high_cpu_percent)
        if hi.seconds >= st.high_cpu_min_seconds:
            return make(HIGH_CPU,
                        f"High CPU: at or above {st.high_cpu_percent:g}% for {fmt_duration(hi.seconds)} "
                        f"({hi.samples} samples, mean {hi.mean_cpu:.0f}%).",
                        "R4", f"high_cpu_percent={st.high_cpu_percent:g}, high_cpu_min_seconds={st.high_cpu_min_seconds:g}",
                        STRONG if hi.seconds >= 3 * st.high_cpu_min_seconds else MODERATE,
                        "Check whether this is work you started. If not, investigate what the program is doing.",
                        ["High CPU use is not automatically harmful or a sign of a fault."],
                        evidence=[f"CPU range during the window: {hi.min_cpu:.0f}%–{hi.max_cpu:.0f}%."],
                        also=also)

        # --- R5 investigate (steady memory growth) -------------------------
        growth = tracker.memory_growth_mb(s.key, st.growth_min_samples)
        if growth is not None and growth[0] >= st.growth_min_mb:
            return make(INVESTIGATE,
                        f"Investigate: memory grew by about {fmt_mb(growth[0])} across the last {growth[1]} readings "
                        "without shrinking.", "R5",
                        f"growth_min_mb={st.growth_min_mb:g}, growth_min_samples={st.growth_min_samples}",
                        WEAK,
                        "Watch whether memory keeps growing. If it does and the program is not doing something "
                        "memory-heavy, saving your work and restarting it is an option.",
                        ["Growing memory is normal while loading data or filling caches; it is not proof of a leak."],
                        also=also)

        # --- R6 consider closing -------------------------------------------
        mem = s.rss_mb or 0.0
        if (low.seconds >= st.close_min_seconds and low.samples >= needed and mem >= st.close_min_memory_mb):
            strong = low.seconds >= 3 * st.close_min_seconds and low.samples >= 3 * needed
            return make(CLOSE,
                        f"Consider closing: CPU activity stayed at or below {st.idle_cpu_percent:g}% for "
                        f"{fmt_duration(low.seconds)} across {low.samples} samples, while the process kept about "
                        f"{fmt_mb(mem)} of memory. Check whether you still need this application before closing it.",
                        "R6", f"idle_cpu_percent={st.idle_cpu_percent:g}, close_min_seconds={st.close_min_seconds:g}, "
                              f"close_min_memory_mb={st.close_min_memory_mb:g}",
                        STRONG if strong else MODERATE,
                        "Look at the application. If you are finished with it, close it normally from its own "
                        "window so it can save your work. Use the Actions panel only as a last resort.",
                        GENERIC_LIMITS + ["Closing may lose unsaved work or interrupt a background task."],
                        evidence=[f"Mean CPU while low: {low.mean_cpu:.2f}% (max {low.max_cpu:.2f}%)."],
                        low=low.seconds, estimate=True, also=also)

        # --- R7 potentially idle -------------------------------------------
        if low.seconds >= st.idle_min_seconds and mem >= st.idle_min_memory_mb:
            return make(IDLE,
                        f"Potentially idle: CPU at or below {st.idle_cpu_percent:g}% for {fmt_duration(low.seconds)} "
                        f"({low.samples} samples) while holding about {fmt_mb(mem)} of memory.",
                        "R7", f"idle_cpu_percent={st.idle_cpu_percent:g}, idle_min_seconds={st.idle_min_seconds:g}, "
                              f"idle_min_memory_mb={st.idle_min_memory_mb:g}",
                        MODERATE if low.seconds >= 2 * st.idle_min_seconds else WEAK,
                        "Nothing needs to be done. If you want the memory back, check whether you still need it.",
                        GENERIC_LIMITS, evidence=[f"Mean CPU while low: {low.mean_cpu:.2f}% (max {low.max_cpu:.2f}%)."],
                        low=low.seconds, estimate=True, also=also)

        # --- R8 high memory ------------------------------------------------
        if mem_flag:
            return make(HIGH_MEM, f"High memory: {mem_flag}.", "R8",
                        f"high_memory_mb={st.high_memory_mb:g}, high_memory_percent={st.high_memory_percent:g}",
                        MODERATE,
                        "Check whether the program really needs this much memory (large files, many tabs, caches).",
                        ["A large footprint is normal for some programs.",
                         "RSS counts shared memory pages too, so it can overstate what closing would free."],
                        low=low.seconds, estimate=True, also=also)

        # --- R9 keep running -----------------------------------------------
        return make(KEEP, "Keep running: no rule suggests any action.", "R9", "no other rule matched",
                    NOT_APPLICABLE, "No action needed.", ["Absence of a warning is not a guarantee of anything."],
                    low=low.seconds, also=also)

    def _secondary(self, s: ProcessSample, tracker: ActivityTracker) -> List[str]:
        """Other facts worth knowing that did not decide the primary category."""
        notes: List[str] = []
        flag = self._memory_flag(s)
        if flag:
            notes.append("Memory is also high (" + flag + ").")
        if s.pid_reused:
            notes.append("This PID was previously used by a different process; history was reset.")
        if s.missing:
            notes.append("Unreadable attributes: " + ", ".join(s.missing) + ".")
        return notes

    def assess_all(self, samples: Iterable[ProcessSample], tracker: ActivityTracker) -> List[ProcessAssessment]:
        out = []
        for s in samples:
            a = self.assess(s, tracker)
            tracker.note_category(s, a.category, a.headline)
            out.append(a)
        return out
