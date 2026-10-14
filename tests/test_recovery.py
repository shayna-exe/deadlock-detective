import pytest

from detector import find_cycles
from recovery import RecoveryManager
from simulator import Event, EventType, LockState, SimulationError, build_wait_for_graph


def deadlocked(extra=()):
    s = LockState()
    for p, op, l in [("P1", "ACQUIRE", "A"), ("P2", "ACQUIRE", "B"),
                     ("P1", "REQUEST", "B"), ("P2", "REQUEST", "A"), *extra]:
        s.apply(Event(p, EventType.parse(op), l))
    return s


def test_abort_breaks_two_process_deadlock():
    s = deadlocked()
    rm = RecoveryManager(s)
    result = rm.abort_process("P1")
    assert result.cycles_before == [["P1", "P2"]] and result.cycles_after == []
    assert result.resolved and result.victim_was_in_cycle
    assert result.released_locks == ["A"]
    # P1's lock A is handed to waiting P2; P2 is running again
    assert s.owner_of("A") == "P2" and s.blocked_processes() == []
    assert find_cycles(build_wait_for_graph(s)) == []


def test_recovery_records_history_and_before_after():
    s = deadlocked()
    n = len(s.history)
    result = RecoveryManager(s).abort_process("P2")
    ops = [e.operation for e in s.history[n:]]
    assert ops == ["ABORT", "GRANT"]
    assert result.before["processes"]["P2"]["status"] == "BLOCKED"
    assert result.before["processes"]["P1"]["status"] == "BLOCKED"
    assert result.after["processes"]["P2"]["status"] == "ABORTED"
    assert result.after["processes"]["P1"]["status"] == "RUNNING"
    assert any("aborted" in c for c in result.changes)


def test_auto_recover_picks_victim_with_fewest_locks():
    s = deadlocked()
    rm = RecoveryManager(s)
    victim, reason = rm.suggest_victim()
    assert victim == "P1" and "fewest locks" in reason  # tie on 1 lock -> name order
    assert rm.auto_recover().resolved


def test_auto_recover_without_deadlock_is_an_error():
    s = LockState()
    s.apply(Event("P1", EventType.ACQUIRE, "A"))
    rm = RecoveryManager(s)
    assert rm.suggest_victim() is None
    with pytest.raises(SimulationError, match="no deadlock"):
        rm.auto_recover()


def test_abort_bystander_does_not_resolve_deadlock():
    s = deadlocked()
    s.apply(Event("P3", EventType.ACQUIRE, "C"))
    result = RecoveryManager(s).abort_process("P3")
    assert not result.victim_was_in_cycle and not result.resolved


def test_abort_twice_and_unknown_rejected():
    rm = RecoveryManager(deadlocked())
    rm.abort_process("P1")
    with pytest.raises(SimulationError, match="already been aborted"):
        rm.abort_process("P1")
    with pytest.raises(SimulationError, match="Unknown process"):
        rm.abort_process("P9")
    assert rm.candidates() == ["P2"]
    assert len(rm.log) == 1


def test_three_process_recovery_chain():
    s = LockState()
    for p, op, l in [("P1", "ACQUIRE", "A"), ("P2", "ACQUIRE", "B"), ("P3", "ACQUIRE", "C"),
                     ("P1", "REQUEST", "B"), ("P2", "REQUEST", "C"), ("P3", "REQUEST", "A")]:
        s.apply(Event(p, EventType.parse(op), l))
    result = RecoveryManager(s).abort_process("P3")   # C goes to P2, so P2 runs again
    assert result.resolved
    assert s.owner_of("C") == "P2" and s.owner_of("A") == "P1"
    assert s.status_of("P2").value == "RUNNING"
    assert s.status_of("P1").value == "BLOCKED"       # still waits for B (held by running P2)


def test_result_serialises():
    import json
    result = RecoveryManager(deadlocked()).auto_recover()
    json.dumps(result.to_dict())
