"""Full incident report (schema 2.0).

The legacy report produced by ``SimulationSession.report()`` is embedded
unchanged at the top level, so existing consumers keep working.  Everything
new is added under new keys, with simulation evidence and real-process
telemetry kept in clearly separate, labelled sections.
"""
from __future__ import annotations

import itertools
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from process_monitor.exporters import unavailable_telemetry
from process_monitor.models import iso_now

REPORT_SCHEMA_VERSION = "2.0"

LEGACY_KEYS = ["scenario", "execution_history", "final_lock_ownership", "process_status",
               "waiting_processes", "wait_for_graph", "detected_cycles", "diagnosis",
               "recommendations", "lock_order_warnings", "recovery_actions", "outcomes"]
NEW_KEYS = ["schema_version", "report_type", "generated_at", "data_sources", "incident",
            "real_process_telemetry", "resource_monitoring", "recommendation_evidence",
            "real_process_actions", "before_after", "what_if_operations", "final_cycle_detection"]

DATA_SOURCES = {
    "simulation": ("Simulated processes, locks, Wait-For Graph, cycles, diagnosis and recovery. "
                   "An educational model; no real application or real lock is involved."),
    "real_process_telemetry": ("Measurements of real operating-system processes collected with psutil. "
                               "Contextual only: it does not show that any listed application is "
                               "involved in the simulated deadlock."),
}


class ReportError(ValueError):
    """The report failed validation and was not written."""


def build_full_report(simulation_report: Dict[str, Any], incident, live_telemetry: Optional[Dict[str, Any]],
                      actions: List[Dict[str, Any]], monitoring_status: Dict[str, Any],
                      settings: Optional[Dict[str, Any]], what_if_log: List[Dict[str, Any]]) -> Dict[str, Any]:
    report: Dict[str, Any] = dict(simulation_report)           # legacy keys, unchanged
    telemetry = (incident.telemetry if incident is not None else live_telemetry) \
        or unavailable_telemetry("No telemetry was captured.")
    recoveries = simulation_report.get("recovery_actions") or []
    last = recoveries[-1] if recoveries else None
    detected = simulation_report.get("detected_cycles") or []
    report.update({
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_type": "deadlock-detective-incident-report",
        "generated_at": iso_now(),
        "data_sources": dict(DATA_SOURCES),
        "incident": incident.to_dict() if incident is not None else None,
        "real_process_telemetry": telemetry,
        "resource_monitoring": {
            **monitoring_status,
            "thresholds_used": settings,
            "privacy_note": "No command-line arguments, user names or executable paths are exported.",
        },
        "recommendation_evidence": telemetry.get("recommendations", []),
        "real_process_actions": {
            "note": ("User-approved operations on REAL processes. Recommendations never run automatically, "
                     "and simulated recovery never touches real processes."),
            "records": list(actions),
        },
        "before_after": ({"state_before": last["state_before"], "state_after": last["state_after"],
                          "cycles_before": last["cycles_before"], "cycles_after": last["cycles_after"]}
                         if last else None),
        "what_if_operations": list(what_if_log),
        "final_cycle_detection": {"deadlock": bool(detected), "cycles": [c["processes"] for c in detected]},
    })
    return report


def _is_iso(value: Any) -> bool:
    try:
        datetime.fromisoformat(str(value))
        return True
    except ValueError:
        return False


def validate_report(report: Any) -> List[str]:
    """Return a list of structural problems (empty list = valid)."""
    if not isinstance(report, dict):
        return ["Report must be a JSON object."]
    problems = [f"Missing key: {k}" for k in LEGACY_KEYS + NEW_KEYS if k not in report]
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        problems.append(f"schema_version must be {REPORT_SCHEMA_VERSION}.")
    if "generated_at" in report and not _is_iso(report["generated_at"]):
        problems.append("generated_at is not an ISO 8601 timestamp.")
    tele = report.get("real_process_telemetry")
    if not isinstance(tele, dict) or not isinstance(tele.get("available"), bool):
        problems.append("real_process_telemetry must contain a boolean 'available'.")
    elif tele["available"] and not _is_iso(tele.get("captured_at")):
        problems.append("real_process_telemetry.captured_at is not an ISO 8601 timestamp.")
    inc = report.get("incident")
    if inc is not None:
        for key in ("incident_id", "created_at", "simulation_evidence", "real_process_telemetry", "timeline"):
            if key not in inc:
                problems.append(f"incident is missing {key}.")
        if "created_at" in inc and not _is_iso(inc["created_at"]):
            problems.append("incident.created_at is not an ISO 8601 timestamp.")
    try:
        json.dumps(report)
    except (TypeError, ValueError) as exc:
        problems.append(f"Report is not JSON-serialisable: {exc}")
    return problems


def unique_path(path: Union[str, Path]) -> Path:
    """``report.json`` -> ``report_2.json`` ... so an existing file is never silently replaced."""
    path = Path(path)
    if not path.exists():
        return path
    for i in itertools.count(2):
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise OSError("unreachable")  # pragma: no cover


def write_json_report(report: Dict[str, Any], path: Union[str, Path], overwrite: bool = False) -> Path:
    """Validate and write ``report`` atomically.

    Raises ``ReportError`` if the structure is invalid and ``OSError`` if the file cannot
    be written.  An existing file is kept (a numbered name is used) unless ``overwrite``.
    """
    problems = validate_report(report)
    if problems:
        raise ReportError("Report not written: " + "; ".join(problems[:5]))
    path = Path(path)
    if not overwrite:
        path = unique_path(path)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_report_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path
