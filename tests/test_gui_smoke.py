"""GUI smoke tests. They need Tkinter and a display (skipped otherwise)."""
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "data" / "scenarios.json"


def test_layout_and_cycle_edges_are_pure_functions():
    pytest.importorskip("tkinter")
    from ui.graph_view import circular_layout, cycle_edge_set
    assert circular_layout([], 400, 300) == {}
    assert circular_layout(["P1"], 400, 300)["P1"][0] == 200
    pos = circular_layout(["P1", "P2", "P3"], 400, 300)
    assert len(set(pos.values())) == 3
    assert cycle_edge_set([["P1", "P2", "P3"]]) == {("P1", "P2"), ("P2", "P3"), ("P3", "P1")}
    assert cycle_edge_set([]) == set()


@pytest.fixture
def app():
    tk = pytest.importorskip("tkinter")
    from session import SimulationSession
    from simulator import load_scenarios
    from ui.dashboard import Dashboard
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display available: {exc}")
    root.withdraw()
    dash = Dashboard(root, SimulationSession(load_scenarios(DATA)))
    yield dash
    root.destroy()


def test_dashboard_runs_every_scenario(app, tmp_path):
    for name in app.session.scenario_names:
        app.reload(name)
        while app.session.has_next:
            app.on_step()
        app.on_detect()
        app.root.update()
        expect_deadlock = "deadlock" in name.lower() and "order" not in name.lower()
        status = app.stat_vars["Deadlock status"].get()
        assert status == ("DEADLOCK" if expect_deadlock else "None detected")
        assert len(app.tree.get_children()) == len(app.session.state.history)
        app.session.write_report(tmp_path / "r.json")


def test_dashboard_recovery_flow(app):
    app.reload("Two-process deadlock")
    for _ in range(4):
        app.on_step()
    app.on_detect()
    assert app.stat_vars["Deadlock status"].get() == "DEADLOCK"
    app.on_auto_recover()
    assert app.stat_vars["Deadlock status"].get() == "None detected"
    assert "Action 1" in app.recovery_text.text.get("1.0", "end")
    assert app.stat_vars["Blocked processes"].get() == "0"


def test_dashboard_run_all_uses_event_loop(app):
    import ui.dashboard as d
    d.RUN_DELAY_MS = 5
    app.reload("Three-process deadlock")
    app.on_run_all()
    for _ in range(200):
        app.root.update()
        app.root.after(5)
        if not app.session.has_next:
            break
    assert not app.session.has_next and not app._running
