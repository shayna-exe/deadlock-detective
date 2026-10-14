"""Overview tab: simulation status, live monitoring summary, top recommendations, incidents, guided demo."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Optional

from lab.demo import GuidedDemo
from process_monitor import MonitorSnapshot
from process_monitor.recommendations import fmt_mb
from simulator import SimulationError

from .reports_tab import REPORTS_DIR
from .viewmodels import badge_text, overview_attention
from .widgets import AMBER, GREEN, MUTED, RED, ReadOnlyText

SIM_LABEL = "SIMULATION (educational model)"
REAL_LABEL = "REAL OPERATING-SYSTEM PROCESSES (measured with psutil)"


class OverviewTab(ttk.Frame):
    def __init__(self, parent, services, family: str, show_view: Callable[[str], None],
                 on_change: Callable[[], None]) -> None:
        super().__init__(parent, padding=8)
        self.services, self.show_view, self.on_change = services, show_view, on_change
        self.demo = GuidedDemo(services.session, self._export_demo, export_path="auto")
        self.cards = ttk.Frame(self)
        self.cards.pack(fill="x")
        self.vars = {}
        for i, (key, label) in enumerate([("deadlock", "Simulation deadlock status"), ("cycles", "Cycles in simulation"),
                                          ("monitor", "Live monitoring"), ("cpu", "System CPU"), ("mem", "System memory")]):
            box = ttk.LabelFrame(self.cards, text=label, padding=6)
            box.grid(row=0, column=i, sticky="nsew", padx=(0, 8))
            self.cards.columnconfigure(i, weight=1)
            var = tk.StringVar(value="-")
            lbl = ttk.Label(box, textvariable=var, font=(family, 13, "bold"))
            lbl.pack(anchor="w")
            self.vars[key] = (var, lbl)

        demo = ttk.LabelFrame(self, text="Guided demonstration (simulation only)", padding=6)
        demo.pack(fill="x", pady=8)
        row = ttk.Frame(demo)
        row.pack(fill="x")
        ttk.Button(row, text="Start demo", command=self.start_demo).pack(side="left")
        self.next_btn = ttk.Button(row, text="Next step", command=self.next_step, state="disabled")
        self.next_btn.pack(side="left", padx=6)
        ttk.Button(row, text="Stop", command=self.stop_demo).pack(side="left")
        self.demo_title = ttk.Label(demo, text="Load → execute events → detect → highlight → explain → compare → recover → verify → export.",
                                    foreground=MUTED)
        self.demo_title.pack(anchor="w", pady=(4, 0))
        self.demo_text = ttk.Label(demo, text="", wraplength=1100, justify="left")
        self.demo_text.pack(anchor="w")

        self.text = ReadOnlyText(self, family, height=18, width=110)
        self.text.pack(fill="both", expand=True)

    # ------------------------------------------------------------ guided demo
    def _export_demo(self, _path) -> Path:
        REPORTS_DIR.mkdir(exist_ok=True)
        name = "demo_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_report.json"
        return self.services.export_report(REPORTS_DIR / name)

    def start_demo(self) -> None:
        self._advance(self.demo.start)

    def next_step(self) -> None:
        self._advance(self.demo.advance)

    def stop_demo(self) -> None:
        self.demo.stop()
        self.next_btn.configure(state="disabled")
        self.demo_title.configure(text="Demonstration stopped.")
        self.demo_text.configure(text="")

    def _advance(self, action) -> None:
        try:
            step = action()
        except (SimulationError, OSError) as exc:
            messagebox.showerror("Deadlock Detective", str(exc), parent=self)
            self.stop_demo()
            return
        self.demo_title.configure(text=step.title, foreground=GREEN if step.finished else "#2b5c8a")
        self.demo_text.configure(text=step.text)
        self.next_btn.configure(state="disabled" if self.demo.finished else "normal")
        self.on_change()
        self.show_view(step.view)

    # ---------------------------------------------------------------- refresh
    def _set(self, key: str, text: str, color: Optional[str] = None) -> None:
        var, lbl = self.vars[key]
        var.set(text)
        lbl.configure(foreground=color or "#1f2933")

    def refresh(self, snap: Optional[MonitorSnapshot]) -> None:
        s = self.services.session
        det = s.last_detection if s.detection_current else None
        if det is None:
            self._set("deadlock", "Not checked" if s.last_detection is None else "Re-run detection", AMBER)
            self._set("cycles", "-")
        elif det.deadlock:
            self._set("deadlock", "DEADLOCK", RED)
            self._set("cycles", f"{len(det.cycles)}", RED)
        else:
            self._set("deadlock", "None detected", GREEN)
            self._set("cycles", "0", GREEN)
        mon = self.services.monitoring
        if mon is None:
            self._set("monitor", "Unavailable", AMBER)
        else:
            self._set("monitor", "Running" if mon.is_running() else "Stopped", GREEN if mon.is_running() else MUTED)
        sysm = snap.system if snap else None
        self._set("cpu", "-" if not sysm or sysm.cpu_percent is None else f"{sysm.cpu_percent:.0f}%")
        self._set("mem", "-" if not sysm or sysm.mem_percent is None else f"{sysm.mem_percent:.0f}%")

        parts = [(SIM_LABEL, "h"), (f"Scenario: {s.scenario.name}   |   event {s.position} of {s.total_events}", "item")]
        inc = self.services.incidents.latest()
        parts.append(("Recent incidents", "h"))
        recent = self.services.incidents.incidents[-3:]
        parts += [(f"{i.id}: {i.scenario_name}: {i.status}", "item") for i in reversed(recent)] or \
                 [("none yet (an incident opens automatically when a deadlock is detected)", "muted")]
        parts += [("", ""), (REAL_LABEL, "h")]
        if mon is None:
            parts.append((self.services.monitoring_error or "Monitoring unavailable.", "warn"))
        elif snap is None:
            parts.append(("No samples yet. Start monitoring on the Live Processes tab.", "muted"))
        else:
            parts.append(("Highest CPU consumers", "h"))
            parts += [(f"{a.name} (PID {a.pid}): {a.sample.cpu_percent:.1f}%", "item") for a in snap.by_cpu(3)] or \
                     [("CPU readings need a second sample.", "muted")]
            parts.append(("Highest memory consumers", "h"))
            parts += [(f"{a.name} (PID {a.pid}): {fmt_mb(a.sample.rss_mb)}", "item") for a in snap.by_memory(3)]
            parts.append(("Important recommendations (advice only)", "h"))
            parts += [(f"{badge_text(a.category)}: {a.name} (PID {a.pid}), evidence {a.strength}", "item")
                      for a in overview_attention(snap.assessments)] or \
                     [("Nothing stands out. Idle rules need several minutes of samples.", "muted")]
        self.text.show(parts)
