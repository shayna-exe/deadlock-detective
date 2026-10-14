"""What-if laboratory helpers: graph comparison and safe scenario editing.

All of this works on the SIMULATION only.  A scenario is validated completely
(names, events, and a dry run on a throw-away state) before it is accepted, so
an invalid scenario can never corrupt the running simulation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from detector.cycle_detector import find_cycles, format_cycle
from simulator import (Event, LockState, Scenario, ScenarioError, SimulationError, parse_scenario)

NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,24}$")
Edge = Tuple[str, str, str]


# ------------------------------------------------------------ graph comparison
@dataclass
class GraphComparison:
    removed_edges: List[Edge]
    added_edges: List[Edge]
    cycles_before: List[List[str]]
    cycles_after: List[List[str]]
    explanation: List[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return bool(self.cycles_before) and not self.cycles_after

    def to_dict(self) -> Dict[str, Any]:
        return {"removed_edges": [list(e) for e in self.removed_edges],
                "added_edges": [list(e) for e in self.added_edges],
                "cycles_before": self.cycles_before, "cycles_after": self.cycles_after,
                "deadlock_resolved": self.resolved, "explanation": list(self.explanation)}


def _edges(graph) -> set:
    return {(u, v, str(d.get("lock"))) for u, v, d in graph.edges(data=True)}


def compare_graphs(before, after, cycles_before: Sequence[Sequence[str]],
                   cycles_after: Sequence[Sequence[str]]) -> GraphComparison:
    """Explain what changed in the Wait-For Graph and why a cycle went or stayed."""
    eb, ea = _edges(before), _edges(after)
    removed, added = sorted(eb - ea), sorted(ea - eb)
    cb = [list(c) for c in cycles_before]
    ca = [list(c) for c in cycles_after]
    lines: List[str] = []
    if removed:
        lines.append("Wait edges removed: " + "; ".join(f"{u} -> {v} (lock {l})" for u, v, l in removed) + ".")
    if added:
        lines.append("Wait edges added: " + "; ".join(f"{u} -> {v} (lock {l})" for u, v, l in added) + ".")
    if not removed and not added:
        lines.append("The set of wait edges did not change.")
    for cycle in cb:
        cyc_edges = set(zip(cycle, cycle[1:] + cycle[:1]))
        gone = sorted((u, v) for u, v, _ in removed if (u, v) in cyc_edges)
        txt = format_cycle(cycle)
        if cycle in ca:
            lines.append(f"Cycle {txt} REMAINS: none of its edges was removed, so every process in it still "
                         "waits for the next one.")
        elif gone:
            lines.append(f"Cycle {txt} DISAPPEARED: a cycle needs every one of its edges, and "
                         + ", ".join(f"{u} -> {v}" for u, v in gone) + " no longer exists.")
        else:
            lines.append(f"Cycle {txt} disappeared because its processes no longer wait in a circle.")
    for cycle in ca:
        if cycle not in cb:
            lines.append(f"NEW cycle {format_cycle(cycle)} now exists.")
    if not cb and not ca:
        lines.append("There was no cycle before and there is none now.")
    return GraphComparison(removed, added, cb, ca, lines)


# ------------------------------------------------------------ scenario editing
def _split_names(text: str, what: str) -> List[str]:
    names = [n for n in re.split(r"[,\s;]+", text.strip()) if n]
    if not names:
        raise ScenarioError(f"Enter at least one {what} name.")
    bad = [n for n in names if not NAME_RE.match(n)]
    if bad:
        raise ScenarioError(f"Invalid {what} name(s): {', '.join(bad)} "
                            "(use letters, digits, '_' or '-', up to 24 characters).")
    if len(set(names)) != len(names):
        raise ScenarioError(f"Duplicate {what} names.")
    return names


def parse_events_text(text: str) -> List[Dict[str, str]]:
    """Parse lines such as ``P1 ACQUIRE A`` (blank lines and ``#`` comments are ignored)."""
    events: List[Dict[str, str]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p for p in re.split(r"[,\s]+", line) if p]
        if len(parts) != 3:
            raise ScenarioError(f"Line {lineno}: expected 'PROCESS OPERATION LOCK', got {raw.strip()!r}.")
        events.append({"process": parts[0], "op": parts[1], "lock": parts[2]})
    return events


def dry_run(scenario: Scenario) -> List[str]:
    """Replay the scenario on a throw-away state; return one message per problem."""
    state = LockState(scenario.processes, scenario.locks, strict=True)
    for i, ev in enumerate(scenario.events, 1):
        try:
            state.apply(ev)
        except SimulationError as exc:
            return [f"Event {i} ({ev}): {exc}"]
    return []


def build_scenario(name: str, description: str, processes_text: str, locks_text: str,
                   events_text: str) -> Scenario:
    """Validate editor input and return a ``Scenario`` (raises ``ScenarioError``)."""
    name = name.strip()
    if not name or len(name) > 60:
        raise ScenarioError("Give the scenario a name (1-60 characters).")
    data = {"name": name, "description": description.strip(),
            "processes": _split_names(processes_text, "process"),
            "locks": _split_names(locks_text, "lock"),
            "events": parse_events_text(events_text)}
    scenario = parse_scenario(data)
    problems = dry_run(scenario)
    if problems:
        raise ScenarioError("The event sequence is not valid: " + problems[0])
    return scenario
