"""Incident data model.  Simulation evidence and real-process telemetry stay in separate fields."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SRC_SIMULATION = "simulation"
SRC_TELEMETRY = "real-process telemetry"
SRC_USER = "user decision"
SRC_REAL_ACTION = "real-process action"

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "deadlock still present"
STATUS_ABANDONED = "abandoned (scenario was reset)"


@dataclass(frozen=True)
class TimelineEntry:
    at: str            # ISO 8601
    kind: str          # DETECTED, DIAGNOSED, RECOMMENDED, TELEMETRY, DECISION, RECOVERY, VERIFIED, ...
    source: str        # one of the SRC_* labels
    text: str

    def to_dict(self) -> Dict[str, str]:
        return {"at": self.at, "kind": self.kind, "source": self.source, "text": self.text}


@dataclass
class Incident:
    id: str
    created_at: str
    scenario_name: str
    scenario_description: str
    cycles: List[List[str]]
    state_at_detection: Dict[str, Any]
    graph: Dict[str, Any]
    diagnosis: Dict[str, Any]
    recommendations: List[Dict[str, Any]]
    recovery_options: List[Dict[str, Any]]
    telemetry: Dict[str, Any]
    timeline: List[TimelineEntry] = field(default_factory=list)
    recoveries: List[Dict[str, Any]] = field(default_factory=list)
    verification: Optional[Dict[str, Any]] = None
    state_after: Optional[Dict[str, Any]] = None
    status: str = STATUS_OPEN
    closed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.id, "created_at": self.created_at, "closed_at": self.closed_at,
            "status": self.status,
            "simulation_evidence": {
                "label": "SIMULATED processes and locks (educational model, not real applications)",
                "scenario": {"name": self.scenario_name, "description": self.scenario_description},
                "state_at_detection": self.state_at_detection,
                "wait_for_graph": self.graph,
                "cycles": self.cycles,
                "diagnosis": self.diagnosis,
                "recommendations": self.recommendations,
                "recovery_options_considered": self.recovery_options,
                "recoveries_applied": self.recoveries,
                "state_after": self.state_after,
                "final_verification": self.verification,
            },
            "real_process_telemetry": self.telemetry,
            "timeline": [t.to_dict() for t in self.timeline],
        }
