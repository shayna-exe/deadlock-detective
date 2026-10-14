"""JSON report assembly and export (no invented data: only what was observed)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence, Union

from detector.cycle_detector import DetectionResult, cycle_edges
from detector.lock_order_analyzer import LockOrderWarning
from simulator.lock_state import LockState
from simulator.wait_for_graph import graph_to_dict

from .explain import Diagnosis
from .recommend import Recommendation


def build_report(
    *,
    scenario_name: str,
    scenario_description: str,
    events_executed: int,
    events_total: int,
    state: LockState,
    graph,
    detection: DetectionResult,
    diagnosis: Diagnosis,
    recommendations: Sequence[Recommendation],
    warnings: Sequence[LockOrderWarning],
    recovery_actions: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    cycles = [
        {
            "processes": list(c),
            "edges": [{"from": u, "to": v, "lock": lock} for u, v, lock in cycle_edges(graph, c)],
        }
        for c in detection.cycles
    ]
    waiting = [
        {"process": p, "waiting_for_lock": state.waiting_for(p),
         "lock_held_by": state.owner_of(state.waiting_for(p))}
        for p in state.blocked_processes()
    ]
    if recovery_actions:
        recovery_outcome = (
            "Deadlock resolved by the last recovery action."
            if not detection.deadlock
            else "Deadlock still present after the last recovery action."
        )
    else:
        recovery_outcome = "No recovery action was performed."
    return {
        "scenario": {"name": scenario_name, "description": scenario_description,
                     "events_executed": events_executed, "events_total": events_total},
        "execution_history": [e.to_dict() for e in state.history],
        "final_lock_ownership": {l: state.owner_of(l) for l in state.locks},
        "process_status": {p: state.status_of(p).value for p in state.processes},
        "waiting_processes": waiting,
        "wait_for_graph": graph_to_dict(graph),
        "detected_cycles": cycles,
        "diagnosis": diagnosis.to_dict(),
        "recommendations": [r.to_dict() for r in recommendations],
        "lock_order_warnings": [w.to_dict() for w in warnings],
        "recovery_actions": list(recovery_actions),
        "outcomes": {
            "detection": "Deadlock detected." if detection.deadlock else "No deadlock detected.",
            "recovery": recovery_outcome,
        },
    }


def write_report(report: Dict[str, Any], path: Union[str, Path]) -> Path:
    """Write ``report`` as UTF-8 JSON; raises ``OSError`` if the file cannot be written."""
    path = Path(path)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path
