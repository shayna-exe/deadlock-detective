from detector import LockOrderAnalyzer, find_cycles
from diagnosis import CONFIRMED, RISK, STATUS_DEADLOCK, STATUS_NONE, explain, recommend
from simulator import Event, EventType, LockState, build_wait_for_graph


def run(events):
    s = LockState()
    for p, op, l in events:
        s.apply(Event(p, EventType.parse(op), l))
    return s


def diagnose(state):
    g = build_wait_for_graph(state)
    cycles = find_cycles(g)
    warnings = LockOrderAnalyzer().analyze(state.history)
    return g, cycles, warnings, explain(state, g, cycles, warnings)


TWO = [("P1", "ACQUIRE", "A"), ("P2", "ACQUIRE", "B"), ("P1", "REQUEST", "B"), ("P2", "REQUEST", "A")]


def test_two_process_diagnosis_matches_state():
    g, cycles, w, d = diagnose(run(TWO))
    text = "\n".join(d.explanation)
    assert d.status == STATUS_DEADLOCK and d.deadlock
    assert "P1 → P2 → P1" in text
    assert "P1 holds lock A and is waiting for lock B, which is held by P2" in text
    assert "P2 holds lock B and is waiting for lock A, which is held by P1" in text
    assert "loop closed at step 4 when P2 requested lock A" in text
    assert "cannot be taken away" in text
    assert "Lock A is held by P1." in d.ownership


def test_explanation_is_generated_not_hardcoded():
    state = run([("X", "ACQUIRE", "L1"), ("Y", "ACQUIRE", "L2"), ("Z", "ACQUIRE", "L3"),
                 ("X", "REQUEST", "L2"), ("Y", "REQUEST", "L3"), ("Z", "REQUEST", "L1")])
    d = diagnose(state)[3]
    text = "\n".join(d.explanation)
    assert "X → Y → Z → X" in text and "3 processes, 3 locks" in text
    assert "P1" not in text


def test_no_deadlock_reported_explicitly():
    d = diagnose(run([("P1", "ACQUIRE", "A"), ("P1", "RELEASE", "A")]))[3]
    assert d.status == STATUS_NONE
    assert "No current deadlock detected" in d.headline


def test_waiting_without_cycle_is_not_a_deadlock():
    d = diagnose(run([("P1", "ACQUIRE", "A"), ("P2", "REQUEST", "A")]))[3]
    assert d.status == STATUS_NONE
    assert "Waiting alone is not a deadlock" in " ".join(d.explanation)
    assert d.waiting == ["P2 is waiting for lock A, held by P1."]


def test_process_stuck_behind_cycle_is_mentioned():
    state = run(TWO[:2] + [("P3", "ACQUIRE", "C"), ("P1", "REQUEST", "B"), ("P2", "REQUEST", "A")])
    state.apply(Event("P3", EventType.REQUEST, "A"))
    d = diagnose(state)[3]
    assert "P3 is not part of a cycle but is stuck behind one" in "\n".join(d.explanation)


def test_lock_order_risk_separate_from_deadlock():
    state = run([("P1", "ACQUIRE", "A"), ("P1", "ACQUIRE", "B"), ("P1", "RELEASE", "B"),
                 ("P1", "RELEASE", "A"), ("P2", "ACQUIRE", "B"), ("P2", "ACQUIRE", "A")])
    g, cycles, warnings, d = diagnose(state)
    assert d.status == STATUS_NONE                   # no current deadlock ...
    assert len(warnings) == 1 and d.lock_order_notes  # ... but a historical risk
    assert "not proof of a current deadlock" in d.lock_order_notes[0]
    recs = recommend(g, cycles, warnings)
    assert any(r.category == RISK for r in recs)
    assert not any(r.category == CONFIRMED for r in recs)


def test_recommendations_for_confirmed_deadlock_name_the_locks():
    g, cycles, w, _ = diagnose(run(TWO))
    recs = recommend(g, cycles, w)
    confirmed = [r.text for r in recs if r.category == CONFIRMED]
    assert any("A before B" in t for t in confirmed)
    assert any("consistent global order" in r.text for r in recs)


def test_recommendation_when_everything_is_fine():
    g, cycles, w, _ = diagnose(run([("P1", "ACQUIRE", "A")]))
    recs = recommend(g, cycles, w)
    assert len(recs) == 1 and "No action needed" in recs[0].text


# ------------------------------------------------------- lock-order analyzer
def test_lock_order_consistent_order_has_no_warning():
    state = run([("P1", "ACQUIRE", "A"), ("P1", "ACQUIRE", "B"), ("P1", "RELEASE", "B"),
                 ("P1", "RELEASE", "A"), ("P2", "ACQUIRE", "A"), ("P2", "ACQUIRE", "B")])
    assert LockOrderAnalyzer().analyze(state.history) == []


def test_lock_order_conflict_details():
    state = run([("P1", "ACQUIRE", "A"), ("P1", "ACQUIRE", "B"), ("P1", "RELEASE", "B"),
                 ("P1", "RELEASE", "A"), ("P2", "ACQUIRE", "B"), ("P2", "ACQUIRE", "A")])
    (w,) = LockOrderAnalyzer().analyze(state.history)
    assert w.locks == ("A", "B")
    assert (w.first.process, w.first.step) == ("P1", 2)
    assert (w.second.process, w.second.step) == ("P2", 6)


def test_lock_order_ignores_locks_already_released():
    state = run([("P1", "ACQUIRE", "A"), ("P1", "RELEASE", "A"), ("P1", "ACQUIRE", "B"),
                 ("P1", "RELEASE", "B"), ("P2", "ACQUIRE", "B"), ("P2", "RELEASE", "B"),
                 ("P2", "ACQUIRE", "A")])
    assert LockOrderAnalyzer().analyze(state.history) == []


def test_lock_order_counts_blocked_attempts():
    # Deadlock scenario: both opposite orders are observed at the REQUEST attempts.
    assert len(LockOrderAnalyzer().analyze(run(TWO).history)) == 1
