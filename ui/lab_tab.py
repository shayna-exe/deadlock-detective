"""Recovery Laboratory and What-If Laboratory tabs.  Everything here is SIMULATION only."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, List, Optional, Tuple

from detector import format_cycle
from lab.whatif import build_scenario
from recovery import CRITERIA, RecoveryOption, check_prediction
from simulator import ScenarioError, SimulationError

from .widgets import AMBER, MUTED, ReadOnlyText

BANNER = "SIMULATION ONLY: these simulated processes and locks are not real programs. Nothing here touches your computer."


class RecoveryLabTab(ttk.Frame):
    def __init__(self, parent, session, family: str, on_change: Callable[[], None]) -> None:
        super().__init__(parent, padding=8)
        self.session, self.on_change = session, on_change
        self._options: List[RecoveryOption] = []
        ttk.Label(self, text=BANNER, foreground=AMBER).pack(anchor="w")
        ttk.Label(self, text="Compare the simulated recovery choices BEFORE applying one. Predictions are computed on a copy "
                             "of the state with the same code that performs the recovery.",
                  foreground=MUTED, wraplength=1100, justify="left").pack(anchor="w", pady=(0, 6))
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        cols = [("rank", "#", 30), ("victim", "Abort", 60), ("holds", "Holds", 70), ("cycle", "In cycle?", 70),
                ("resolves", "Resolves?", 80), ("blocked", "Blocked after", 90), ("sug", "Heuristic pick", 100)]
        self.tree = ttk.Treeview(left, columns=[c[0] for c in cols], show="headings", selectmode="browse", height=8)
        for key, title, width in cols:
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=width, anchor="w", stretch=False)
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.apply_btn = ttk.Button(left, text="Apply simulated recovery for the selected victim", command=self.apply)
        self.apply_btn.pack(fill="x", pady=(6, 4))
        self.criteria = ReadOnlyText(left, family, height=7, width=50)
        self.criteria.pack(fill="both", expand=True)
        self.criteria.show([("Ranking criteria (a heuristic, not proven optimal)", "h")] +
                           [(f"{i}. {c}", "item") for i, c in enumerate(CRITERIA, 1)])
        body.add(left, weight=2)
        self.detail = ReadOnlyText(body, family, height=18, width=60)
        body.add(self.detail, weight=3)
        self.refresh()

    def refresh(self) -> None:
        self._options = self.session.recovery_options()
        self.tree.delete(*self.tree.get_children())
        for o in self._options:
            self.tree.insert("", "end", iid=o.victim, values=(
                o.rank, o.victim, ", ".join(o.held_locks) or "-", "yes" if o.in_cycle else "no",
                "yes" if o.predicted_resolved else "no", o.blocked_after, "★ suggested" if o.suggested else ""))
        has_cycle = any(o.in_cycle for o in self._options)
        self.apply_btn.configure(state="normal" if self._options else "disabled")
        if not self._options:
            self.detail.show([("Nothing to compare", "h"), ("Every simulated process has already been aborted.", "muted")])
        elif not has_cycle:
            self.detail.show([("No deadlock right now", "h"),
                              ("Run the scenario and press Detect Deadlocks first. Options are still listed so "
                               "you can explore what aborting each process would do.", "muted")])

    def _selected(self, _e=None) -> None:
        sel = self.tree.selection()
        opt = next((o for o in self._options if sel and o.victim == sel[0]), None)
        if opt is None:
            return
        parts = [(f"Option {opt.rank}: abort {opt.victim}", "h")]
        parts += [(line, "item") for line in opt.summary_lines()]
        parts.append(("Predicted history entries", "h"))
        parts += [(m, "item") for m in opt.predicted_changes]
        self.detail.show(parts)

    def apply(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Deadlock Detective", "Select a victim in the table first.", parent=self)
            return
        option = next(o for o in self._options if o.victim == sel[0])
        before_graph, before_cycles = self.session.graph, self.session.detector_cycles()
        try:
            result = self.session.abort_process(option.victim)
        except SimulationError as exc:
            messagebox.showerror("Deadlock Detective", str(exc), parent=self)
            return
        check = check_prediction(option, result)
        cmp = self.session.compare_with(before_graph, before_cycles)
        parts = [(f"Applied: abort {result.victim} (simulated)", "h"),
                 ("Actual outcome: " + ("deadlock RESOLVED; no cycle remains." if result.resolved
                                        else "deadlock still present: " + ", ".join(format_cycle(c) for c in result.cycles_after)),
                  "good" if result.resolved else "bad"),
                 ("Prediction matched the actual result." if check.matched else
                  "Prediction differed: " + " ".join(check.differences), "good" if check.matched else "warn"),
                 ("Why the graph changed", "h")]
        parts += [(l, "item") for l in cmp.explanation]
        parts.append(("Changes", "h"))
        parts += [(c, "item") for c in result.changes]
        self.on_change()
        self.detail.show(parts)


class WhatIfTab(ttk.Frame):
    def __init__(self, parent, session, family: str, on_change: Callable[[], None],
                 on_scenario_added: Callable[[str], None]) -> None:
        super().__init__(parent, padding=8)
        self.session, self.on_change, self.on_scenario_added = session, on_change, on_scenario_added
        ttk.Label(self, text=BANNER, foreground=AMBER).pack(anchor="w")
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(6, 0))
        left = ttk.LabelFrame(body, text="Scenario editor", padding=8)
        self.name = tk.StringVar(value="My scenario")
        self.desc = tk.StringVar()
        self.procs = tk.StringVar(value="P1 P2")
        self.locks = tk.StringVar(value="A B")
        for label, var in (("Name", self.name), ("Description", self.desc), ("Processes (space or comma separated)", self.procs),
                           ("Locks", self.locks)):
            ttk.Label(left, text=label).pack(anchor="w")
            ttk.Entry(left, textvariable=var, width=46).pack(fill="x", pady=(0, 4))
        ttk.Label(left, text="Events, one per line: PROCESS OPERATION LOCK  (ACQUIRE, REQUEST, RELEASE; # starts a comment)").pack(anchor="w")
        self.events = tk.Text(left, height=9, width=46, font=("Courier", 10))
        self.events.insert("1.0", "P1 ACQUIRE A\nP2 ACQUIRE B\nP1 REQUEST B\nP2 REQUEST A\n")
        self.events.pack(fill="both", expand=True, pady=(0, 4))
        row = ttk.Frame(left)
        row.pack(fill="x")
        ttk.Button(row, text="Validate", command=lambda: self.build(False)).pack(side="left")
        ttk.Button(row, text="Create and load", command=lambda: self.build(True)).pack(side="left", padx=6)
        self.editor_msg = ttk.Label(left, text="", wraplength=380, justify="left")
        self.editor_msg.pack(fill="x", pady=(4, 0))
        body.add(left, weight=2)

        right = ttk.LabelFrame(body, text="Release a simulated lock (what-if)", padding=8)
        ttk.Label(right, text="Make a simulated process release a lock it holds, outside the scripted events. "
                              "Reset restores the scenario.", foreground=MUTED, wraplength=420, justify="left").pack(anchor="w")
        row2 = ttk.Frame(right)
        row2.pack(fill="x", pady=6)
        self.rel_proc, self.rel_lock = tk.StringVar(), tk.StringVar()
        self.proc_box = ttk.Combobox(row2, textvariable=self.rel_proc, state="readonly", width=8)
        self.lock_box = ttk.Combobox(row2, textvariable=self.rel_lock, state="readonly", width=8)
        ttk.Label(row2, text="Process").pack(side="left")
        self.proc_box.pack(side="left", padx=4)
        ttk.Label(row2, text="Lock").pack(side="left")
        self.lock_box.pack(side="left", padx=4)
        ttk.Button(row2, text="Release (simulated)", command=self.release).pack(side="left", padx=6)
        self.out = ReadOnlyText(right, family, height=16, width=50)
        self.out.pack(fill="both", expand=True)
        body.add(right, weight=3)
        self.refresh()

    def refresh(self) -> None:
        st = self.session.state
        self.proc_box.configure(values=st.processes)
        self.lock_box.configure(values=st.locks)
        if self.rel_proc.get() not in st.processes:
            self.rel_proc.set(st.processes[0] if st.processes else "")
        if self.rel_lock.get() not in st.locks:
            self.rel_lock.set(st.locks[0] if st.locks else "")

    def build(self, load: bool) -> None:
        try:
            sc = build_scenario(self.name.get(), self.desc.get(), self.procs.get(), self.locks.get(),
                                self.events.get("1.0", "end"))
            if load:
                replace = sc.name in self.session.user_scenarios
                if replace and not messagebox.askyesno("Replace?", f"Replace your scenario '{sc.name}'?", parent=self):
                    return
                self.session.add_scenario(sc, replace_own=replace)
        except (ScenarioError, SimulationError) as exc:
            self.editor_msg.configure(text=f"Not accepted: {exc}", foreground="#b42318")
            return
        self.editor_msg.configure(text=("Scenario created and loaded." if load else
                                        f"Valid: {len(sc.events)} events replay without errors."), foreground="#1b7a3d")
        if load:
            self.on_scenario_added(sc.name)

    def release(self) -> None:
        graph, cycles = self.session.graph, self.session.detector_cycles()
        try:
            self.session.manual_release(self.rel_proc.get(), self.rel_lock.get())
        except SimulationError as exc:
            messagebox.showerror("Deadlock Detective", f"Not allowed in the simulation:\n{exc}", parent=self)
            return
        cmp = self.session.compare_with(graph, cycles)
        self.out.show([(f"Simulated: {self.rel_proc.get()} released {self.rel_lock.get()}", "h"),
                       ("Wait-For Graph before vs after", "h")] + [(l, "item") for l in cmp.explanation] +
                      [("Press Detect Deadlocks to refresh the highlighted graph.", "muted")])
        self.on_change()
