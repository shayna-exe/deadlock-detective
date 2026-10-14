"""Exports of real-process telemetry (CSV) and the 'telemetry unavailable' placeholder."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Union

from .models import iso_from_epoch

CSV_COLUMNS = ["sampled_at", "pid", "name", "status", "cpu_percent", "cpu_time_total_s", "rss_mb",
               "mem_percent", "num_threads", "recommendation", "evidence_strength", "rule_id", "access"]


def unavailable_telemetry(reason: str) -> Dict[str, Any]:
    """Used in incidents/reports when no live samples exist."""
    return {
        "available": False,
        "reason": reason,
        "disclaimer": "Resource telemetry could not be collected; deadlock analysis is unaffected.",
        "top_cpu_consumers": [], "top_memory_consumers": [], "recommendations": [],
    }


def snapshot_to_csv(snapshot, path: Union[str, Path]) -> Path:
    """Write one row per process (no command lines, paths or user names).

    Raises ``OSError`` if the file cannot be written.
    """
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for a in snapshot.assessments:
            d = a.sample.to_dict()
            writer.writerow({
                "sampled_at": iso_from_epoch(a.sample.sampled_at), "pid": d["pid"], "name": d["name"],
                "status": d["status"], "cpu_percent": d["cpu_percent"],
                "cpu_time_total_s": d["cpu_time_total_s"], "rss_mb": d["rss_mb"],
                "mem_percent": d["mem_percent"], "num_threads": d["num_threads"],
                "recommendation": a.category, "evidence_strength": a.strength, "rule_id": a.rule_id,
                "access": d["access"],
            })
    return path
