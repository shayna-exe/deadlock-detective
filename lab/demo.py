"""Guided demonstration of one complete deadlock workflow (simulation only).

Load scenario -> execute events -> detect -> highlight cycle -> explain ->
compare recovery -> apply simulated recovery -> verify -> export report.

The class is pure logic so it can be tested without a GUI.  ``advance()``
performs the next step and returns what the GUI should say and show.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Union

from detector import format_cycle

DEMO_SCENARIO = "Two-process deadlock"

# Names of the GUI areas a step wants to bring to the front.
VIEW_SIMULATOR = "simulator"
VIEW_GRAPH = "graph"
VIEW_DIAGNOSIS = "diagnosis"
VIEW_RECOVERY = "recovery"
VIEW_REPORTS = "reports"


@dataclass
class DemoStep:
    title: str
    view: str
    text: str
    finished: bool = False


class GuidedDemo:
    def __init__(self, session, export: Optional[Callable[[Union[str, Path]], Path]] = None,
                 export_path: Optional[Union[str, Path]] = None) -> None:
        self.session = session
        self._export = export
        self._export_path = export_path
        self.phase = "load"
        self.running = False
        self.exported_to: Optional[Path] = None

    # ------------------------------------------------------------------ API
    def start(self) -> DemoStep:
        self.running, self.phase = True, "load"
        return self.advance()

    def stop(self) -> None:
        self.running = False
        self.phase = "load"

    @property
    def finished(self) -> bool:
        return self.phase == "done"

    def advance(self) -> DemoStep:
        """Perform the next demonstration step."""
        s = self.session
        if not self.running:
            self.running = True
            self.phase = "load"
        if self.phase == "load":
            s.load(DEMO_SCENARIO)
            self.phase = "events"
            return DemoStep("1. Load the scenario", VIEW_SIMULATOR,
                            f"Loaded “{DEMO_SCENARIO}”. P1 and P2 are SIMULATED processes sharing two simulated "
                            f"locks, A and B. {s.total_events} scripted events will run one at a time.")
        if self.phase == "events":
            entries = s.step()
            if not s.has_next:
                self.phase = "detect"
            e = entries[0]
            return DemoStep(f"2. Execute event {s.position} of {s.total_events}", VIEW_SIMULATOR,
                            e.message + ("" if s.has_next else " That was the last event."))
        if self.phase == "detect":
            result = s.detect()
            self.phase = "highlight"
            msg = ("Wait-For Graph cycle detection found a deadlock." if result.deadlock
                   else "Cycle detection found no deadlock.")
            return DemoStep("3. Detect the deadlock", VIEW_GRAPH, msg)
        if self.phase == "highlight":
            self.phase = "explain"
            cycles = s.last_detection.cycles if s.last_detection else []
            text = ("The cycle is highlighted in red on the graph: " + "; ".join(format_cycle(c) for c in cycles)
                    + ". Each arrow means “waits for a lock held by”.") if cycles else "There is no cycle to highlight."
            return DemoStep("4. Highlight the cycle", VIEW_GRAPH, text)
        if self.phase == "explain":
            self.phase = "compare"
            d = s.diagnose()
            return DemoStep("5. Explain", VIEW_DIAGNOSIS, d.headline + " " + (d.explanation[0] if d.explanation else ""))
        if self.phase == "compare":
            self.phase = "apply"
            opts = s.recovery_options()
            lines = [f"Abort {o.victim}: {'resolves' if o.predicted_resolved else 'does not resolve'} the deadlock, "
                     f"holds {len(o.held_locks)} lock(s)." for o in opts]
            return DemoStep("6. Compare recovery options (simulated)", VIEW_RECOVERY, " ".join(lines))
        if self.phase == "apply":
            result = s.auto_recover()
            self.phase = "verify"
            return DemoStep("7. Apply the simulated recovery", VIEW_RECOVERY,
                            f"Aborted simulated process {result.victim}. {result.reason} "
                            "No real process was touched.")
        if self.phase == "verify":
            self.phase = "export"
            ok = s.last_detection is not None and not s.last_detection.deadlock
            return DemoStep("8. Verify", VIEW_GRAPH,
                            "Detection was re-run: no cycle remains, the deadlock is resolved." if ok
                            else "Detection was re-run: a cycle still remains.")
        if self.phase == "export":
            self.phase = "done"
            self.running = False
            if self._export and self._export_path:
                self.exported_to = self._export(self._export_path)
                return DemoStep("9. Export the report", VIEW_REPORTS, f"Report saved to {self.exported_to}.", True)
            return DemoStep("9. Export the report", VIEW_REPORTS,
                            "Use “Export incident report” on the Reports tab to save the JSON report.", True)
        return DemoStep("Demonstration finished", VIEW_SIMULATOR, "Press Start to run it again.", True)
