import csv
import json
from pathlib import Path

import pytest

from incidents import (REPORT_SCHEMA_VERSION, ReportError, build_full_report, unique_path, validate_report,
                       write_json_report)
from process_monitor.exporters import snapshot_to_csv
from services import AppServices
from session import SimulationSession
from simulator import load_scenarios
from tests.fakes import make_fake_psutil
from tests.helpers import small_settings

DATA = Path(__file__).resolve().parent.parent / "data" / "scenarios.json"


def make(tmp_path, with_psutil=True):
    session = SimulationSession(load_scenarios(DATA))
    ps = make_fake_psutil()
    ps.add(10, name="a.exe"); ps.add(11, name="b.exe", cpu=(0.0, 50.0))
    svc = AppServices(session, settings_path=tmp_path / "s.json", psutil_module=ps, own_pids={99999})
    return session, svc, ps


def deadlock(session, name="Two-process deadlock"):
    session.load(name); session.run_all(); return session.detect()


def test_simulator_works_without_any_monitoring():
    session = SimulationSession(load_scenarios(DATA))
    assert deadlock(session).deadlock                      # no AppServices, no psutil at all


def test_incident_opens_on_deadlock_with_unavailable_telemetry(tmp_path):
    session, svc, ps = make(tmp_path)
    deadlock(session)
    inc = svc.incidents.latest()
    assert inc.status == "open" and inc.id.startswith("INC-") and inc.cycles == [["P1", "P2"]]
    assert inc.telemetry["available"] is False and "not running" in inc.telemetry["reason"]
    kinds = [t.kind for t in inc.timeline]
    assert kinds[:4] == ["DETECTED", "DIAGNOSED", "RECOMMENDED", "TELEMETRY"]
    assert session.last_detection.deadlock                # detection unaffected by missing telemetry


def test_no_incident_for_safe_scenarios(tmp_path):
    session, svc, ps = make(tmp_path)
    deadlock(session, "Safe execution")
    assert svc.incidents.latest() is None


def test_incident_includes_real_snapshot_labelled_as_context(tmp_path):
    session, svc, ps = make(tmp_path)
    svc.monitoring.sample_once(); svc.monitoring.sample_once()
    deadlock(session)
    d = svc.incidents.latest().to_dict()
    assert d["real_process_telemetry"]["available"] is True
    assert "does NOT show" in d["real_process_telemetry"]["disclaimer"]
    assert "SIMULATED" in d["simulation_evidence"]["label"]
    assert d["simulation_evidence"]["cycles"] == [["P1", "P2"]]
    assert {p["name"] for p in d["real_process_telemetry"]["top_cpu_consumers"]} == {"a.exe", "b.exe"}
    assert "a.exe" not in json.dumps(d["simulation_evidence"])   # real names never leak into simulation evidence


def test_incident_lifecycle_recovery_and_verification(tmp_path):
    session, svc, ps = make(tmp_path)
    deadlock(session)
    session.auto_recover()
    inc = svc.incidents.latest()
    assert inc.status == "resolved" and inc.verification["deadlock_resolved"] is True
    assert [t.kind for t in inc.timeline][-3:] == ["DECISION", "RECOVERY", "VERIFIED"]
    assert inc.recoveries[0]["victim"] == "P1" and inc.closed_at


def test_bystander_abort_leaves_incident_unresolved_until_a_cycle_member_is_aborted(tmp_path):
    from lab.whatif import build_scenario
    session, svc, ps = make(tmp_path)
    session.add_scenario(build_scenario(
        "With bystander", "", "P1 P2 P3", "A B C",
        "P1 ACQUIRE A\nP2 ACQUIRE B\nP1 REQUEST B\nP2 REQUEST A\nP3 ACQUIRE C"))
    deadlock(session, "With bystander")
    session.abort_process("P3")                            # outside the cycle
    inc = svc.incidents.latest()
    assert inc.status == "deadlock still present" and inc.verification["deadlock_resolved"] is False
    assert svc.incidents.current is inc                    # still open for another attempt
    session.abort_process("P1")
    assert inc.status == "resolved" and len(inc.recoveries) == 2
    assert [t.kind for t in inc.timeline].count("VERIFIED") == 2


def test_simulated_recovery_never_touches_real_processes(tmp_path):
    session, svc, ps = make(tmp_path)
    svc.monitoring.sample_once(); svc.monitoring.sample_once()
    deadlock(session)
    session.auto_recover()
    assert all(p.calls == [] for p in ps.registry.values())
    assert list(svc.controller.log) == []


def test_reset_abandons_open_incident(tmp_path):
    session, svc, ps = make(tmp_path)
    deadlock(session)
    session.reset()
    assert svc.incidents.incidents[-1].status.startswith("abandoned") and svc.incidents.current is None


