"""Incident History and Reports tab."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional

from incidents import Incident, ReportError

from .widgets import AMBER, MUTED, ReadOnlyText

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


class ReportsTab(ttk.Frame):
    def __init__(self, parent, services, family: str) -> None:
        super().__init__(parent, padding=8)
        self.services = services
        self._incidents: List[Incident] = []
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Button(top, text="Export incident report (JSON)", command=self.export_json).pack(side="left")
        ttk.Button(top, text="Export process snapshot (CSV)", command=self.export_csv).pack(side="left", padx=6)
        self.msg = ttk.Label(top, text="", foreground=MUTED)
        self.msg.pack(side="left", padx=8)
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(6, 0))
        left = ttk.Frame(body)
        cols = [("id", "Incident", 190), ("scenario", "Scenario", 140), ("status", "Status", 150)]
        self.tree = ttk.Treeview(left, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for key, title, width in cols:
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        body.add(left, weight=2)
        self.detail = ReadOnlyText(body, family, height=20, width=70)
        body.add(self.detail, weight=3)
        self.refresh()

    def refresh(self) -> None:
        sel = self.tree.selection()
        keep = sel[0] if sel else None
        self._incidents = list(self.services.incidents.incidents)
        self.tree.delete(*self.tree.get_children())
        for inc in reversed(self._incidents):
            self.tree.insert("", "end", iid=inc.id, values=(inc.id, inc.scenario_name, inc.status))
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
        elif not self._incidents:
            self.detail.show([("No incidents yet", "h"),
                              ("An incident is created automatically when the simulator detects a deadlock. "
                               "You can still export a report at any time.", "muted")])

    def _selected(self, _e=None) -> None:
        sel = self.tree.selection()
        inc = next((i for i in self._incidents if sel and i.id == sel[0]), None)
        if inc is None:
            return
        tele = inc.telemetry
        parts = [(f"{inc.id}: {inc.status}", "h"), (f"Scenario: {inc.scenario_name}   Opened: {inc.created_at}", "item"),
                 ("Timeline", "h")]
        parts += [(f"{t.at}  [{t.source}]  {t.kind}: {t.text}", "item") for t in inc.timeline]
        parts.append(("Simulation evidence (SIMULATED processes)", "h"))
        parts += [(" ; ".join(inc.diagnosis.get("explanation", [])[:2]) or inc.diagnosis.get("headline", ""), "item")]
        parts.append(("Real-process telemetry (context only, NOT evidence about the simulated deadlock)", "h"))
        if tele.get("available"):
            parts.append((f"Captured {tele['captured_at']}; top CPU: " + ", ".join(
                f"{p['name']} ({p['cpu_percent']}%)" for p in tele["top_cpu_consumers"][:3]), "item"))
            parts.append(("Top memory: " + ", ".join(f"{p['name']} ({p['rss_mb']} MB)" for p in tele["top_memory_consumers"][:3]), "item"))
            parts.append((f"{len(tele['recommendations'])} resource recommendation(s) recorded with their evidence.", "item"))
        else:
            parts.append(("Unavailable: " + tele.get("reason", ""), "warn"))
        if inc.verification:
            parts.append(("Final verification", "h"))
            parts.append(("Deadlock resolved." if inc.verification["deadlock_resolved"] else "Deadlock NOT resolved.",
                          "good" if inc.verification["deadlock_resolved"] else "bad"))
        self.detail.show(parts)

    def export_json(self) -> None:
        sc = self.services.session.scenario.name.lower().replace(" ", "_").replace("-", "_")
        path = filedialog.asksaveasfilename(
            parent=self, title="Save incident report", defaultextension=".json",
            initialdir=str(REPORTS_DIR if REPORTS_DIR.is_dir() else Path.home()), initialfile=f"{sc}_incident_report.json",
            filetypes=[("JSON files", "*.json")])
        if not path:
            return
        try:
            # The save dialog already asked about overwriting, so overwrite is intentional here.
            saved = self.services.export_report(path, overwrite=True)
        except (OSError, ReportError) as exc:
            messagebox.showerror("Deadlock Detective", f"The report could not be written:\n{exc}", parent=self)
            return
        self.msg.configure(text=f"Saved {saved.name}")
        messagebox.showinfo("Deadlock Detective", f"Report saved to:\n{saved}", parent=self)

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, title="Save process snapshot", defaultextension=".csv",
                                            initialdir=str(REPORTS_DIR if REPORTS_DIR.is_dir() else Path.home()),
                                            initialfile="process_snapshot.csv", filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            saved = self.services.export_snapshot_csv(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Deadlock Detective", str(exc), parent=self)
            return
        self.msg.configure(text=f"Saved {saved.name}")
