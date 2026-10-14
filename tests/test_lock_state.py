import pytest

from simulator import Event, EventType, LockState, ProcessStatus, SimulationError


def ev(p, op, l):
    return Event(p, EventType.parse(op), l)


def test_valid_acquire():
    s = LockState()
    entries = s.apply(ev("P1", "ACQUIRE", "A"))
    assert s.owner_of("A") == "P1"
    assert entries[0].result == "ACQUIRED" and not entries[0].blocked


def test_request_on_free_lock_acquires():
    s = LockState()
    s.apply(ev("P1", "REQUEST", "A"))
    assert s.owner_of("A") == "P1"


def test_request_on_occupied_lock_blocks():
    s = LockState()
    s.apply(ev("P1", "ACQUIRE", "A"))
    entries = s.apply(ev("P2", "REQUEST", "A"))
    assert entries[0].blocked and entries[0].result == "BLOCKED"
    assert s.owner_of("A") == "P1"            # P2 did NOT get the lock
    assert s.status_of("P2") is ProcessStatus.BLOCKED
    assert s.waiting_for("P2") == "A"
    assert s.blocked_processes() == ["P2"]


def test_release_frees_lock():
    s = LockState()
    s.apply(ev("P1", "ACQUIRE", "A"))
    s.apply(ev("P1", "RELEASE", "A"))
    assert s.owner_of("A") is None


def test_release_hands_lock_to_waiter_fifo():
    s = LockState()
    s.apply(ev("P1", "ACQUIRE", "A"))
    s.apply(ev("P2", "REQUEST", "A"))
    s.apply(ev("P3", "REQUEST", "A"))
    entries = s.apply(ev("P1", "RELEASE", "A"))
    assert [e.operation for e in entries] == ["RELEASE", "GRANT"]
    assert s.owner_of("A") == "P2"            # first in the queue
    assert s.status_of("P2") is ProcessStatus.RUNNING
    assert s.queue_of("A") == ["P3"]
    assert s.status_of("P3") is ProcessStatus.BLOCKED


@pytest.mark.parametrize("setup,event,fragment", [
    ([], ("P1", "RELEASE", "A"), "free"),                                   # release unheld lock
    ([("P1", "ACQUIRE", "A")], ("P2", "RELEASE", "A"), "held by P1"),       # release other's lock
    ([("P1", "ACQUIRE", "A")], ("P2", "ACQUIRE", "A"), "already held"),     # acquire held lock
    ([("P1", "ACQUIRE", "A")], ("P1", "REQUEST", "A"), "not re-entrant"),   # self request
    ([("P1", "ACQUIRE", "A")], ("P1", "ACQUIRE", "A"), "not re-entrant"),
    ([("P1", "ACQUIRE", "A"), ("P2", "REQUEST", "A")], ("P2", "ACQUIRE", "B"), "blocked"),
])
def test_invalid_events_rejected_without_changing_state(setup, event, fragment):
    s = LockState()
    for e in setup:
        s.apply(ev(*e))
    before, version, n = s.snapshot(), s.version, len(s.history)
    with pytest.raises(SimulationError, match=fragment):
        s.apply(ev(*event))
    assert s.snapshot() == before and s.version == version and len(s.history) == n


def test_unknown_operation_rejected():
    with pytest.raises(SimulationError, match="Unknown operation"):
        EventType.parse("STEAL")
    with pytest.raises(SimulationError, match="missing"):
        Event.from_dict({"process": "P1", "op": "ACQUIRE"})


def test_strict_mode_rejects_undeclared_names():
    s = LockState(["P1"], ["A"], strict=True)
    with pytest.raises(SimulationError, match="Unknown process"):
        s.apply(ev("P9", "ACQUIRE", "A"))
    with pytest.raises(SimulationError, match="Unknown lock"):
        s.apply(ev("P1", "ACQUIRE", "Z"))


def test_history_numbering_and_messages():
    s = LockState()
    s.apply(ev("P1", "ACQUIRE", "A"))
    s.apply(ev("P2", "REQUEST", "A"))
    assert [e.step for e in s.history] == [1, 2]
    assert all(e.message for e in s.history)


def test_abort_releases_locks_and_grants_waiters():
    s = LockState()
    s.apply(ev("P1", "ACQUIRE", "A"))
    s.apply(ev("P1", "ACQUIRE", "B"))
    s.apply(ev("P2", "REQUEST", "A"))
    s.apply(ev("P3", "REQUEST", "B"))
    entries = s.abort_process("P1")
    assert s.status_of("P1") is ProcessStatus.ABORTED
    assert s.owner_of("A") == "P2" and s.owner_of("B") == "P3"
    assert s.blocked_processes() == []
    assert [e.operation for e in entries] == ["ABORT", "GRANT", "GRANT"]
    with pytest.raises(SimulationError, match="aborted"):
        s.apply(ev("P1", "RELEASE", "A"))
    with pytest.raises(SimulationError, match="already been aborted"):
        s.abort_process("P1")


def test_abort_blocked_process_leaves_wait_queue():
    s = LockState()
    s.apply(ev("P1", "ACQUIRE", "A"))
    s.apply(ev("P2", "REQUEST", "A"))
    s.abort_process("P2")
    assert s.queue_of("A") == [] and s.owner_of("A") == "P1"