def test_incident_history_is_bounded(tmp_path):
    session, svc, ps = make(tmp_path)
    svc.incidents._max = 3
    for _ in range(6):
        deadlock(session)
        session.auto_recover()
    assert len(svc.incidents.incidents) == 3


def test_real_action_is_logged_separately_and_labelled(tmp_path):
    session, svc, ps = make(tmp_path)
    svc.monitoring.sample_once(); snap = svc.monitoring.sample_once()
    deadlock(session)
    target = next(a.sample for a in snap.assessments if a.name == "a.exe")
    rec = svc.execute_action(target, "lower_priority", True)
    assert rec.outcome == "success"
    report = svc.full_report()
    assert report["real_process_actions"]["records"][0]["operation"] == "lower_priority"
    assert "unrelated to the simulation" in report["real_process_actions"]["records"][0]["note"]
    assert any(t["source"] == "real-process action" for t in report["incident"]["timeline"])
    assert "REAL" in report["real_process_actions"]["note"]


# ---------------------------------------------------------------- reports
def test_full_report_is_valid_superset_of_legacy_report(tmp_path):
    session, svc, ps = make(tmp_path)
    deadlock(session); session.auto_recover()
    report = svc.full_report()
    assert validate_report(report) == [] and report["schema_version"] == REPORT_SCHEMA_VERSION
    legacy = session.report()
    for key, value in legacy.items():
        assert report[key] == value                      # every legacy key is preserved unchanged
    assert report["final_cycle_detection"] == {"deadlock": False, "cycles": []}
    assert report["before_after"]["cycles_before"] == [["P1", "P2"]] and report["before_after"]["cycles_after"] == []
    assert report["resource_monitoring"]["thresholds_used"]["idle_cpu_percent"] == 1.0
    assert "No command-line" in report["resource_monitoring"]["privacy_note"]


def test_report_without_monitoring_still_valid(tmp_path):
    session = SimulationSession(load_scenarios(DATA))
    svc = AppServices(session, settings_path=tmp_path / "s.json", psutil_module=make_fake_psutil())
    svc.monitoring = None; svc.monitoring_error = "psutil missing"
    deadlock(session)
    report = svc.full_report()
    assert validate_report(report) == [] and report["real_process_telemetry"]["available"] is False
    assert report["resource_monitoring"]["available"] is False


def test_write_json_report_roundtrip_and_never_overwrites(tmp_path):
    session, svc, ps = make(tmp_path)
    deadlock(session)
    first = svc.export_report(tmp_path / "r.json")
    second = svc.export_report(tmp_path / "r.json")
    assert first.name == "r.json" and second.name == "r_2.json"
    assert json.loads(first.read_text(encoding="utf-8"))["schema_version"] == "2.0"
    third = write_json_report(svc.full_report(), tmp_path / "r.json", overwrite=True)
    assert third.name == "r.json"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".tmp_report_")]


def test_write_failure_is_oserror_and_leaves_no_temp_file(tmp_path):
    session, svc, ps = make(tmp_path)
    with pytest.raises(OSError):
        svc.export_report(tmp_path / "missing_dir" / "r.json")


def test_invalid_report_is_rejected_before_writing(tmp_path):
    with pytest.raises(ReportError):
        write_json_report({"nope": 1}, tmp_path / "x.json")
    assert not (tmp_path / "x.json").exists()
    assert "Missing key: scenario" in validate_report({"nope": 1})


def test_unique_path(tmp_path):
    (tmp_path / "a.json").write_text("{}")
    assert unique_path(tmp_path / "a.json").name == "a_2.json"
    assert unique_path(tmp_path / "b.json").name == "b.json"


def test_csv_export_has_no_private_columns(tmp_path):
    session, svc, ps = make(tmp_path)
    with pytest.raises(ValueError):
        svc.export_snapshot_csv(tmp_path / "x.csv")           # nothing sampled yet
    svc.monitoring.sample_once(); svc.monitoring.sample_once()
    path = svc.export_snapshot_csv(tmp_path / "x.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert {r["name"] for r in rows} == {"a.exe", "b.exe"}
    assert not {"exe", "cmdline", "username"} & set(rows[0])
    assert rows[0]["recommendation"]


def test_bad_saved_settings_fall_back_to_defaults_with_warning(tmp_path):
    (tmp_path / "s.json").write_text("{bad", encoding="utf-8")
    svc = AppServices(SimulationSession(load_scenarios(DATA)), settings_path=tmp_path / "s.json",
                      psutil_module=make_fake_psutil())
    assert svc.settings_warning and svc.settings.sample_interval_s == 2.0


def test_settings_can_be_applied_and_saved(tmp_path):
    session, svc, ps = make(tmp_path)
    svc.apply_settings(small_settings(sample_interval_s=4.0), save=True)
    assert svc.monitoring.settings.sample_interval_s == 4.0
    assert json.loads((tmp_path / "s.json").read_text())["sample_interval_s"] == 4.0
