"""GUI tests for the monitoring tabs.  They need Tkinter and a display (skipped otherwise)."""
from pathlib import Path
import threading

import pytest

from tests.fakes import make_fake_psutil

DATA = Path(__file__).resolve().parent.parent / "data" / "scenarios.json"


@pytest.fixture
def app(tmp_path):
    tk = pytest.importorskip("tkinter")
    from services import AppServices
    from session import SimulationSession
    from simulator import load_scenarios
    from ui.dashboard import Dashboard
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display available: {exc}")
    root.withdraw()
    ps = make_fake_psutil()
    ps.add(10, name="notes.exe", cpu=(0.0, 0.1)); ps.add(11, name="render.exe", cpu=(0.0, 95.0))
    session = SimulationSession(load_scenarios(DATA))
    services = AppServices(session, settings_path=tmp_path / "s.json", psutil_module=ps, own_pids={99999})
    dash = Dashboard(root, session, services)
    yield dash
    services.shutdown()
    try:
        root.destroy()
    except tk.TclError:
        pass


def test_all_tabs_exist_and_monitoring_is_not_started_automatically(app):
    assert set(app.tabs) >= {"overview", "simulator", "live", "recs", "history", "lab", "whatif", "reports",
                             "settings", "guide"}
    assert not app.services.monitoring.is_running()


def test_start_stop_monitoring_from_gui_leaves_no_thread(app):
    app.live.toggle()
    assert app.services.monitoring.is_running()
    app.live.toggle()
    assert not app.services.monitoring.is_running()
    assert not [t for t in threading.enumerate() if t.name == "deadlock-detective-monitor"]


def test_table_search_and_selection_show_explanation(app):
    mon = app.services.monitoring
    mon.sample_once(); mon.sample_once()
    app._poll_monitor()
    assert len(app.live.tree.get_children()) == 2
    app.live.query.set("render")
    app.root.update()
    assert len(app.live.tree.get_children()) == 1
    iid = app.live.tree.get_children()[0]
    app.live.tree.selection_set(iid)
    app.root.update()
    assert "INFORMATION" in app.live.card.info.text.get("1.0", "end")


def test_graph_shows_stale_state_after_detection_then_change(app):
    app.reload("Two-process deadlock")
    for _ in range(4):
        app.on_step()
    app.on_detect()
    assert "CURRENT" in app.graph_view.status_var.get() and "Cycle:" in app.graph_view.cycle_var.get()
    app.on_auto_recover()
    assert app.stat_vars["Deadlock status"].get() == "None detected"


def test_recovery_lab_apply_and_incident_recorded(app):
    app.reload("Two-process deadlock")
    for _ in range(4):
        app.on_step()
    app.on_detect()
    assert app.services.incidents.latest().status == "open"
    app.lab.refresh()
    app.lab.tree.selection_set("P1")
    app.lab.apply()
    assert app.services.incidents.latest().status == "resolved"


def test_shutdown_via_close_stops_worker(app):
    app.live.toggle()
    app.on_close()
    assert not app.services.monitoring.is_running()
