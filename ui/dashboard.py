"""Main Tkinter window.  All logic lives in ``SimulationSession``; this file only
wires buttons to it and displays the results."""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Tuple

from detector import format_cycle
from diagnosis import CONFIRMED, GENERAL, RISK
from recovery import RecoveryResult
from session import SimulationSession
from simulator import SimulationError, format_snapshot

from services import AppServices

from .graph_view import GraphView
from .guide_tab import GuideTab
from .history_tab import HistoryTab
from .lab_tab import RecoveryLabTab, WhatIfTab
from .monitor_tab import LiveProcessesTab
from .overview_tab import OverviewTab
from .recommendations_tab import RecommendationsTab
from .reports_tab import ReportsTab
from .settings_tab import SettingsTab
from .widgets import ACCENT, AMBER, BG, GREEN, MUTED, RED, TEXT, ReadOnlyText

APP_NAME = "Deadlock Detective"
PURPOSE = ("Intelligent deadlock detection, live process monitoring and application lifecycle management. "
           "The deadlock simulator and what-if labs work on SIMULATED processes and locks. The live-process "
           "tabs measure REAL programs and only advise: nothing is ever changed without your confirmation.")
RUN_DELAY_MS = 450

POLL_MS = 500


class Dashboard:
    def __init__(self, root: tk.Tk, session: SimulationSession, services: Optional[AppServices] = None) -> None:
        self.root = root
        self.session = session
        self.services = services or AppServices(session)
        self._running = False
        self._after_id: Optional[str] = None
        self._poll_id: Optional[str] = None
        self._last_seq = -1
        self._last_running: Optional[bool] = None
        self._family = "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"
        root.title(APP_NAME)
        root.geometry("1400x820")
        root.minsize(1150, 700)
        root.configure(background=BG)
        self._style()
        self._build_header()
        self._build_tabs()
        self.reload(self.session.scenario.name)
        self._poll_monitor()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_tabs(self) -> None:
        f, sv = self._family, self.services
        self.main_nb = ttk.Notebook(self.root)
        self.main_nb.pack(fill="both", expand=True)
        self.overview = OverviewTab(self.main_nb, sv, f, self.show_view, self.refresh)
        sim = ttk.Frame(self.main_nb)
        self._build_body(sim)
        self.live = LiveProcessesTab(self.main_nb, sv, f)
        self.recs = RecommendationsTab(self.main_nb, sv, f)
        self.history = HistoryTab(self.main_nb, sv, f)
        self.lab = RecoveryLabTab(self.main_nb, self.session, f, self.refresh)
        self.whatif = WhatIfTab(self.main_nb, self.session, f, self.refresh, self._scenario_added)
        self.reports = ReportsTab(self.main_nb, sv, f)
        self.settings_tab = SettingsTab(self.main_nb, sv, f)
        self.guide = GuideTab(self.main_nb, f)
        self.tabs = {"overview": self.overview, "simulator": sim, "live": self.live, "recs": self.recs,
                     "history": self.history, "lab": self.lab, "whatif": self.whatif, "reports": self.reports,
                     "settings": self.settings_tab, "guide": self.guide}
        for key, title in [("overview", "Overview"), ("simulator", "Deadlock Simulator (simulated)"),
                           ("live", "Live Processes (real)"), ("recs", "Smart Recommendations (real)"),
                           ("history", "Resource History (real)"), ("lab", "Recovery Lab (simulated)"),
                           ("whatif", "What-If Lab (simulated)"), ("reports", "Incidents & Reports"),
                           ("settings", "Settings & Safety"), ("guide", "OS Concept Guide")]:
            self.main_nb.add(self.tabs[key], text=title)

    def show_view(self, view: str) -> None:
        """Bring a part of the UI to the front (used by the guided demo)."""
        target = {"simulator": "simulator", "graph": "simulator", "diagnosis": "simulator",
                  "recovery": "lab", "reports": "reports"}.get(view, "simulator")
        self.main_nb.select(self.tabs[target])
        if view == "diagnosis":
            self.notebook.select(self.diag_text)
        elif view == "recovery" and target == "simulator":
            self.notebook.select(self.recovery_panel)

    def _scenario_added(self, name: str) -> None:
        self.scenario_box.configure(values=self.session.scenario_names)
        self.reload(name)
        self.main_nb.select(self.tabs["simulator"])

    # ------------------------------------------------------- live monitoring
    def _poll_monitor(self) -> None:
        """Runs on the Tk main thread; reads what the worker thread stored (never blocks)."""
        mon = self.services.monitoring
        snap = mon.latest() if mon else None
        running = mon.is_running() if mon else False
        seq = snap.sequence if snap else -1
        if seq != self._last_seq or running != self._last_running:
            self._last_seq, self._last_running = seq, running
            self.live.update(snap)
            self.recs.update(snap)
            self.history.update(snap)
            self.overview.refresh(snap)
        self._poll_id = self.root.after(POLL_MS, self._poll_monitor)

    def on_close(self) -> None:
        """Stop background work cleanly; offer to resume anything this program suspended."""
        self._stop_run()
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        suspended = self.services.shutdown()
        ctl = self.services.controller
        if suspended and ctl is not None:
            names = ", ".join(f"{n} (PID {p})" for p, n in suspended)
            if messagebox.askyesno(APP_NAME, f"These processes are still suspended by this program:\n{names}\n\n"
                                   "Resume them now? (Otherwise they stay frozen.)", parent=self.root):
                mon = self.services.monitoring
                snap = mon.latest() if mon else None
                for a in (snap.assessments if snap else []):
                    if (a.pid, a.name) in suspended:
                        self.services.execute_action(a.sample, "resume", True)
        self.root.destroy()

    # --------------------------------------------------------------- styling
    def _style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        f = self._family
        style.configure(".", background=BG, foreground=TEXT, font=(f, 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG)
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, font=(f, 10, "bold"))
        style.configure("Title.TLabel", font=(f, 20, "bold"), foreground=ACCENT)
        style.configure("Purpose.TLabel", foreground=MUTED)
        style.configure("StatName.TLabel", foreground=MUTED, font=(f, 9))
        style.configure("StatValue.TLabel", font=(f, 13, "bold"))
        style.configure("TButton", padding=(8, 5))
        style.configure("Treeview", rowheight=24, font=(f, 10))
        style.configure("Treeview.Heading", font=(f, 10, "bold"))

    # ---------------------------------------------------------------- layout
    def _build_header(self) -> None:
        head = ttk.Frame(self.root, padding=(14, 10, 14, 4))
        head.pack(fill="x")
        ttk.Label(head, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        self.purpose = ttk.Label(head, text=PURPOSE, style="Purpose.TLabel", wraplength=1200, justify="left")
        self.purpose.pack(anchor="w", pady=(0, 6))
        head.bind("<Configure>", lambda e: self.purpose.configure(wraplength=max(300, e.width - 30)))
        stats = ttk.Frame(head)
        stats.pack(fill="x")
        self.stat_vars = {}
        self.stat_labels = {}
        for i, name in enumerate(["Scenario", "Processes", "Locks", "Blocked processes", "Deadlock status"]):
            box = ttk.Frame(stats, padding=(0, 0, 28, 0))
            box.grid(row=0, column=i, sticky="w")
            ttk.Label(box, text=name, style="StatName.TLabel").pack(anchor="w")
            var = tk.StringVar(value="-")
            lbl = ttk.Label(box, textvariable=var, style="StatValue.TLabel")
            lbl.pack(anchor="w")
            self.stat_vars[name] = var
            self.stat_labels[name] = lbl
        ttk.Separator(self.root).pack(fill="x", pady=(8, 0))

    def _build_body(self, parent) -> None:
        body = ttk.Frame(parent, padding=10)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=3, minsize=470)
        body.columnconfigure(2, weight=2, minsize=430)
        body.rowconfigure(0, weight=1)
        self._build_controls(body).grid(row=0, column=0, sticky="ns", padx=(0, 10))
        self._build_center(body).grid(row=0, column=1, sticky="nsew")
        self._build_right(body).grid(row=0, column=2, sticky="nsew", padx=(10, 0))

    def _build_controls(self, parent) -> ttk.Frame:
        col = ttk.Frame(parent, width=250)
        sc = ttk.LabelFrame(col, text="Scenario", padding=8)
        sc.pack(fill="x")
        self.scenario_var = tk.StringVar(value=self.session.scenario.name)
        self.scenario_box = ttk.Combobox(sc, textvariable=self.scenario_var, state="readonly",
                                         values=self.session.scenario_names, width=28)
        self.scenario_box.pack(fill="x")
        self.scenario_desc = ttk.Label(sc, text="", wraplength=230, justify="left", style="Purpose.TLabel")
        self.scenario_desc.pack(fill="x", pady=(6, 6))
        self.btn_load = ttk.Button(sc, text="Load Scenario", command=self.on_load)
        self.btn_load.pack(fill="x")
        self.btn_reset = ttk.Button(sc, text="Reset Simulation", command=self.on_reset)
        self.btn_reset.pack(fill="x", pady=(4, 0))

        run = ttk.LabelFrame(col, text="Run", padding=8)
        run.pack(fill="x", pady=(10, 0))
        self.progress = ttk.Label(run, text="", style="Purpose.TLabel")
        self.progress.pack(anchor="w", pady=(0, 4))
        self.btn_step = ttk.Button(run, text="Step (next event)", command=self.on_step)
        self.btn_step.pack(fill="x")
        self.btn_run = ttk.Button(run, text="Run All", command=self.on_run_all)
        self.btn_run.pack(fill="x", pady=(4, 0))
        self.btn_detect = ttk.Button(run, text="Detect Deadlocks", command=self.on_detect)
        self.btn_detect.pack(fill="x", pady=(10, 0))
        self.btn_report = ttk.Button(run, text="Export Incident Report (JSON)", command=self.on_report)
        self.btn_report.pack(fill="x", pady=(4, 0))

        return col

    def _build_center(self, parent) -> ttk.Frame:
        col = ttk.Frame(parent)
        col.rowconfigure(0, weight=3)
        col.rowconfigure(1, weight=2)
        col.columnconfigure(0, weight=1)
        gf = ttk.LabelFrame(col, text="Wait-For Graph", padding=6)
        gf.grid(row=0, column=0, sticky="nsew")
        self.graph_view = GraphView(gf, self._family)
        self.graph_view.pack(fill="both", expand=True)

        hf = ttk.LabelFrame(col, text="Event history", padding=6)
        hf.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        cols = [("step", "#", 34), ("process", "Process", 62), ("op", "Operation", 82), ("lock", "Lock", 44),
                ("result", "Result", 82), ("blocked", "Blocked?", 66), ("msg", "Details", 560)]
        self.tree = ttk.Treeview(hf, columns=[c[0] for c in cols], show="headings", height=5)
        for key, title, width in cols:
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=width, anchor="w", stretch=False)
        bar = ttk.Scrollbar(hf, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(hf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=bar.set, xscrollcommand=xbar.set)
        xbar.pack(side="bottom", fill="x")
        bar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("blocked", background="#fdf0d5")
        self.tree.tag_configure("abort", background="#fde4e1")
        self.tree.tag_configure("grant", background="#e3f1e6")
        return col

    def _build_right(self, parent) -> ttk.Frame:
        nb = ttk.Notebook(parent)
        self.diag_text = ReadOnlyText(nb, self._family)
        self.order_text = ReadOnlyText(nb, self._family)
        self.recovery_panel = ttk.Frame(nb, padding=(0, 6, 0, 0))
        self._build_recovery_panel(self.recovery_panel)
        self.recovery_text = ReadOnlyText(self.recovery_panel, self._family)
        self.recovery_text.pack(fill="both", expand=True, pady=(8, 0))
        self.state_text = ReadOnlyText(nb, self._family)
        nb.add(self.diag_text, text="Diagnosis")
        nb.add(self.order_text, text="Lock-order risk")
        nb.add(self.recovery_panel, text="Recovery")
        nb.add(self.state_text, text="Lock state")
        self.notebook = nb
        return nb

    def _build_recovery_panel(self, panel: ttk.Frame) -> None:
        box = ttk.LabelFrame(panel, text="Simulated recovery: abort a process", padding=8)
        box.pack(fill="x")
        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="Process:").pack(side="left")
        self.victim_var = tk.StringVar()
        self.victim_box = ttk.Combobox(row, textvariable=self.victim_var, state="readonly", width=8)
        self.victim_box.pack(side="left", padx=(4, 8))
        self.btn_abort = ttk.Button(row, text="Abort Selected Process", command=self.on_abort)
        self.btn_abort.pack(side="left")
        self.btn_auto = ttk.Button(box, text="Abort Suggested Victim (fewest locks held)", command=self.on_auto_recover)
        self.btn_auto.pack(fill="x", pady=(6, 0))
        self.suggest = ttk.Label(box, text="", wraplength=380, justify="left", style="Purpose.TLabel")
        self.suggest.pack(fill="x", pady=(6, 0))
        self.suggest_wrap = lambda e: self.suggest.configure(wraplength=max(200, e.width - 20))
        box.bind("<Configure>", self.suggest_wrap)

    # --------------------------------------------------------------- actions
    def _safely(self, action) -> bool:
        try:
            action()
            return True
        except SimulationError as exc:
            self._stop_run()
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            self.refresh()
            return False

    def reload(self, name: str) -> None:
        self._stop_run()
        self.session.load(name)
        self.scenario_var.set(name)
        self.scenario_box.configure(values=self.session.scenario_names)
        self.scenario_desc.configure(text=self.session.scenario.description)
        self.refresh()

    def on_load(self) -> None:
        self.reload(self.scenario_var.get())

    def on_reset(self) -> None:
        self.reload(self.session.scenario.name)

    def on_step(self) -> None:
        self._stop_run()
        self._safely(self.session.step)
        self.refresh()

    def on_run_all(self) -> None:
        if self._running:
            self._stop_run()
            self.refresh()
            return
        if not self.session.has_next:
            return
        self._running = True
        self._tick()
        self.refresh()

    def _tick(self) -> None:
        """One scheduled step of 'Run All'; yields to the Tk event loop between steps."""
        self._after_id = None
        if not self._running:
            return
        if not self.session.has_next or not self._safely(self.session.step):
            self._stop_run()
            self.refresh()
            return
        self.refresh()
        if self.session.has_next:
            self._after_id = self.root.after(RUN_DELAY_MS, self._tick)
        else:
            self._stop_run()
            self.refresh()

    def _stop_run(self) -> None:
        self._running = False
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None

    def on_detect(self) -> None:
        self._stop_run()
        result = self.session.detect()
        self.refresh()
        self.notebook.select(self.diag_text)
        if result.repeated:
            self.diag_text.show(self.diag_text_parts(prefix="Same deadlock as the last detection run; "
                                                      "nothing has changed since."))

    def on_abort(self) -> None:
        victim = self.victim_var.get()
        if not victim:
            messagebox.showinfo(APP_NAME, "Choose a process to abort first.", parent=self.root)
            return
        self._recover(lambda: self.session.abort_process(victim))

    def on_auto_recover(self) -> None:
        self._recover(self.session.auto_recover)

    def _recover(self, action) -> None:
        self._stop_run()
        holder: List[RecoveryResult] = []
        if self._safely(lambda: holder.append(action())):
            self.refresh()
            self.notebook.select(self.recovery_panel)

    def on_report(self) -> None:
        self._stop_run()
        reports = Path(__file__).resolve().parent.parent / "reports"
        name = self.session.scenario.name.lower().replace(" ", "_").replace("-", "_") + "_report.json"
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save report", defaultextension=".json",
            initialdir=str(reports if reports.is_dir() else Path.home()), initialfile=name,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            saved = self.services.export_report(path, overwrite=True)
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, f"The report could not be written:\n{exc}", parent=self.root)
            return
        self.refresh()
        messagebox.showinfo(APP_NAME, f"Report saved to:\n{saved}", parent=self.root)

    # --------------------------------------------------------------- refresh
    def refresh(self) -> None:
        s = self.session
        det = s.last_detection if s.detection_current else None
        cycles = det.cycles if det else []

        self.stat_vars["Scenario"].set(s.scenario.name)
        self.stat_vars["Processes"].set(str(len(s.state.processes)))
        self.stat_vars["Locks"].set(str(len(s.state.locks)))
        self.stat_vars["Blocked processes"].set(str(len(s.state.blocked_processes())))
        if det is None:
            text, color = ("Not checked", MUTED) if s.last_detection is None else ("Re-run detection", AMBER)
        elif det.deadlock:
            text, color = "DEADLOCK", RED
        else:
            text, color = "None detected", GREEN
        self.stat_vars["Deadlock status"].set(text)
        self.stat_labels["Deadlock status"].configure(foreground=color)

        state = "current" if det is not None else ("unchecked" if s.last_detection is None else "stale")
        self.graph_view.update_graph(s.graph, cycles, state)
        self._fill_history()
        self.progress.configure(text=f"Event {s.position} of {s.total_events}")
        self.btn_step.configure(state="normal" if s.has_next else "disabled")
        self.btn_run.configure(text="Pause" if self._running else "Run All",
                               state="normal" if (s.has_next or self._running) else "disabled")

        self.diag_text.show(self.diag_text_parts())
        self._fill_order()
        self._fill_recovery()
        self.state_text.show([("Current ownership and waiting", "h")] +
                             [(l, "item") for l in format_snapshot(s.state.snapshot())])
        self._fill_recovery_controls()
        if hasattr(self, "lab"):                  # secondary tabs exist once the UI is fully built
            self.lab.refresh()
            self.whatif.refresh()
            self.reports.refresh()
            mon = self.services.monitoring
            self.overview.refresh(mon.latest() if mon else None)

    def _fill_history(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for e in self.session.state.history:
            tag = "blocked" if e.blocked else "abort" if e.operation == "ABORT" else \
                  "grant" if e.operation == "GRANT" else ""
            self.tree.insert("", "end", values=(e.step, e.process, e.operation, e.lock or "-", e.result,
                                                "Yes" if e.blocked else "No", e.message), tags=(tag,))
        kids = self.tree.get_children()
        if kids:
            self.tree.see(kids[-1])

    def diag_text_parts(self, prefix: str = "") -> List[Tuple[str, str]]:
        s = self.session
        if s.last_detection is None:
            return [("Diagnosis", "h"),
                    ("Detection has not been run for this scenario. Step through the events, then press "
                     "“Detect Deadlocks”.", "muted")]
        parts: List[Tuple[str, str]] = []
        if not s.detection_current:
            parts.append(("The state has changed since the last detection run. The text below describes "
                          "the current state; press “Detect Deadlocks” to refresh the graph "
                          "highlighting.", "warn"))
        if prefix:
            parts.append((prefix, "warn"))
        d = s.diagnose()
        parts.append(("Status", "h"))
        parts.append((d.headline, "bad" if d.deadlock else "good"))
        if d.cycles:
            parts.append(("Detected cycle(s)", "h"))
            parts.extend((format_cycle(c), "bad") for c in d.cycles)
        parts.append(("Explanation", "h"))
        parts.extend((line, "item") for line in d.explanation)
        parts.append(("Lock ownership", "h"))
        parts.extend((line, "item") for line in d.ownership)
        if d.waiting:
            parts.append(("Waiting processes", "h"))
            parts.extend((line, "item") for line in d.waiting)
        parts.append(("Recommendations", "h"))
        for r in s.recommendations():
            label = {CONFIRMED: "[Confirmed deadlock] ", RISK: "[Potential risk] ", GENERAL: ""}[r.category]
            parts.append((f"• {label}{r.text}", "item"))
        return parts

    def _fill_order(self) -> None:
        warnings = self.session.lock_order_warnings()
        parts: List[Tuple[str, str]] = [
            ("Potential risks from lock-order history", "h"),
            ("These warnings come from the order in which locks were taken in the past. They are NOT "
             "confirmed deadlocks; only a cycle in the Wait-For Graph proves a deadlock in the current state.",
             "muted"),
        ]
        if not warnings:
            parts.append(("No inconsistent lock ordering observed so far.", "good"))
        for w in warnings:
            parts.append((f"Locks {w.locks[0]} and {w.locks[1]}", "warn"))
            parts.append((w.message, "item"))
        self.order_text.show(parts)

    def _fill_recovery(self) -> None:
        log = self.session.recovery.log
        if not log:
            self.recovery_text.show([("Recovery", "h"),
                                     ("No recovery action has been performed. Use the controls above "
                                      "to abort a simulated process.", "muted")])
            return
        parts: List[Tuple[str, str]] = []
        for i, r in enumerate(log, 1):
            parts.append((f"Action {i}: abort {r.victim}", "h"))
            parts.append((f"Reason: {r.reason}", "item"))
            parts.append(("Deadlock resolved: yes" if r.resolved else "Deadlock still present after this action",
                          "good" if r.resolved else "bad"))
            parts.append(("Changes made", "h"))
            parts.extend((c, "item") for c in r.changes)
            parts.append(("State before", "h"))
            parts.extend((l, "item") for l in format_snapshot(r.before))
            parts.append(("State after", "h"))
            parts.extend((l, "item") for l in format_snapshot(r.after))
            parts.append(("Cycles before: " + (", ".join(format_cycle(c) for c in r.cycles_before) or "none"), "muted"))
            parts.append(("Cycles after: " + (", ".join(format_cycle(c) for c in r.cycles_after) or "none"), "muted"))
        self.recovery_text.show(parts)

    def _fill_recovery_controls(self) -> None:
        rm = self.session.recovery
        candidates = rm.candidates()
        self.victim_box.configure(values=candidates)
        if self.victim_var.get() not in candidates:
            self.victim_var.set(candidates[0] if candidates else "")
        choice = rm.suggest_victim()
        self.btn_auto.configure(state="normal" if choice else "disabled")
        self.btn_abort.configure(state="normal" if candidates else "disabled")
        self.suggest.configure(text=("Suggested: " + choice[1]) if choice else "No deadlock to recover from right now.")
