"""Resource History tab: charts, top consumers, sustained low activity and the recommendation timeline.

Everything displayed comes from stored real samples; the Clear button empties the history.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from process_monitor import MonitorSnapshot
from process_monitor.models import iso_from_epoch
from process_monitor.recommendations import fmt_duration, fmt_mb

from .widgets import LineChart, MUTED, ReadOnlyText


class HistoryTab(ttk.Frame):
    def __init__(self, parent, services, family: str) -> None:
        super().__init__(parent, padding=8)
        self.services = services
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Bounded history of real samples (the retention limits are in Settings).",
                  foreground=MUTED).pack(side="left")
        ttk.Button(top, text="Clear history", command=self.clear).pack(side="right")
        grid = ttk.Frame(self)
        grid.pack(fill="both", expand=True, pady=(6, 0))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)
        self.cpu_chart = LineChart(grid, "System CPU use (all processes)", "%", family, fixed_max=100.0)
        self.mem_chart = LineChart(grid, "System memory in use", "%", family, fixed_max=100.0)
        self.top_chart = LineChart(grid, "CPU % of the top 3 CPU consumers (right now)", "%", family)
        self.top_mem = LineChart(grid, "RAM (MB) of the top 3 memory consumers (right now)", "", family)
        self.cpu_chart.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 4))
        self.mem_chart.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 4))
        self.top_chart.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        self.top_mem.grid(row=1, column=1, sticky="nsew", padx=(4, 0))
        self.text = ReadOnlyText(self, family, height=11, width=100)
        self.text.pack(fill="x", pady=(6, 0))
        self.update(None)

    def clear(self) -> None:
        mon = self.services.monitoring
        if mon is None:
            return
        if messagebox.askyesno("Clear history", "Delete all stored monitoring samples?", parent=self):
            mon.clear_history()
            self.update(None)

    def update(self, snap: Optional[MonitorSnapshot]) -> None:
        mon = self.services.monitoring
        if mon is None or snap is None:
            for chart in (self.cpu_chart, self.mem_chart, self.top_chart, self.top_mem):
                chart.set_data([])
            self.text.show([("No samples yet", "h"), ("Start monitoring to build a history.", "muted")])
            return
        tr = mon.tracker
        self.cpu_chart.set_data([("CPU", [s.cpu_percent for s in tr.system])])
        self.mem_chart.set_data([("Memory", [s.mem_percent for s in tr.system])])
        top_cpu, top_mem = tr.top_by_cpu(3), tr.top_by_memory(3)
        self.top_chart.set_data([(tr.name_of(k), [p.cpu for p in tr.points(k)]) for k, _ in top_cpu])
        self.top_mem.set_data([(tr.name_of(k), [None if p.rss is None else p.rss / 1048576 for p in tr.points(k)])
                               for k, _ in top_mem])
        parts = [("Top CPU consumers (latest sample)", "h")]
        parts += [(f"{tr.name_of(k)} (PID {k[0]}): {v:.1f}%   cumulative CPU time "
                   f"{fmt_duration(tr.points(k)[-1].cpu_time or 0)}", "item") for k, v in top_cpu] or [("none yet", "muted")]
        parts.append(("Top memory consumers", "h"))
        parts += [(f"{tr.name_of(k)} (PID {k[0]}): {fmt_mb(v / 1048576)}", "item") for k, v in top_mem]
        parts.append(("Sustained low activity (at or below the idle CPU threshold)", "h"))
        low = tr.sustained_low_activity(min_seconds=mon.settings.idle_min_seconds)[:5]
        parts += ([(f"{tr.name_of(k)} (PID {k[0]}): {fmt_duration(w.seconds)} across {w.samples} samples", "item")
                   for k, w in low] or [("No process has been quiet for long enough yet.", "muted")])
        parts.append(("Recommendation timeline (most recent last)", "h"))
        events = list(tr.timeline)[-8:]
        parts += ([(f"{iso_from_epoch(e.t)}  {e.name} (PID {e.pid}): {e.category}", "item") for e in events]
                  or [("No recommendation has changed yet.", "muted")])
        parts.append((f"Samples stored: {len(tr.system)} system, {len(tr.tracked())} processes tracked, "
                      f"{tr.passes} passes.", "muted"))
        self.text.show(parts)
