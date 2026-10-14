import networkx as nx

from detector import CycleDetector, cycle_edges, find_cycles, format_cycle
from simulator import Event, EventType, LockState, build_wait_for_graph


def wfg(edges, nodes=()):
    g = nx.DiGraph()
    g.add_nodes_from(nodes)
    for u, v, lock in edges:
        g.add_edge(u, v, lock=lock)
    return g


def test_empty_graph():
    assert find_cycles(nx.DiGraph()) == []


def test_two_process_cycle():
    g = wfg([("P1", "P2", "B"), ("P2", "P1", "A")])
    assert find_cycles(g) == [["P1", "P2"]]
    assert format_cycle(["P1", "P2"]) == "P1 → P2 → P1"
    assert cycle_edges(g, ["P1", "P2"]) == [("P1", "P2", "B"), ("P2", "P1", "A")]


def test_three_process_cycle():
    g = wfg([("P1", "P2", "B"), ("P2", "P3", "C"), ("P3", "P1", "A")])
    assert find_cycles(g) == [["P1", "P2", "P3"]]


def test_cycle_reported_from_any_start_is_canonical():
    g = wfg([("P3", "P1", "A"), ("P1", "P2", "B"), ("P2", "P3", "C")])
    assert find_cycles(g) == [["P1", "P2", "P3"]]


def test_acyclic_chain():
    assert find_cycles(wfg([("P1", "P2", "A"), ("P2", "P3", "B")])) == []


def test_disconnected_components_find_cycle_in_second_component():
    g = wfg([("P1", "P2", "A"), ("P3", "P4", "B"), ("P4", "P3", "C")], nodes=["P5"])
    assert find_cycles(g) == [["P3", "P4"]]


def test_two_independent_cycles():
    g = wfg([("P1", "P2", "A"), ("P2", "P1", "B"), ("P3", "P4", "C"), ("P4", "P3", "D")])
    assert find_cycles(g) == [["P1", "P2"], ["P3", "P4"]]


def test_tail_leading_into_cycle_excluded_from_cycle():
    g = wfg([("P0", "P1", "X"), ("P1", "P2", "A"), ("P2", "P1", "B")])
    assert find_cycles(g) == [["P1", "P2"]]


def test_diamond_without_cycle_is_not_a_false_positive():
    g = wfg([("A", "B", 1), ("A", "C", 2), ("B", "D", 3), ("C", "D", 4)])
    assert find_cycles(g) == []


def test_self_loop_is_a_cycle_of_length_one():
    assert find_cycles(wfg([("P1", "P1", "A")])) == [["P1"]]


def test_detector_does_not_repeat_unchanged_deadlock():
    g = wfg([("P1", "P2", "B"), ("P2", "P1", "A")])
    d = CycleDetector()
    first = d.detect(g)
    assert first.deadlock and first.new_cycles == [["P1", "P2"]]
    second = d.detect(g)
    assert second.deadlock and second.repeated and second.new_cycles == []
    d.detect(wfg([]))                      # cycle disappears ...
    third = d.detect(g)                    # ... and comes back: reported again
    assert third.new_cycles == [["P1", "P2"]]


def test_detection_on_real_simulation_state():
    s = LockState()
    for p, op, l in [("P1", "ACQUIRE", "A"), ("P2", "ACQUIRE", "B"),
                     ("P1", "REQUEST", "B"), ("P2", "REQUEST", "A")]:
        s.apply(Event(p, EventType.parse(op), l))
    assert find_cycles(build_wait_for_graph(s)) == [["P1", "P2"]]
