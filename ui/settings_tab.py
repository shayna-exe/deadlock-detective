"""Settings and Safety tab: transparent thresholds with validation, protected list and safety notes."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict

from process_monitor import MonitorSettings, SettingsError

from .widgets import MUTED, Tooltip

FIELDS = [
    ("Sampling", [
        ("sample_interval_s", "Sample interval (s)", "How often the monitor measures every process."),
        ("max_samples_per_process", "Samples kept per process", "Retention limit; older samples are dropped."),
        ("min_samples_for_analysis", "Samples needed before analysis", "Fewer samples gives 'Monitoring Unavailable'."),
    ]),
    ("Idle rules", [
        ("idle_cpu_percent", "Low-activity CPU % (at or below)", "CPU use at or below this counts as low activity."),
        ("idle_min_seconds", "Potentially idle after (s)", "How long activity must stay low."),
        ("idle_min_memory_mb", "...and holding at least (MB)", "Idle processes below this memory are ignored."),
        ("close_min_seconds", "Consider closing after (s)", "Longer window needed before closing is suggested."),
        ("close_min_memory_mb", "...and holding at least (MB) ", "Memory needed for a 'Consider Closing' suggestion."),
    ]),
    ("High usage rules", [
        ("high_cpu_percent", "High CPU % (of all cores)", "Sustained CPU at or above this is flagged."),
        ("high_cpu_min_seconds", "High CPU for (s)", "How long it must be sustained."),
        ("lower_priority_cpu_percent", "Lower-priority CPU %", "Stronger threshold for suggesting a lower priority."),
        ("lower_priority_min_seconds", "Lower-priority for (s)", "Duration for that suggestion."),
        ("high_memory_percent", "High memory (% of RAM)", "Percentage rule."),
        ("high_memory_mb", "High memory (MB)", "Absolute rule."),
        ("growth_min_samples", "Memory-growth readings", "Readings examined for the Investigate rule."),
        ("growth_min_mb", "Memory growth (MB)", "Growth that triggers Investigate."),
    ]),
    ("Safety", [
        ("terminate_timeout_s", "Termination wait (s)", "How long to wait for a process to exit."),
    ]),
]


class SettingsTab(ttk.Frame):
    def __init__(self, parent, services, family: str) -> None:
        super().__init__(parent, padding=8)
        self.services = services
        self.vars: Dict[str, tk.StringVar] = {}
        cols = ttk.Frame(self)
        cols.pack(fill="both", expand=True)
        left = ttk.Frame(cols)
        left.pack(side="left", fill="y", padx=(0, 20))
        for group, items in FIELDS:
            box = ttk.LabelFrame(left, text=group, padding=6)
            box.pack(fill="x", pady=(0, 6))
            for i, (key, label, tip) in enumerate(items):
                lab = ttk.Label(box, text=label)
                lab.grid(row=i, column=0, sticky="w", padx=(0, 8), pady=1)
                Tooltip(lab, tip)
                var = tk.StringVar()
                ttk.Entry(box, textvariable=var, width=10).grid(row=i, column=1, pady=1)
                self.vars[key] = var
        self.force = tk.BooleanVar()
        ttk.Checkbutton(left, text="Allow the 'Force kill' operation (Linux/macOS; still needs confirmation)",
                        variable=self.force).pack(anchor="w")
        row = ttk.Frame(left)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="Apply", command=lambda: self.apply(False)).pack(side="left")
        ttk.Button(row, text="Apply and save", command=lambda: self.apply(True)).pack(side="left", padx=6)
        ttk.Button(row, text="Reset to defaults", command=self.reset).pack(side="left")
        self.msg = ttk.Label(left, text=services.settings_warning or "", foreground="#b42318", wraplength=420)
        self.msg.pack(anchor="w")

        right = ttk.Frame(cols)
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Protected processes (one name per line)", font=(family, 10, "bold")).pack(anchor="w")
        ttk.Label(right, text="These are never offered for terminate, suspend or priority changes. Deadlock Detective "
                              "and its launching terminal are always protected, as is anything whose name cannot be read "
                              "or that lives in an operating-system folder.", foreground=MUTED, wraplength=460,
                  justify="left").pack(anchor="w")
        self.protected = tk.Text(right, height=16, width=34)
        self.protected.pack(fill="both", expand=True, pady=4)
        ttk.Label(right, text=("Safety rules: nothing runs automatically; every real operation needs your explicit "
                               "confirmation; the process identity is re-checked right before acting; simulated recovery "
                               "never touches real programs."), foreground=MUTED, wraplength=460, justify="left").pack(anchor="w")
        self.load(services.settings)

    def load(self, st: MonitorSettings) -> None:
        for key, var in self.vars.items():
            var.set(f"{getattr(st, key):g}")
        self.force.set(st.allow_force_kill)
        self.protected.delete("1.0", "end")
        self.protected.insert("1.0", "\n".join(st.protected_names))

    def apply(self, save: bool) -> None:
        try:
            data = self.services.settings.to_dict()
            for key, var in self.vars.items():
                data[key] = float(var.get())
            data["allow_force_kill"] = bool(self.force.get())
            data["protected_names"] = [l for l in self.protected.get("1.0", "end").splitlines() if l.strip()]
            new = MonitorSettings.from_dict(data)
            self.services.apply_settings(new, save=save)
        except (ValueError, SettingsError, OSError) as exc:
            self.msg.configure(text=f"Not applied: {exc}", foreground="#b42318")
            return
        self.msg.configure(text="Settings applied" + (" and saved." if save else "."), foreground="#1b7a3d")
        self.load(self.services.settings)

    def reset(self) -> None:
        if messagebox.askyesno("Reset", "Restore the default thresholds and protected list?", parent=self):
            self.load(MonitorSettings().validate())
