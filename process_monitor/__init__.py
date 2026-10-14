"""Real operating-system process monitoring (psutil) with explainable recommendations.

Kept separate from the deadlock simulator on purpose: simulated processes and
real processes are different things and must never be mixed up.
"""
from .actions import ActionRecord, Availability, ProcessController
from .activity_tracker import ActivityTracker, WindowStats
from .exporters import snapshot_to_csv, unavailable_telemetry
from .models import CollectionResult, ProcessSample, SystemSample, iso_now
from .monitor import ProcessMonitor
from .recommendations import (CATEGORIES, CATEGORY_HELP, ProcessAssessment, RecommendationEngine)
from .service import MonitoringService, MonitorSnapshot
from .settings import MonitorSettings, SettingsError, load_settings, save_settings

__all__ = [
    "ActionRecord", "Availability", "ProcessController", "ActivityTracker", "WindowStats",
    "snapshot_to_csv", "unavailable_telemetry", "CollectionResult", "ProcessSample", "SystemSample",
    "iso_now", "ProcessMonitor", "CATEGORIES", "CATEGORY_HELP", "ProcessAssessment",
    "RecommendationEngine", "MonitoringService", "MonitorSnapshot", "MonitorSettings",
    "SettingsError", "load_settings", "save_settings",
]
