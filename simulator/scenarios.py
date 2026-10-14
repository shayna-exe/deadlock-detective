"""Scenario loading and validation (scenarios are plain JSON, see data/scenarios.json)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Tuple, Union

from .events import Event, SimulationError


class ScenarioError(SimulationError):
    """Raised when a scenario file or definition is invalid."""


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    processes: Tuple[str, ...]
    locks: Tuple[str, ...]
    events: Tuple[Event, ...]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "processes": list(self.processes),
            "locks": list(self.locks),
            "events": [e.to_dict() for e in self.events],
        }


def _names(data: Mapping[str, Any], key: str, scenario: str) -> Tuple[str, ...]:
    raw = data.get(key)
    if not isinstance(raw, list) or not raw:
        raise ScenarioError(f"Scenario '{scenario}': '{key}' must be a non-empty list.")
    names = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ScenarioError(f"Scenario '{scenario}': '{key}' contains an invalid name {item!r}.")
        names.append(item.strip())
    if len(set(names)) != len(names):
        raise ScenarioError(f"Scenario '{scenario}': '{key}' contains duplicates.")
    return tuple(names)


def parse_scenario(data: Mapping[str, Any]) -> Scenario:
    """Validate one scenario dict and convert it to a ``Scenario``."""
    if not isinstance(data, Mapping):
        raise ScenarioError("Each scenario must be a JSON object.")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ScenarioError("Each scenario needs a non-empty 'name'.")
    name = name.strip()
    processes = _names(data, "processes", name)
    locks = _names(data, "locks", name)
    raw_events = data.get("events")
    if not isinstance(raw_events, list):
        raise ScenarioError(f"Scenario '{name}': 'events' must be a list.")
    events = []
    for i, raw in enumerate(raw_events, 1):
        try:
            ev = Event.from_dict(raw)
        except SimulationError as exc:
            raise ScenarioError(f"Scenario '{name}', event {i}: {exc}") from None
        if ev.process not in processes:
            raise ScenarioError(f"Scenario '{name}', event {i}: unknown process '{ev.process}'.")
        if ev.lock not in locks:
            raise ScenarioError(f"Scenario '{name}', event {i}: unknown lock '{ev.lock}'.")
        events.append(ev)
    description = data.get("description", "")
    if not isinstance(description, str):
        raise ScenarioError(f"Scenario '{name}': 'description' must be text.")
    return Scenario(name, description, processes, locks, tuple(events))


def load_scenarios(path: Union[str, Path]) -> List[Scenario]:
    """Load every scenario from a JSON file ``{"scenarios": [...]}``."""
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise ScenarioError(f"Scenario file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"Scenario file {path} is not valid JSON: {exc}") from None
    except OSError as exc:
        raise ScenarioError(f"Could not read scenario file {path}: {exc}") from None
    if not isinstance(data, Mapping) or not isinstance(data.get("scenarios"), list):
        raise ScenarioError("Scenario file must be an object with a 'scenarios' list.")
    scenarios = [parse_scenario(item) for item in data["scenarios"]]
    if not scenarios:
        raise ScenarioError("Scenario file contains no scenarios.")
    names = [s.name for s in scenarios]
    if len(set(names)) != len(names):
        raise ScenarioError("Scenario names must be unique.")
    return scenarios
