from pathlib import Path

import pytest

from detector import find_cycles
from lab.whatif import (build_scenario, compare_graphs, dry_run, parse_events_text)
from recovery import CRITERIA, check_prediction, preview_options
from session import SimulationSession
from simulator import Event, EventType, LockState, ScenarioError, SimulationError, build_wait_for_graph, load_scenarios

DATA = Path(__file__).resolve().parent.parent / "data" / "scenarios.json"


@pytest.fixture
def session():
    return SimulationSession(load_scenarios(DATA))


def ready(session, name):
    session.load(name); session.run_all(); session.detect(); return session


def test_preview_does_not_change_the_state(session):
    ready(session, "Two-process deadlock")
    before, version = session.state.snapshot(), session.state.version
    session.recovery_options()
    assert session.state.snapshot() == before and session.state.version == version
    assert session.recovery.log == []


def test_options_describe_victim_locks_and_handoffs(session):
    ready(session, "Two-process deadlock")
    opts = {o.victim: o for o in session.recovery_options()}
    p1 = opts["P1"]
    assert p1.held_locks == ["A"] and p1.handoffs == [("A", "P2")]
    assert p1.in_cycle and p1.predicted_resolved and p1.predicted_cycles_after == []
    assert (p1.blocked_before, p1.blocked_after) == (2, 0)
    text = " ".join(p1.summary_lines())
    assert "A -> P2" in text and "no cycle remains" in text


def test_suggested_option_matches_existing_heuristic_and_is_ranked_first(session):
    ready(session, "Three-process deadlock")
    opts = session.recovery_options()
    victim, _ = session.recovery.suggest_victim()
    assert opts[0].victim == victim and opts[0].suggested and sum(o.suggested for o in opts) == 1
    assert [o.rank for o in opts] == [1, 2, 3]


def test_outsider_is_predicted_not_to_resolve():
    s = LockState()
    for p, op, l in [("P1", "ACQUIRE", "A"), ("P2", "ACQUIRE", "B"), ("P1", "REQUEST", "B"),
                     ("P2", "REQUEST", "A"), ("P3", "ACQUIRE", "C")]:
        s.apply(Event(p, EventType.parse(op), l))
    opts = {o.victim: o for o in preview_options(s)}
    assert not opts["P3"].in_cycle and not opts["P3"].predicted_resolved
    assert opts["P3"].predicted_cycles_after == [["P1", "P2"]]
    assert preview_options(s)[-1].victim == "P3"            # outsiders rank last


def test_prediction_matches_actual_outcome_for_every_option(session):
    ready(session, "Three-process deadlock")
    for option in session.recovery_options():
        session.reset(); session.run_all(); session.detect()
        chosen = next(o for o in session.recovery_options() if o.victim == option.victim)
        result = session.abort_process(option.victim)
        assert check_prediction(chosen, result).matched


def test_no_options_complaint_for_safe_state_and_criteria_documented(session):
    ready(session, "Safe execution")
    assert not any(o.suggested for o in session.recovery_options())
    assert len(CRITERIA) >= 4 and "not a proof of optimality" in CRITERIA[-1]


# ------------------------------------------------------------------ what-if
def test_manual_release_breaks_waiting_chain_and_explains_it(session):
    session.load("Two-process deadlock")
    session.step(); session.step()                         # P1 holds A, P2 holds B
    session.step(); session.step()                         # both blocked: deadlock
    assert session.detect().deadlock
    with pytest.raises(SimulationError):
        session.manual_release("P1", "A")                  # P1 is blocked and cannot act
    assert session.detect().deadlock                        # failed what-if changed nothing


def test_manual_release_before_deadlock_and_comparison_text(session):
    session.load("Safe execution")
    session.step(); session.step()                         # P1 holds A; P2 blocked on A
    graph, cycles = session.graph, session.detector_cycles()
    session.manual_release("P1", "A")
    cmp = session.compare_with(graph, cycles)
    assert ("P2", "P1", "A") in cmp.removed_edges and any("no cycle" in l.lower() for l in cmp.explanation)
    assert session.what_if_log and "simulated" in session.what_if_log[0]["operation"]
    assert not session.detection_current                    # detection is flagged stale


def test_compare_graphs_explains_disappearing_and_remaining_cycle(session):
    ready(session, "Two-process deadlock")
    before, cb = session.graph, session.detector_cycles()
    result = session.abort_process("P1")
    cmp = session.compare_with(before, cb)
    assert cmp.resolved and any("DISAPPEARED" in l for l in cmp.explanation)
    same = compare_graphs(before, before, cb, cb)
    assert not same.resolved and any("REMAINS" in l for l in same.explanation)
    assert "edges did not change" in same.explanation[0]


def test_reset_restores_scenario_after_what_if(session):
    session.load("Safe execution"); session.step(); session.step()
    session.manual_release("P1", "A")
    session.reset()
    assert session.position == 0 and session.what_if_log == []


# --------------------------------------------------------- scenario editing
def test_build_scenario_accepts_valid_input():
    sc = build_scenario("Mine", "demo", "P1, P2", "A B", "P1 ACQUIRE A  # first\n\nP2 request A")
    assert sc.processes == ("P1", "P2") and [str(e) for e in sc.events] == ["P1 ACQUIRE A", "P2 REQUEST A"]


@pytest.mark.parametrize("name,procs,locks,events,message", [
    ("", "P1", "A", "", "name"),
    ("x", "", "A", "", "process"),
    ("x", "P 1!", "A", "", "Invalid process"),
    ("x", "P1 P1", "A", "", "Duplicate"),
    ("x", "P1", "A", "P1 ACQUIRE", "expected"),
    ("x", "P1", "A", "P1 GRAB A", "Unknown operation"),
    ("x", "P1", "A", "P9 ACQUIRE A", "unknown process"),
    ("x", "P1", "A", "P1 ACQUIRE Z", "unknown lock"),
    ("x", "P1", "A", "P1 RELEASE A", "not valid"),
])
def test_build_scenario_rejects_invalid_input(name, procs, locks, events, message):
    with pytest.raises(ScenarioError, match=message):
        build_scenario(name, "", procs, locks, events)


def test_add_scenario_protects_bundled_and_allows_own_replacement(session):
    mine = build_scenario("Mine", "", "P1", "A", "P1 ACQUIRE A")
    session.add_scenario(mine)
    assert "Mine" in session.scenario_names
    with pytest.raises(SimulationError, match="already exists"):
        session.add_scenario(mine)
    session.add_scenario(build_scenario("Mine", "", "P1", "A", ""), replace_own=True)
    bundled = build_scenario("Safe execution", "", "P1", "A", "")
    with pytest.raises(SimulationError, match="bundled"):
        session.add_scenario(bundled)


def test_invalid_scenario_never_corrupts_running_simulation(session):
    session.load("Two-process deadlock"); session.step()
    snap = session.state.snapshot()
    with pytest.raises(ScenarioError):
        build_scenario("bad", "", "P1", "A", "P1 RELEASE A")
    assert session.state.snapshot() == snap and session.position == 1


def test_dry_run_and_events_parser_report_line_numbers():
    with pytest.raises(ScenarioError, match="Line 2"):
        parse_events_text("P1 ACQUIRE A\nbroken line here now")
    sc = build_scenario("ok", "", "P1", "A", "P1 ACQUIRE A")
    assert dry_run(sc) == []
