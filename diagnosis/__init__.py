"""Plain-language diagnosis, recommendations and JSON report building."""
from .explain import STATUS_DEADLOCK, STATUS_NONE, Diagnosis, explain
from .recommend import CONFIRMED, GENERAL, RISK, Recommendation, recommend
from .report import build_report, write_report

__all__ = [
    "STATUS_DEADLOCK", "STATUS_NONE", "Diagnosis", "explain", "CONFIRMED", "GENERAL", "RISK",
    "Recommendation", "recommend", "build_report", "write_report",
]
