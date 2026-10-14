"""Explainable recommendation card + guarded real-process action buttons."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Dict, Optional

from process_monitor.actions import (FORCE_KILL, LABELS, LOWER_PRIORITY, OK, OPERATIONS, RESUME, SUSPEND,
                                     TERMINATE, UNVERIFIED)
from process_monitor.recommendations import ProcessAssessment

from .viewmodels import card_parts
from .widgets import MUTED, ReadOnlyText, Tooltip

OP_HELP = {
    TERMINATE: "Asks the operating system to end the program. On Windows this is immediate.",
    FORCE_KILL: "Only offered after a termination request timed out (Linux/macOS).",
    LOWER_PRIORITY: "Priority is how the scheduler ranks processes for CPU time; lower means it yields to others.",
    SUSPEND: "Freezes the program until you resume it. Its window will stop responding.",
    RESUME: "Lets a program that was suspended continue.",
}


class ProcessCard(ttk.Frame):
    def __init__(self, parent, services, family: str, on_action_done: Optional[Callable[[], None]] = None) -> None:
        super().__init__(parent)
        self.services, self.on_action_done = services, on_action_done
        self.assessment: Optional[ProcessAssessment] = None
        self.info = ReadOnlyText(self, family, height=12)
        self.info.pack(fill="both", expand=True)
        box = ttk.LabelFrame(self, text="Operations on this REAL process (each needs your confirmation)", padding=6)
        box.pack(fill="x", pady=(6, 0))
        self.buttons: Dict[str, ttk.Button] = {}
        for op in OPERATIONS:
            b = ttk.Button(box, text=LABELS[op], command=lambda o=op: self._run(o))
            b.pack(side="left", padx=(0, 4))
            Tooltip(b, OP_HELP[op])
            self.buttons[op] = b
        self.note = ttk.Label(box, text="", foreground=MUTED, wraplength=360, justify="left")
        self.note.pack(side="left", padx=6)
        self.show(None)

    def show(self, assessment: Optional[ProcessAssessment]) -> None:
        self.assessment = assessment
        self.info.show(card_parts(assessment))
        ctl = self.services.controller
        reasons = []
        for op, b in self.buttons.items():
            if assessment is None or ctl is None:
                b.configure(state="disabled")
                continue
            av = ctl.availability(assessment.sample)[op]
            b.configure(state="normal" if av.available else "disabled")
            if not av.available and av.reason and op == TERMINATE:
                reasons.append(av.reason)
        self.note.configure(text=(reasons[0] if reasons else
                                  ("Process management unavailable." if ctl is None else
                                   "Nothing runs automatically; recommendations are only advice.")))

    def _run(self, op: str) -> None:
        a, ctl = self.assessment, self.services.controller
        if a is None or ctl is None:
            return
        sample = a.sample
        text = ctl.describe(sample, op)
        if not messagebox.askokcancel("Confirm real process operation", text, icon="warning", parent=self):
            return
        if op in (TERMINATE, FORCE_KILL) and not messagebox.askyesno(
                "Are you sure?", f"{LABELS[op]} {sample.name} (PID {sample.pid}) now?\n\n"
                                  "Unsaved work in that program may be lost.", default="no", icon="warning", parent=self):
            return
        record = self.services.execute_action(sample, op, True)
        icon = "info" if record.outcome == OK else "warning"
        messagebox.showinfo("Result" if record.outcome == OK else "Not completed",
                            f"{LABELS[op]} on {record.name} (PID {record.pid}): {record.outcome}.\n\n{record.detail}"
                            + ("\n\nThe outcome could not be verified." if record.outcome == UNVERIFIED else ""),
                            icon=icon, parent=self)
        if self.on_action_done:
            self.on_action_done()
