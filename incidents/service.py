"""Builds incidents from simulator events and attaches optional telemetry snapshots.

The service only OBSERVES the simulation session (through its listener hook).
It never changes the simulation and never touches real processes.  The real
process snapshot is context: it is stored in its own field and labelled so it
cannot be mistaken for evidence about the simulated deadlock.
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from detector.cycle_detector import format_cycle
from process_monitor.exporters import unavailable_telemetry
from process_monitor.models import iso_now
from simulator import graph_to_dict

from .models import (SRC_REAL_ACTION, SRC_SIMULATION, SRC_TELEMETRY, SRC_USER, STATUS_ABANDONED,
                     STATUS_OPEN, STATUS_RESOLVED, STATUS_UNRESOLVED, Incident, TimelineEntry)

TelemetryProvider = Callable[[], Optional[Any]]      # returns a MonitorSnapshot or None
ActionLogProvider = Callable[[], List[Dict[str, Any]]]


class IncidentService:
    def __init__(self, session, telemetry_provider: Optional[TelemetryProvider] = None,
                 action_log_provider: Optional[ActionLogProvider] = None, max_incidents: int = 50) -> None:
        self.session = session
        self._telemetry = telemetry_provider
        self._actions = action_log_provider
        self._max = max_incidents
        self._counter = itertools.count(1)
        self.incidents: List[Incident] = []
        self.current: Optional[Incident] = None
        self._awaiting_verification = False
        self._busy = False
        session.add_listener(self._on_event)

    # ------------------------------------------------------------- observers
    def _on_event(self, kind: str, payload: Any) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            if kind == "detected":
                self._on_detected(payload)
            elif kind == "recovered":
                self._on_recovered(payload)
            elif kind == "reset":
                self._on_reset()
        finally:
            self._busy = False

    def _on_reset(self) -> None:
        if self.current is not None and self.current.status == STATUS_OPEN:
            self._close(STATUS_ABANDONED)
        self.current = None
        self._awaiting_verification = False

    def _on_detected(self, detection) -> None:
        if self._awaiting_verification and self.current is not None:
            self._verify(detection)
            return
        if detection.deadlock and self.current is None:
            self._open_incident(detection)

    # --------------------------------------------------------------- opening
    def _telemetry_block(self) -> Dict[str, Any]:
        if self._telemetry is None:
            return unavailable_telemetry("Live process monitoring is not configured.")
        try:
            snap = self._telemetry()
        except Exception as exc:  # telemetry problems must never block deadlock analysis
            return unavailable_telemetry(f"Telemetry collection failed: {type(exc).__name__}: {exc}")
        if snap is None:
            return unavailable_telemetry("Live monitoring is not running or has produced no samples yet.")
        return snap.telemetry_dict()

    def _open_incident(self, detection) -> None:
        s = self.session
        now = iso_now()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        diagnosis = s.diagnose()
        recs = [r.to_dict() for r in s.recommendations()]
        options = [o.to_dict() for o in s.recovery_options()]
        telemetry = self._telemetry_block()
        inc = Incident(
            id=f"INC-{stamp}-{next(self._counter):03d}", created_at=now,
            scenario_name=s.scenario.name, scenario_description=s.scenario.description,
            cycles=[list(c) for c in detection.cycles], state_at_detection=s.state.snapshot(),
            graph=graph_to_dict(s.graph), diagnosis=diagnosis.to_dict(), recommendations=recs,
            recovery_options=options, telemetry=telemetry)
        cyc = "; ".join(format_cycle(c) for c in detection.cycles)
        inc.timeline.append(TimelineEntry(now, "DETECTED", SRC_SIMULATION, f"Deadlock detected in the simulation: {cyc}."))
        inc.timeline.append(TimelineEntry(now, "DIAGNOSED", SRC_SIMULATION, diagnosis.headline))
        inc.timeline.append(TimelineEntry(now, "RECOMMENDED", SRC_SIMULATION,
                                          f"{len(options)} simulated recovery option(s) compared; "
                                          f"{len(recs)} recommendation(s) generated."))
        if telemetry.get("available"):
            n = telemetry.get("process_count", 0)
            inc.timeline.append(TimelineEntry(now, "TELEMETRY", SRC_TELEMETRY,
                                              f"Snapshot of {n} real processes captured as context (not evidence about the simulated deadlock)."))
        else:
            inc.timeline.append(TimelineEntry(now, "TELEMETRY", SRC_TELEMETRY,
                                              "Resource telemetry unavailable: " + telemetry.get("reason", "unknown reason")))
        self.current = inc
        self.incidents.append(inc)
        del self.incidents[:-self._max]          # bounded history

    # -------------------------------------------------------------- recovery
    def _on_recovered(self, result) -> None:
        inc = self.current
        if inc is None:
            return
        now = iso_now()
        inc.timeline.append(TimelineEntry(now, "DECISION", SRC_USER,
                                          f"Simulated recovery chosen: abort {result.victim} ({result.reason})."))
        inc.timeline.append(TimelineEntry(now, "RECOVERY", SRC_SIMULATION, "; ".join(result.changes)))
        inc.recoveries.append(result.to_dict())
        inc.state_after = result.after
        self._awaiting_verification = True

    def _verify(self, detection) -> None:
        inc = self.current
        if inc is None:
            return
        now = iso_now()
        self._awaiting_verification = False
        resolved = not detection.deadlock
        remaining = "; ".join(format_cycle(c) for c in detection.cycles)
        inc.verification = {
            "verified_at": now, "method": "Wait-For Graph cycle detection re-run after recovery",
            "deadlock_resolved": resolved,
            "cycles_remaining": [list(c) for c in detection.cycles],
        }
        inc.timeline.append(TimelineEntry(
            now, "VERIFIED", SRC_SIMULATION,
            "Verification: no cycle remains; the simulated deadlock is resolved." if resolved
            else f"Verification: the deadlock is NOT resolved; remaining cycle(s): {remaining}."))
        if resolved:
            self._close(STATUS_RESOLVED)
            self.current = None
        else:
            inc.status = STATUS_UNRESOLVED     # stays current so another recovery can be applied

    def _close(self, status: str) -> None:
        if self.current is not None:
            self.current.status = status
            self.current.closed_at = iso_now()

    # ------------------------------------------------------------ user hooks
    def note(self, kind: str, source: str, text: str) -> None:
        """Add a timeline entry to the open incident (e.g. a user decision)."""
        if self.current is not None:
            self.current.timeline.append(TimelineEntry(iso_now(), kind, source, text))

    def note_real_action(self, record) -> None:
        """Record a user-approved REAL process action next to the incident (unrelated to the simulation)."""
        target = self.current or (self.incidents[-1] if self.incidents else None)
        if target is not None:
            target.timeline.append(TimelineEntry(
                iso_now(), "REAL ACTION", SRC_REAL_ACTION,
                f"{record.operation} on real process {record.name} (PID {record.pid}): {record.outcome}. "
                "This does not affect the simulation."))

    # --------------------------------------------------------------- queries
    def latest(self) -> Optional[Incident]:
        return self.current or (self.incidents[-1] if self.incidents else None)

    def actions_since(self, incident: Optional[Incident]) -> List[Dict[str, Any]]:
        if self._actions is None:
            return []
        records = self._actions()
        if incident is None:
            return records
        return [r for r in records if r["at"] >= incident.created_at]
