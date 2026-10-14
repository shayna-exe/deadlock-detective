"""Smart Recommendations tab: processes that deserve attention, each with an explainable card."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional

from process_monitor import MonitorSnapshot
from process_monitor.recommendations import CATEGORIES, CATEGORY_HELP, KEEP, PROTECTED, UNAVAILABLE, ProcessAssessment

from .process_card import ProcessCard
from .viewmodels import BADGES, badge_text, fmt_ram
from .widgets import MUTED, ReadOnlyText

ATTENTION_ORDER = ("Consider Closing", "Consider Lowering Priority", "Investigate", "High CPU Usage",
                   "Potentially Idle Resource Consumer", "High Memory Usage")


class RecommendationsTab(ttk.Frame):
    def __init__(self, parent, services, family: str) -> None:
        super().__init__(parent, padding=8)
        self.services = services
        self._by_iid: Dict[str, ProcessAssessment] = {}
        ttk.Label(self, text=("Recommendations are ADVICE based on measurements and transparent rules, not machine "
                              "learning and not proof. Nothing is ever closed, suspended or changed automatically."),
                  foreground=MUTED, wraplength=1100, justify="left").pack(anchor="w")
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(6, 0))
        left = ttk.Frame(body)
        self.summary = ttk.Label(left, text="Start monitoring on the Live Processes tab to get recommendations.",
                                 foreground=MUTED, wraplength=520, justify="left")
        self.summary.pack(fill="x")
        cols = [("name", "Process", 150), ("pid", "PID", 55), ("rec", "Recommendation", 220),
                ("strength", "Evidence", 70), ("ram", "RAM", 70)]
        self.tree = ttk.Treeview(left, columns=[c[0] for c in cols], show="headings", selectmode="browse", height=12)
        for key, title, width in cols:
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=width, anchor="w", stretch=key == "rec")
        self.tree.pack(fill="both", expand=True, pady=(4, 6))
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        legend = ttk.LabelFrame(left, text="What the categories mean", padding=4)
        legend.pack(fill="x")
        text = ReadOnlyText(legend, family, height=8, width=40)
        text.pack(fill="x")
        text.show([(f"{badge_text(c)}: {CATEGORY_HELP[c]}", "item") for c in CATEGORIES])
        body.add(left, weight=2)
        self.card = ProcessCard(body, services, family)
        body.add(self.card, weight=3)

    def update(self, snap: Optional[MonitorSnapshot]) -> None:
        selected = self.tree.selection()
        keep = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        self._by_iid = {}
        if snap is None:
            self.card.show(None)
            return
        rank = {c: i for i, c in enumerate(ATTENTION_ORDER)}
        items = sorted((a for a in snap.assessments if a.category in rank),
                       key=lambda a: (rank[a.category], -(a.sample.rss_bytes or 0)))
        for a in items:
            iid = f"{a.sample.pid}:{a.sample.create_time}"
            self._by_iid[iid] = a
            self.tree.insert("", "end", iid=iid, values=(a.name, a.pid, badge_text(a.category), a.strength,
                                                         fmt_ram(a)))
        unavailable = sum(1 for a in snap.assessments if a.category == UNAVAILABLE)
        protected = sum(1 for a in snap.assessments if a.category == PROTECTED)
        self.summary.configure(text=(
            f"{len(items)} process(es) may deserve a look. {protected} protected and {unavailable} not yet "
            f"analysable (too few samples or access denied) are excluded." if items else
            f"No process currently matches a recommendation rule. {protected} protected and {unavailable} not yet "
            "analysable processes are excluded. Rules need several minutes of samples to say anything about idleness."))
        if keep in self._by_iid:
            self.tree.selection_set(keep)
            self.card.show(self._by_iid[keep])
        else:
            self.card.show(None)

    def _selected(self, _event=None) -> None:
        sel = self.tree.selection()
        self.card.show(self._by_iid.get(sel[0]) if sel else None)
