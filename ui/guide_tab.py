"""OS concept guide tab."""
from __future__ import annotations

from tkinter import ttk

from .guide_content import GUIDE
from .widgets import ReadOnlyText


class GuideTab(ttk.Frame):
    def __init__(self, parent, family: str) -> None:
        super().__init__(parent, padding=8)
        text = ReadOnlyText(self, family, height=30, width=110)
        text.pack(fill="both", expand=True)
        parts = [("Operating Systems concepts and where they appear in Deadlock Detective", "h")]
        for title, meaning, where in GUIDE:
            parts += [(title, "h"), (meaning, "item"), ("In this program: " + where, "muted")]
        text.show(parts)
