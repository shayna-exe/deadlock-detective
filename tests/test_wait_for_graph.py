from simulator import Event, EventType, LockState, build_wait_for_graph, graph_to_dict


def run(events, **kw):
    s = LockState(**kw)
    for p, op, l in events:
        s.apply(Event(p, EventType.parse(op), l))
    return s


def test_two_process_edges_keep_lock_identity():
    s = run([("P1", "ACQUIRE", "A"), ("P2", "ACQUIRE", "B"),
             ("P1", "REQUEST", "B"), ("P2", "REQUEST", "A")])
    g = build_wait_for_graph(s)
    assert set(g.edges) == {("P1", "P2"), ("P2", "P1")}
    assert g.edges["P1", "P2"]["lock"] == "B"   # P1 waits for B held by P2
    assert g.edges["P2", "P1"]["lock"] == "A"


def test_no_edges_when_nobody_waits():
    g = build_wait_for_graph(run([("P1", "ACQUIRE", "A"), ("P2", "ACQUIRE", "B")]))
    assert set(g.nodes) == {"P1", "P2"} and g.number_of_edges() == 0


def test_waiting_edge_points_to_holder_only():
    g = build_wait_for_graph(run([("P1", "ACQUIRE", "A"), ("P2", "REQUEST", "A")]))
    assert list(g.edges(data="lock")) == [("P2", "P1", "A")]


def test_edge_disappears_after_release():
    s = run([("P1", "ACQUIRE", "A"), ("P2", "REQUEST", "A"), ("P1", "RELEASE", "A")])
    assert build_wait_for_graph(s).number_of_edges() == 0


def test_graph_to_dict_is_plain_data():
    s = run([("P1", "ACQUIRE", "A"), ("P2", "REQUEST", "A")])
    d = graph_to_dict(build_wait_for_graph(s))
    assert d["edges"] == [{"from": "P2", "to": "P1", "lock": "A"}]
    assert {n["process"] for n in d["nodes"]} == {"P1", "P2"}
