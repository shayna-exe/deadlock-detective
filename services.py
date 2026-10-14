"""Application services container: wires the simulator session, real-process monitoring,
the safe action controller and the incident service together.

The GUI talks to this object (and to ``SimulationSession``); tests can build it with a
fake ``psutil`` and a temporary settings file, so nothing here needs Tkinter.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

from incidents import IncidentService, build_full_report, write_json_report
from process_monitor import (MonitoringService, MonitorSettings, ProcessController, SettingsError,
                             load_settings, save_settings, snapshot_to_csv, unavailable_telemetry)
from process_monitor.actions import ActionRecord
from process_monitor.models import ProcessSample
from session import SimulationSession

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parent / "config" / "monitor_settings.json"


class AppServices:
    def __init__(self, session: SimulationSession, settings_path: Optional[Union[str, Path]] = None,
                 psutil_module: Any = None, own_pids=None) -> None:
        self.session = session
        self.settings_path = Path(settings_path) if settings_path else DEFAULT_SETTINGS_PATH
        self.settings_warning: Optional[str] = None
        try:
            self.settings = load_settings(self.settings_path)
        except SettingsError as exc:
            self.settings = MonitorSettings().validate()
            self.settings_warning = f"Saved settings were ignored ({exc}); defaults are in use."

        self.monitoring: Optional[MonitoringService] = None
        self.controller: Optional[ProcessController] = None
        self.monitoring_error: Optional[str] = None
        try:
            if psutil_module is None:
                import psutil as psutil_module  # noqa: F811
            self.monitoring = MonitoringService(self.settings, psutil_module, own_pids)
            self.controller = ProcessController(self.settings, psutil_module, own_pids)
        except ImportError:
            self.monitoring_error = "The 'psutil' package is not installed. Run: pip install -r requirements.txt"

        self.incidents = IncidentService(
            session, telemetry_provider=self._latest_snapshot,
            action_log_provider=(self.controller.log_as_dicts if self.controller else None))

    # ------------------------------------------------------------- telemetry
    def _latest_snapshot(self):
        return self.monitoring.latest() if self.monitoring else None

    def monitoring_status(self) -> Dict[str, Any]:
        if self.monitoring is None:
            return {"available": False, "running": False, "reason": self.monitoring_error}
        snap = self.monitoring.latest()
        return {"available": True, "running": self.monitoring.is_running(),
                "samples_taken": snap.sequence if snap else 0,
                "last_error": self.monitoring.last_error,
                "collection_errors": list(snap.errors) if snap else []}

    # --------------------------------------------------------------- actions
    def execute_action(self, sample: ProcessSample, operation: str, confirmed: bool) -> ActionRecord:
        if self.controller is None:
            raise RuntimeError("Process management is unavailable (psutil is not installed).")
        record = self.controller.execute(sample, operation, confirmed)
        if record.outcome != "refused":
            self.incidents.note_real_action(record)
        return record

    # -------------------------------------------------------------- settings
    def apply_settings(self, settings: MonitorSettings, save: bool = False) -> None:
        settings = settings.validate()
        self.settings = settings
        if self.monitoring:
            self.monitoring.apply_settings(settings)
        if self.controller:
            self.controller.settings = settings
        if save:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            save_settings(settings, self.settings_path)

    # --------------------------------------------------------------- reports
    def full_report(self) -> Dict[str, Any]:
        inc = self.incidents.latest()
        snap = self._latest_snapshot()
        live = snap.telemetry_dict() if snap else unavailable_telemetry(
            self.monitoring_error or "Live monitoring is not running or has produced no samples yet.")
        return build_full_report(
            self.session.report(), inc, live, self.incidents.actions_since(inc),
            self.monitoring_status(), self.settings.to_dict(), self.session.what_if_log)

    def export_report(self, path: Union[str, Path], overwrite: bool = False) -> Path:
        return write_json_report(self.full_report(), path, overwrite=overwrite)

    def export_snapshot_csv(self, path: Union[str, Path]) -> Path:
        snap = self._latest_snapshot()
        if snap is None:
            raise ValueError("There is no process snapshot yet. Start monitoring first.")
        return snapshot_to_csv(snap, path)

    # -------------------------------------------------------------- shutdown
    def shutdown(self) -> list:
        """Stop the worker thread; return [(pid, name)] of processes still suspended by this program."""
        if self.monitoring:
            self.monitoring.stop()
        return self.controller.suspended_processes() if self.controller else []
