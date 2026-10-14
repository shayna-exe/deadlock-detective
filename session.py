"""Application controller shared by the GUI and the tests.

``SimulationSession`` ties together the simulator, detector, diagnosis,
recovery and report code so the GUI contains no business logic of its own.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from detector import CycleDetector, DetectionResult, LockOrderAnalyzer, LockOrderWarning
from diagnosis import Diagnosis, Recommendation, build_report, explain, recommend, write_report
from lab.whatif import GraphComparison, compare_graphs
from recovery import RecoveryManager, RecoveryOption, RecoveryResult, preview_options
from simulator import (
    Event,
    EventType,
    HistoryEntry,
    LockState,
    Scenario,
    SimulationError,
    build_wait_for_graph,
)

#: Observer signature: ``listener(kind, payload)``.  Kinds: "reset", "detected", "recovered",
#: "what_if".  Observers (e.g. the incident service) must never modify the simulation.
Listener = Callable[[str, Any], None]


class SimulationSession:
    def __init__(self, scenarios: Sequence[Scenario]) -> None:
        if not scenarios:
            raise SimulationError("At least one scenario is required.")
        self.scenarios = {s.name: s for s in scenarios}
        self.user_scenarios: set = set()     # names created in the what-if editor
        self._listeners: List[Listener] = []
        self.what_if_log: List[Dict[str, Any]] = []
        self.scenario: Scenario = scenarios[0]
        self.load(self.scenario.name)

    # -------------------------------------------------------------- observers
    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _notify(self, kind: str, payload: Any = None) -> None:
        for listener in list(self._listeners):
            try:
                listener(kind, payload)
            except Exception:  # an observer bug must never break the simulation
                pass

    # ---------------------------------------------------------------- control
    @property
    def scenario_names(self) -> List[str]:
        return list(self.scenarios)

    def load(self, name: str) -> None:
        """Select a scenario and reset the simulation to its start."""
        if name not in self.scenarios:
            raise SimulationError(f"Unknown scenario '{name}'.")
        self.scenario = self.scenarios[name]
        self.reset()

    def reset(self) -> None:
        sc = self.scenario
        self.state = LockState(sc.processes, sc.locks, strict=True)
        self.position = 0  # number of scripted events executed
        self.detector = CycleDetector()
        self.recovery = RecoveryManager(self.state)
        self._detection: Optional[DetectionResult] = None
        self._detected_version = -1
        self.what_if_log = []
        self._notify("reset", self.scenario.name)

    @property
    def total_events(self) -> int:
        return len(self.scenario.events)

    @property
    def has_next(self) -> bool:
        return self.position < self.total_events

    def step(self) -> List[HistoryEntry]:
        """Execute the next scripted event (raises ``SimulationError`` if it is invalid)."""
        if not self.has_next:
            raise SimulationError("The scenario has no more events.")
        entries = self.state.apply(self.scenario.events[self.position])
        self.position += 1
        return entries

    def run_all(self) -> List[HistoryEntry]:
        entries: List[HistoryEntry] = []
        while self.has_next:
            entries.extend(self.step())
        return entries

    # -------------------------------------------------------------- detection
    @property
    def graph(self):
        return build_wait_for_graph(self.state)

    @property
    def detection_current(self) -> bool:
        """True if the last detection run still matches the current state."""
        return self._detection is not None and self._detected_version == self.state.version

    @property
    def last_detection(self) -> Optional[DetectionResult]:
        return self._detection

    def detect(self) -> DetectionResult:
        """Run Wait-For-Graph cycle detection on the current state."""
        self._detection = self.detector.detect(self.graph)
        self._detected_version = self.state.version
        self._notify("detected", self._detection)
        return self._detection

    def lock_order_warnings(self) -> List[LockOrderWarning]:
        """Historical (potential) risks; independent of the current-deadlock check."""
        return LockOrderAnalyzer().analyze(self.state.history)

    def diagnose(self) -> Diagnosis:
        detection = self._detection if self.detection_current else self.detect()
        return explain(self.state, self.graph, detection.cycles, self.lock_order_warnings())

    def recommendations(self) -> List[Recommendation]:
        detection = self._detection if self.detection_current else self.detect()
        return recommend(self.graph, detection.cycles, self.lock_order_warnings())

    # --------------------------------------------------------------- recovery
    def abort_process(self, victim: str) -> RecoveryResult:
        result = self.recovery.abort_process(victim)
        self._after_recovery(result)
        return result

    def auto_recover(self) -> RecoveryResult:
        result = self.recovery.auto_recover()
        self._after_recovery(result)
        return result

    def _after_recovery(self, result: RecoveryResult) -> None:
        self._notify("recovered", result)   # observers see the recovery first...
        self.detect()                       # ...then the verification run is made

    def recovery_options(self) -> List[RecoveryOption]:
        """Compare every possible simulated victim without changing anything."""
        return preview_options(self.state)

    # ---------------------------------------------------------------- what-if
    def manual_release(self, process: str, lock: str) -> List[HistoryEntry]:
        """What-if: make ``process`` release ``lock`` outside the scripted events.

        Uses the simulator's normal RELEASE rules (and raises ``SimulationError``,
        leaving the state unchanged, if it is not allowed).  The scripted position
        is not advanced; Reset restores the scenario.
        """
        before_graph, before_cycles = self.graph, self.detector_cycles()
        entries = self.state.apply(Event(process, EventType.RELEASE, lock))
        comparison = compare_graphs(before_graph, self.graph, before_cycles, self.detector_cycles())
        self.what_if_log.append({"operation": f"{process} RELEASE {lock} (what-if, simulated)",
                                 "comparison": comparison.to_dict()})
        self._notify("what_if", comparison)
        return entries

    def detector_cycles(self) -> List[List[str]]:
        """Cycles in the current state computed on demand (does not touch detection state)."""
        from detector import find_cycles
        return find_cycles(self.graph)

    def compare_with(self, before_graph, before_cycles) -> GraphComparison:
        return compare_graphs(before_graph, self.graph, before_cycles, self.detector_cycles())

    def add_scenario(self, scenario: Scenario, replace_own: bool = False) -> None:
        """Register a validated scenario (e.g. from the editor).

        Bundled scenarios can never be overwritten; user-made ones only with ``replace_own``.
        """
        if scenario.name in self.scenarios:
            if scenario.name not in self.user_scenarios:
                raise SimulationError(f"'{scenario.name}' is a bundled scenario and cannot be replaced.")
            if not replace_own:
                raise SimulationError(f"A scenario named '{scenario.name}' already exists.")
        self.scenarios[scenario.name] = scenario
        self.user_scenarios.add(scenario.name)

    # ----------------------------------------------------------------- report
    def report(self) -> Dict[str, Any]:
        detection = self._detection if self.detection_current else self.detect()
        graph = self.graph
        warnings = self.lock_order_warnings()
        return build_report(
            scenario_name=self.scenario.name,
            scenario_description=self.scenario.description,
            events_executed=self.position,
            events_total=self.total_events,
            state=self.state,
            graph=graph,
            detection=detection,
            diagnosis=explain(self.state, graph, detection.cycles, warnings),
            recommendations=recommend(graph, detection.cycles, warnings),
            warnings=warnings,
            recovery_actions=[r.to_dict() for r in self.recovery.log],
        )

    def write_report(self, path: Union[str, Path]) -> Path:
        return write_report(self.report(), path)
