"""Reusable Tkinter widgets and the colour theme shared by every tab."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List, Optional, Sequence, Tuple

from .viewmodels import nice_max, scale_series

BG = "#f4f5f7"
TEXT = "#1f2933"
MUTED = "#52606d"
ACCENT = "#2b5c8a"
RED = "#b42318"
GREEN = "#1b7a3d"
AMBER = "#8a5a00"
CARD = "#ffffff"
BORDER = "#cbd2d9"


class Tooltip:
    """Small hover explanation for unfamiliar OS terms."""

    def __init__(self, widget, text: str) -> None:
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None) -> None:
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", wraplength=320, background="#fffbe6",
                 foreground=TEXT, relief="solid", borderwidth=1, padx=6, pady=4).pack()

    def _hide(self, _event=None) -> None:
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class ReadOnlyText(ttk.Frame):
    """Scrollable, read-only text area with a few styling tags."""

    def __init__(self, parent, font_family: str, height: int = 10, width: int = 48) -> None:
        super().__init__(parent)
        self.text = tk.Text(self, wrap="word", height=height, width=width, relief="flat", padx=8, pady=6,
                            background=CARD, foreground=TEXT, font=(font_family, 10),
                            highlightthickness=1, highlightbackground=BORDER)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set, state="disabled")
        self.text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.text.tag_configure("h", font=(font_family, 11, "bold"), spacing1=8, spacing3=2)
        self.text.tag_configure("bad", foreground=RED, font=(font_family, 10, "bold"))
        self.text.tag_configure("good", foreground=GREEN, font=(font_family, 10, "bold"))
        self.text.tag_configure("warn", foreground=AMBER, font=(font_family, 10, "bold"))
        self.text.tag_configure("muted", foreground=MUTED)
        self.text.tag_configure("item", lmargin1=12, lmargin2=24)

    def show(self, parts: List[Tuple[str, str]]) -> None:
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        for content, tag in parts:
            t.insert("end", content + "\n", tag or ())
        t.configure(state="disabled")


class LineChart(ttk.Frame):
    """Lightweight native line chart (no plotting dependency).

    ``set_data`` takes real samples only; ``None`` values draw as gaps.
    """

    PAD = (46.0, 22.0, 12.0, 22.0)
    PALETTE = ("#2b5c8a", "#b42318", "#1b7a3d", "#7c3aed")

    def __init__(self, parent, title: str, unit: str = "%", font_family: str = "TkDefaultFont",
                 fixed_max: Optional[float] = None, height: int = 150) -> None:
        super().__init__(parent)
        self.title, self.unit, self.fixed_max = title, unit, fixed_max
        self._font = (font_family, 9)
        self._series: List[Tuple[str, Sequence[Optional[float]]]] = []
        self.canvas = tk.Canvas(self, background=CARD, height=height, highlightthickness=1,
                                highlightbackground=BORDER)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._draw())

    def set_data(self, series: Sequence[Tuple[str, Sequence[Optional[float]]]]) -> None:
        self._series = [(label, list(values)) for label, values in series]
        self._draw()

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 100)
        c.create_text(8, 4, anchor="nw", text=self.title, font=(self._font[0], 9, "bold"), fill=TEXT)
        values = [v for _, vals in self._series for v in vals if v is not None]
        if not values:
            c.create_text(w / 2, h / 2, text="No samples yet.", fill=MUTED, font=self._font)
            return
        y_max = self.fixed_max or nice_max(max(values))
        left, top, right, bottom = self.PAD
        for frac in (0.0, 0.5, 1.0):
            y = top + (h - top - bottom) * (1 - frac)
            c.create_line(left, y, w - right, y, fill="#e4e7eb")
            c.create_text(left - 4, y, anchor="e", text=f"{y_max * frac:g}{self.unit}", font=self._font, fill=MUTED)
        x = left
        for i, (label, vals) in enumerate(self._series):
            color = self.PALETTE[i % len(self.PALETTE)]
            run: List[float] = []
            for p in scale_series(vals, w, h, self.PAD, y_max) + [None]:
                if p is None:
                    if len(run) >= 4:
                        c.create_line(*run, fill=color, width=2)
                    run = []
                else:
                    run.extend(p)
            c.create_line(x, h - 8, x + 16, h - 8, fill=color, width=3)
            t = c.create_text(x + 20, h - 8, anchor="w", text=label, font=self._font, fill=TEXT)
            x = c.bbox(t)[2] + 14
