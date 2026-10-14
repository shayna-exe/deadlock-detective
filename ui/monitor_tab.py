"""Live Processes tab: monitoring controls, searchable/sortable table and details panel.

The table only ever shows what the background worker has stored; the worker never
touches widgets.  ``update(snapshot)`` is called from the Tk main thread.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, Optional

from process_monitor import MonitorSnapshot
from process_monitor.recommendations import CATEGORIES, ProcessAssessment

from .process_card import ProcessCard
from .viewmodels import ALL, BADGES, SORT_OPTIONS, filter_and_sort, fmt_clock, process_row, statuses
from .widgets import AMBER, MUTED, Tooltip

COLUMNS = [("name", "Name", 170), ("pid", "PID", 60), ("cpu", "CPU %", 80), ("cputime", "CPU time", 90),
           ("ram", "RAM", 80), ("mem", "Mem %", 60), ("status", "Status", 80),
           ("rec", "Recommendation", 230), ("upd", "Updated", 70)]
TIPS = {
    "CPU %": "Current CPU use over the last sample, as a share of ALL cores (100 = every core busy).",
    "CPU time": "Cumulative CPU seconds the process has used since it started. Not elapsed time, not a percentage.",
    "RAM": "Resident memory: the part of the program currently held in physical memory.",
    "Status": "Process state reported by the operating system (running, sleeping, stopped, ...).",
}


class LiveProcessesTab(ttk.Frame):
    def __init__(self, parent, services, family: str, on_selection=None) -> None:
        super().__init__(parent, padding=8)
        self.services, self.family = services, family
        self._snapshot: Optional[MonitorSnapshot] = None
        self._by_iid: Dict[str, ProcessAssessment] = {}
        self._manual_busy = False
        self.on_selection = on_selection
        self._build()
        self.update_state(None)

    # ---------------------------------------------------------------- layout
    def _build(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.btn_toggle = ttk.Button(top, text="Start monitoring", command=self.toggle)
        self.btn_toggle.pack(side="left")
        self.btn_refresh = ttk.Button(top, text="Refresh now", command=self.refresh_now)
        self.btn_refresh.pack(side="left", padx=(6, 0))
        ttk.Label(top, text="  Interval (s):").pack(side="left")
        self.interval_var = tk.StringVar(value=f"{self.services.settings.sample_interval_s:g}")
        spin = ttk.Spinbox(top, from_=0.5, to=60, increment=0.5, width=5, textvariable=self.interval_var,
                           command=self.apply_interval)
        spin.pack(side="left")
        spin.bind("<Return>", lambda _e: self.apply_interval())
        spin.bind("<FocusOut>", lambda _e: self.apply_interval())
        self.status_var = tk.StringVar()
        ttk.Label(top, textvariable=self.status_var, foreground=MUTED).pack(side="left", padx=12)

        flt = ttk.Frame(self)
        flt.pack(fill="x", pady=(6, 4))
        ttk.Label(flt, text="Search name or PID:").pack(side="left")
        self.query = tk.StringVar()
        entry = ttk.Entry(flt, textvariable=self.query, width=20)
        entry.pack(side="left", padx=(4, 10))
        self.query.trace_add("write", lambda *_: self.render())
        ttk.Label(flt, text="Sort by:").pack(side="left")
        self.sort_var = tk.StringVar(value=SORT_OPTIONS[0])
        sort = ttk.Combobox(flt, textvariable=self.sort_var, values=SORT_OPTIONS, state="readonly", width=10)
        sort.pack(side="left", padx=(4, 10))
        sort.bind("<<ComboboxSelected>>", lambda _e: self.render())
        ttk.Label(flt, text="Recommendation:").pack(side="left")
        self.cat_var = tk.StringVar(value=ALL)
        cat = ttk.Combobox(flt, textvariable=self.cat_var, values=[ALL, *CATEGORIES], state="readonly", width=32)
        cat.pack(side="left", padx=(4, 10))
        cat.bind("<<ComboboxSelected>>", lambda _e: self.render())
        ttk.Label(flt, text="State:").pack(side="left")
        self.state_var = tk.StringVar(value=ALL)
        self.state_box = ttk.Combobox(flt, textvariable=self.state_var, values=[ALL], state="readonly", width=12)
        self.state_box.pack(side="left", padx=4)
        self.state_box.bind("<<ComboboxSelected>>", lambda _e: self.render())

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        self.message = ttk.Label(left, text="", foreground=AMBER, wraplength=700, justify="left")
        self.message.pack(fill="x")
        self.tree = ttk.Treeview(left, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=width, anchor="w", stretch=key in ("name", "rec"))
        ybar = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ybar.set)
        ybar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        for cat_name, (_sym, color) in BADGES.items():
            self.tree.tag_configure(cat_name, foreground=color)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        Tooltip(self.tree, "CPU % = current use of all cores. CPU time = cumulative CPU seconds. "
                           "RAM = resident memory. Select a row for the evidence behind its recommendation.")
        body.add(left, weight=3)
        self.card = ProcessCard(body, self.services, self.family, on_action_done=self.refresh_now)
        body.add(self.card, weight=2)

    # --------------------------------------------------------------- control
    def toggle(self) -> None:
        mon = self.services.monitoring
        if mon is None:
            return
        if mon.is_running():
            mon.stop()
        else:
            mon.start()
        self.update_state(self._snapshot)

    def apply_interval(self) -> None:
        try:
            value = float(self.interval_var.get())
            self.services.apply_settings(self.services.settings.with_changes(sample_interval_s=value))
        except ValueError as exc:
            messagebox.showerror("Deadlock Detective", f"Invalid interval: {exc}", parent=self)
            self.interval_var.set(f"{self.services.settings.sample_interval_s:g}")

    def refresh_now(self) -> None:
        """One sample on a short-lived thread so the window never freezes."""
        mon = self.services.monitoring
        if mon is None or self._manual_busy:
            return
        self._manual_busy = True

        def work() -> None:
            try:
                mon.sample_once()
            finally:
                self._manual_busy = False

        threading.Thread(target=work, name="deadlock-detective-refresh", daemon=True).start()

    # ---------------------------------------------------------------- display
    def update_state(self, snap: Optional[MonitorSnapshot]) -> None:
        mon = self.services.monitoring
        if mon is None:
            self.btn_toggle.configure(state="disabled")
            self.btn_refresh.configure(state="disabled")
            self.status_var.set("Unavailable")
            self.message.configure(text=self.services.monitoring_error or "Monitoring is unavailable.")
            return
        running = mon.is_running()
        self.btn_toggle.configure(text="Stop monitoring" if running else "Start monitoring")
        if snap is None:
            self.status_var.set("Monitoring running: collecting the first sample..." if running
                                else "Monitoring stopped. Press Start monitoring.")
            self.message.configure(text="")
            return
        state = "running" if running else "stopped"
        self.status_var.set(f"Monitoring {state} | {len(snap.assessments)} processes | last update "
                            f"{fmt_clock(snap.sampled_at)}")
        notes = []
        if snap.warming_up:
            notes.append("Warming up: the first CPU reading of each process is not meaningful, so CPU % "
                         "appears after the next sample.")
        if snap.errors:
            notes.append(f"{len(snap.errors)} collection problem(s), e.g. {snap.errors[0]}")
        if snap.skipped_denied:
            notes.append(f"{snap.skipped_denied} process(es) are not readable (access denied).")
        self.message.configure(text=" ".join(notes))

    def update(self, snap: Optional[MonitorSnapshot]) -> None:
        self._snapshot = snap
        self.update_state(snap)
        if snap is not None:
            self.state_box.configure(values=[ALL, *statuses(snap.assessments)])
        self.render()

    def render(self) -> None:
        snap = self._snapshot
        selected = self.tree.selection()
        keep = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        self._by_iid = {}
        if snap is None:
            return
        rows = filter_and_sort(snap.assessments, self.query.get(), self.cat_var.get(), self.state_var.get(),
                               self.sort_var.get())
        for a in rows:
            iid = f"{a.sample.pid}:{a.sample.create_time}"
            self._by_iid[iid] = a
            self.tree.insert("", "end", iid=iid, values=process_row(a), tags=(a.category,))
        if keep in self._by_iid:
            self.tree.selection_set(keep)
            self.card.show(self._by_iid[keep])
        else:
            self.card.show(None)
        if not rows and snap.assessments:
            self.message.configure(text="No process matches the current search or filters.")

    def _selected(self, _event=None) -> None:
        sel = self.tree.selection()
        a = self._by_iid.get(sel[0]) if sel else None
        self.card.show(a)
        if self.on_selection:
            self.on_selection(a)
