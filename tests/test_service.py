import threading
import time

from process_monitor.service import MonitoringService
from tests.fakes import make_fake_psutil
from tests.helpers import small_settings


def make_service(**kw):
    ps = make_fake_psutil()
    ps.add(10, name="a.exe", cpu=(0.0, 2.0))
    ps.add(11, name="b.exe", cpu=(0.0, 40.0))
    return ps, MonitoringService(small_settings(**kw), ps, own_pids={99999})


def test_sample_once_produces_snapshot_with_assessments():
    ps, svc = make_service()
    first = svc.sample_once()
    assert first.warming_up and all(a.category == "Monitoring Unavailable" for a in first.assessments)
    second = svc.sample_once()
    assert second.sequence == 2 and len(second.assessments) == 2
    assert second.by_cpu(1)[0].name == "b.exe"


def test_worker_starts_once_and_stops_cleanly():
    ps, svc = make_service(sample_interval_s=0.5)
    assert svc.start() is True
    assert svc.start() is False                       # no duplicate thread
    threads = [t for t in threading.enumerate() if t.name == "deadlock-detective-monitor"]
    assert len(threads) == 1
    time.sleep(0.2)
    assert svc.stop(timeout=3) is True and not svc.is_running()
    assert not [t for t in threading.enumerate() if t.name == "deadlock-detective-monitor"]
    assert svc.latest() is not None


def test_worker_can_be_restarted_after_stop():
    ps, svc = make_service(sample_interval_s=0.5)
    svc.start(); svc.stop()
    assert svc.start() is True
    svc.stop()


def test_listing_error_does_not_crash_worker():
    ps, svc = make_service(sample_interval_s=0.5)
    ps.fail_listing = True
    snap = svc.sample_once()
    assert snap.assessments == [] and snap.errors and svc.last_error
    svc.start(); time.sleep(0.2)
    assert svc.is_running()
    svc.stop()


def test_history_stays_bounded_over_many_passes():
    ps, svc = make_service(max_samples_per_process=10)
    for _ in range(60):
        svc.sample_once()
    key = svc.tracker.tracked()[0]
    assert len(svc.tracker.points(key)) == 10


def test_clear_history_resets_everything():
    ps, svc = make_service()
    svc.sample_once(); svc.sample_once()
    svc.clear_history()
    assert svc.latest() is None and svc.tracker.tracked() == []
    assert svc.sample_once().warming_up is True


def test_apply_settings_changes_rules_and_retention():
    ps, svc = make_service()
    svc.apply_settings(small_settings(max_samples_per_process=10, idle_cpu_percent=7.0))
    assert svc.engine.settings.idle_cpu_percent == 7.0 and svc.tracker.settings.max_samples_per_process == 10


def test_telemetry_dict_is_labelled_context_and_has_no_private_fields():
    ps, svc = make_service()
    svc.sample_once()
    d = svc.sample_once().telemetry_dict()
    assert d["available"] is True and "does NOT show" in d["disclaimer"]
    assert d["top_cpu_consumers"][0]["name"] == "b.exe"
    text = str(d)
    assert "cmdline" not in text and "username" not in text
