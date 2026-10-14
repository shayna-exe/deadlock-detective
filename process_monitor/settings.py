"""User-configurable monitoring and recommendation thresholds (with validation).

Every number the recommendation engine uses lives here, so the rules are
transparent: the GUI shows these values and the tests change them.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Mapping, Tuple, Union

#: Executable names (lower-case) that are never offered for management actions.
#: This is a *safety net*, not a complete list; unknown system processes are
#: additionally protected by the heuristics in ``protection.py``.
DEFAULT_PROTECTED_NAMES: Tuple[str, ...] = (
    # Windows
    "system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe",
    "services.exe", "lsass.exe", "winlogon.exe", "svchost.exe", "dwm.exe", "explorer.exe",
    "fontdrvhost.exe", "lsaiso.exe", "memory compression", "secure system", "sihost.exe",
    "taskhostw.exe", "ctfmon.exe", "searchindexer.exe", "msmpeng.exe", "wudfhost.exe",
    # Linux / BSD
    "init", "systemd", "kthreadd", "systemd-journald", "systemd-logind", "dbus-daemon",
    "xorg", "xwayland", "gnome-shell", "plasmashell", "sshd", "networkmanager",
    # macOS
    "launchd", "kernel_task", "windowserver", "loginwindow", "coreservicesd", "opendirectoryd",
)


class SettingsError(ValueError):
    """Raised when a settings value is out of range or has the wrong type."""


@dataclass
class MonitorSettings:
    # ---- sampling -------------------------------------------------------
    sample_interval_s: float = 2.0          # seconds between samples
    max_samples_per_process: int = 300      # bounded history per process
    max_system_samples: int = 600           # bounded system-wide history
    max_timeline_events: int = 200          # bounded recommendation timeline
    min_samples_for_analysis: int = 5       # fewer samples -> "Monitoring Unavailable"
    # ---- idle / low-activity rules -------------------------------------
    idle_cpu_percent: float = 1.0           # "low activity" = at or below this
    idle_min_seconds: float = 300.0         # low for this long -> potentially idle
    idle_min_memory_mb: float = 100.0       # ...and still holding at least this much RAM
    close_min_seconds: float = 600.0        # low for this long -> "Consider Closing" candidate
    close_min_memory_mb: float = 200.0
    # ---- high usage rules ----------------------------------------------
    high_cpu_percent: float = 60.0          # of total CPU capacity (normalised)
    high_cpu_min_seconds: float = 30.0
    lower_priority_cpu_percent: float = 85.0
    lower_priority_min_seconds: float = 60.0
    high_memory_percent: float = 10.0       # of physical RAM...
    high_memory_mb: float = 1500.0          # ...or this absolute amount
    # ---- investigate rule (memory growth) ------------------------------
    growth_min_samples: int = 10
    growth_min_mb: float = 200.0
    # ---- safety --------------------------------------------------------
    protected_names: List[str] = field(default_factory=lambda: list(DEFAULT_PROTECTED_NAMES))
    terminate_timeout_s: float = 3.0
    allow_force_kill: bool = True           # force kill still needs its own confirmation

    # ----------------------------------------------------------- validation
    _RANGES: ClassVar[Dict[str, Tuple[float, float]]] = {
        "sample_interval_s": (0.5, 60.0),
        "max_samples_per_process": (10, 5000),
        "max_system_samples": (10, 10000),
        "max_timeline_events": (10, 2000),
        "min_samples_for_analysis": (2, 1000),
        "idle_cpu_percent": (0.0, 20.0),
        "idle_min_seconds": (5.0, 86400.0),
        "idle_min_memory_mb": (0.0, 1e6),
        "close_min_seconds": (5.0, 86400.0),
        "close_min_memory_mb": (0.0, 1e6),
        "high_cpu_percent": (5.0, 100.0),
        "high_cpu_min_seconds": (2.0, 86400.0),
        "lower_priority_cpu_percent": (5.0, 100.0),
        "lower_priority_min_seconds": (2.0, 86400.0),
        "high_memory_percent": (0.5, 100.0),
        "high_memory_mb": (10.0, 1e7),
        "growth_min_samples": (3, 5000),
        "growth_min_mb": (1.0, 1e6),
        "terminate_timeout_s": (0.5, 60.0),
    }
    _INTS: ClassVar[frozenset] = frozenset({
        "max_samples_per_process", "max_system_samples", "max_timeline_events",
        "min_samples_for_analysis", "growth_min_samples"})

    def validate(self) -> "MonitorSettings":
        for name, (lo, hi) in self._RANGES.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SettingsError(f"{name} must be a number, got {value!r}.")
            if name in self._INTS and int(value) != value:
                raise SettingsError(f"{name} must be a whole number, got {value!r}.")
            if not (lo <= value <= hi):
                raise SettingsError(f"{name} must be between {lo:g} and {hi:g}, got {value:g}.")
        if self.close_min_seconds < self.idle_min_seconds:
            raise SettingsError("close_min_seconds must not be shorter than idle_min_seconds.")
        if self.lower_priority_cpu_percent < self.high_cpu_percent:
            raise SettingsError("lower_priority_cpu_percent must be at least high_cpu_percent.")
        if not isinstance(self.allow_force_kill, bool):
            raise SettingsError("allow_force_kill must be true or false.")
        if (not isinstance(self.protected_names, list)
                or not all(isinstance(n, str) and n.strip() for n in self.protected_names)):
            raise SettingsError("protected_names must be a list of non-empty names.")
        self.protected_names = sorted({n.strip().lower() for n in self.protected_names})
        for name in self._INTS:
            setattr(self, name, int(getattr(self, name)))
        return self

    # --------------------------------------------------------- (de)serialise
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MonitorSettings":
        if not isinstance(data, Mapping):
            raise SettingsError("Settings must be a JSON object.")
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise SettingsError("Unknown setting(s): " + ", ".join(unknown))
        return cls(**dict(data)).validate()

    def with_changes(self, **changes: Any) -> "MonitorSettings":
        merged = self.to_dict()
        merged.update(changes)
        return MonitorSettings.from_dict(merged)


def load_settings(path: Union[str, Path]) -> MonitorSettings:
    """Load settings; a missing file gives defaults, a broken file raises ``SettingsError``."""
    path = Path(path)
    if not path.exists():
        return MonitorSettings().validate()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SettingsError(f"Could not read settings file {path}: {exc}") from None
    return MonitorSettings.from_dict(data)


def save_settings(settings: MonitorSettings, path: Union[str, Path]) -> Path:
    path = Path(path)
    settings.validate()
    path.write_text(json.dumps(settings.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path
