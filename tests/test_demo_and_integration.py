import json
from pathlib import Path

from lab.demo import DEMO_SCENARIO, GuidedDemo
from services import AppServices
from session import SimulationSession
from simulator import load_scenarios
from tests.fakes import make_fake_psutil

DATA = Path(__file__).resolve().parent.parent / "data" / "scenarios.json"


def test_guided_demo_walks_the_whole_workflow(tmp_path):
    session = SimulationSession(load_scenarios(DATA))
    svc = AppServices(session, settings_path=tmp_path / "s.json", psutil_module=make_fake_psutil())
    demo = GuidedDemo(session, svc.export_report, tmp_path / "demo.json")
    titles = []
    step = demo.start()
    titles.append(step.title)
    while not demo.finished:
        step = demo.advance()
        titles.append(step.title)
    assert titles[0].startswith("1.") and titles[-1].startswith("9.") and step.finished
    assert sum(t.startswith("2.") for t in titles) == 4                 # one step per scripted event
    for n in "345678":
        assert any(t.startswith(n + ".") for t in titles)
    assert session.scenario.name == DEMO_SCENARIO
    assert not session.last_detection.deadlock                           # verified
    data = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    assert data["incident"]["status"] == "resolved" and data["final_cycle_detection"]["deadlock"] is False


def test_demo_can_restart_and_stop():
    session = SimulationSession(load_scenarios(DATA))
    demo = GuidedDemo(session)
    demo.start(); demo.advance()
    demo.stop()
    assert not demo.running
    assert demo.start().title.startswith("1.") and session.position == 0


def test_monitoring_error_in_one_process_never_breaks_deadlock_detection(tmp_path):
    ps = make_fake_psutil()
    ps.fail_listing = True
    session = SimulationSession(load_scenarios(DATA))
    svc = AppServices(session, settings_path=tmp_path / "s.json", psutil_module=ps)
    svc.monitoring.sample_once()
    session.load("Three-process deadlock"); session.run_all()
    assert session.detect().deadlock
    inc = svc.incidents.latest()
    assert inc.telemetry["available"] is True and inc.telemetry["collection_errors"]


def test_psutil_missing_is_handled_gracefully(tmp_path):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *a, **k)

    builtins.__import__ = fake_import
    try:
        session = SimulationSession(load_scenarios(DATA))
        svc = AppServices(session, settings_path=tmp_path / "s.json")
    finally:
        builtins.__import__ = real_import
    assert svc.monitoring is None and "psutil" in svc.monitoring_error
    session.load("Two-process deadlock"); session.run_all()
    assert session.detect().deadlock
    assert svc.full_report()["real_process_telemetry"]["available"] is False
    assert svc.shutdown() == []


def test_shutdown_stops_worker_and_lists_suspended_processes(tmp_path):
    ps = make_fake_psutil()
    ps.add(10, name="a.exe")
    svc = AppServices(SimulationSession(load_scenarios(DATA)), settings_path=tmp_path / "s.json",
                      psutil_module=ps, own_pids={99999})
    svc.monitoring.start()
    snap = None
    svc.monitoring.sample_once(); snap = svc.monitoring.sample_once()
    svc.execute_action(snap.assessments[0].sample, "suspend", True)
    assert svc.shutdown() == [(10, "a.exe")] and not svc.monitoring.is_running()


def test_existing_report_format_is_unchanged_by_the_new_features():
    session = SimulationSession(load_scenarios(DATA))
    session.load("Two-process deadlock"); session.run_all()
    legacy = session.report()
    assert "schema_version" not in legacy and "timestamp" not in json.dumps(legacy).lower()
