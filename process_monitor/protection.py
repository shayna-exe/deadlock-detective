"""Decide whether a real process must be protected from management actions.

The rule is *fail safe*: if a process cannot be identified or looks like part of
the operating system, it is protected.  Protection is checked twice: when a
recommendation is generated and again right before any action is executed.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Iterable, Optional, Set

from .models import ProcessSample
from .settings import MonitorSettings

#: Path fragments (lower-case, '/' separators) that identify operating-system binaries.
_SYSTEM_PATH_PARTS = (
    "/windows/system32/", "/windows/syswow64/", "/windows/winsxs/",
    "/usr/sbin/", "/sbin/", "/usr/lib/systemd/", "/lib/systemd/", "/usr/libexec/",
    "/system/library/", "/usr/lib/polkit",
)


@dataclass(frozen=True)
class Protection:
    protected: bool
    reason: str = ""


def default_own_pids() -> Set[int]:
    """This program and the process that launched it (usually the terminal)."""
    pids = {os.getpid()}
    try:
        pids.add(os.getppid())
    except OSError:  # pragma: no cover
        pass
    return {p for p in pids if p and p > 0}


def _norm_path(path: Optional[str]) -> str:
    return (path or "").replace("\\", "/").lower()


def classify_protection(sample: ProcessSample, settings: MonitorSettings,
                        own_pids: Optional[Iterable[int]] = None) -> Protection:
    own = set(own_pids) if own_pids is not None else default_own_pids()
    name = (sample.name or "").strip().lower()
    if sample.pid in own:
        return Protection(True, "This is Deadlock Detective itself or the terminal that started it.")
    if "name" in sample.missing or not name or name.startswith("<pid"):
        return Protection(True, "The process name could not be read, so its safety cannot be established.")
    if sample.pid <= 4 or (sys.platform != "win32" and sample.pid == 1):
        return Protection(True, "Reserved system process ID.")
    if name in {n.lower() for n in settings.protected_names}:
        return Protection(True, f"'{sample.name}' is on the protected-process list (critical operating-system component).")
    if sample.ppid == 2 and sys.platform.startswith("linux"):
        return Protection(True, "Linux kernel thread.")
    path = _norm_path(sample.exe)
    if any(part in path for part in _SYSTEM_PATH_PARTS):
        return Protection(True, "The executable lives in an operating-system folder.")
    return Protection(False)
