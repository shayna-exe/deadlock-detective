import json
from pathlib import Path

import pytest

from session import SimulationSession
from simulator import ScenarioError, SimulationError, load_scenarios, parse_scenario

DATA = Path(__file__).resolve().parent.parent / "data" / "scenarios.json"


@pytest.fixture
def session():
    return SimulationSession(load_scenarios(DATA))


def run(session, name):
    session.load(name)
    session.run_all()
    return session


def test_bundled_scenarios_load_and_cover_required_cases(session):
    assert session.scenario_names == ["Safe execution", "Two-process deadlock",
                                      "Three-process deadlock", "Lock-order conflict"]


@pytest.mark.parametrize("name,deadlock,cycle_len,warnings", [
    ("Safe execution", False, None, 0),
    ("Two-process deadlock", True, 2, 1),
    ("Three-process deadlock", True, 3, 0),
    ("Lock-order conflict", False, None, 1),
])
def test_scenario_outcomes(session, name, deadlock, cycle_len, warnings):
    run(session, name)
    det = session.detect()
    assert det.deadlock is deadlock
    if cycle_len:
        assert len(det.cycles[0]) == cycle_len
    assert len(session.lock_order_warnings()) == warnings


def test_safe_scenario_ends_with_all_locks_free(session):
    run(session, "Safe execution")
    assert all(session.state.owner_of(l) is None for l in session.state.locks)


def test_stepping_and_staleness(session):
    session.load("Two-process deadlock")
    assert not session.detection_current
    session.run_all()
    session.detect()
    assert session.detection_current
    session.abort_process("P1")
    assert session.detection_current            # recovery re-ran detection
    assert not session.last_detection.deadlock
    with pytest.raises(SimulationError):
        session.step()                           # no more events


def test_repeat_detection_flagged_as_repeated(session):
    run(session, "Two-process deadlock")
    assert session.detect().new_cycles
    assert session.detect().repeated


def test_report_is_valid_json_with_required_sections(session, tmp_path):
    run(session, "Two-process deadlock")
    session.auto_recover()
    path = session.write_report(tmp_path / "r.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ["scenario", "execution_history", "final_lock_ownership", "waiting_processes",
                "wait_for_graph", "detected_cycles", "diagnosis", "recommendations",
                "lock_order_warnings", "recovery_actions", "outcomes"]:
        assert key in data
    assert data["scenario"]["name"] == "Two-process deadlock"
    assert data["recovery_actions"][0]["deadlock_resolved"] is True
    assert data["outcomes"]["detection"] == "No deadlock detected."
    assert "resolved" in data["outcomes"]["recovery"]
    assert len(data["execution_history"]) == len(session.state.history)
    assert "timestamp" not in json.dumps(data).lower()


def test_report_before_recovery_shows_cycle(session):
    run(session, "Three-process deadlock")
    data = session.report()
    assert data["detected_cycles"][0]["processes"] == ["P1", "P2", "P3"]
    assert {e["lock"] for e in data["detected_cycles"][0]["edges"]} == {"A", "B", "C"}
    assert data["diagnosis"]["status"] == "DEADLOCK_DETECTED"
    assert data["outcomes"]["recovery"] == "No recovery action was performed."


def test_report_write_error_is_oserror(session, tmp_path):
    with pytest.raises(OSError):
        session.write_report(tmp_path / "missing_dir" / "r.json")


# ----------------------------------------------------------- scenario parsing
def test_scenario_validation_errors(tmp_path):
    base = {"name": "x", "processes": ["P1"], "locks": ["A"],
            "events": [{"process": "P1", "op": "ACQUIRE", "lock": "A"}]}
    assert parse_scenario(base).name == "x"
    bad_op = dict(base, events=[{"process": "P1", "op": "GRAB", "lock": "A"}])
    with pytest.raises(ScenarioError, match="Unknown operation"):
        parse_scenario(bad_op)
    with pytest.raises(ScenarioError, match="unknown lock"):
        parse_scenario(dict(base, events=[{"process": "P1", "op": "ACQUIRE", "lock": "Z"}]))
    with pytest.raises(ScenarioError, match="duplicates"):
        parse_scenario(dict(base, processes=["P1", "P1"]))
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ScenarioError, match="not valid JSON"):
        load_scenarios(p)
    with pytest.raises(ScenarioError, match="not found"):
        load_scenarios(tmp_path / "nope.json")
