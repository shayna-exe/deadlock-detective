"""Collector tests using a fake psutil (no real process is read)."""
from process_monitor.monitor import ProcessMonitor

from tests.fakes import MB, make_fake_psutil


def make(**kw):
    ps = make_fake_psutil(**kw)
    return ps, ProcessMonitor(ps)


def test_collects_basic_fields_and_never_exports_command_line():
    ps, mon = make()
    ps.add(10, name="editor.exe", rss=250 * MB, user=3.0, system=1.5, cpu=(0.0, 40.0))
    s = mon.collect().samples[0]
    assert (s.pid, s.name, s.ppid, s.status) == (10, "editor.exe", 100, "running")
    assert s.rss_bytes == 250 * MB and s.rss_mb == 250.0
    assert s.cpu_time_user_s == 3.0 and s.cpu_time_system_s == 1.5
    assert s.cpu_time_total_s == 4.5                  # cumulative CPU seconds, not a percentage
    assert s.num_threads == 4 and s.access == "ok"
    d = s.to_dict()
    assert "cmdline" not in d and "exe" not in d and "username" not in d


def test_first_cpu_reading_is_not_reported_as_a_measurement():
    ps, mon = make()
    ps.add(10, cpu=(0.0, 80.0))
    first = mon.collect()
    assert first.warming_up is True
    assert first.samples[0].cpu_percent is None and first.samples[0].cpu_ready is False
    second = mon.collect()
    assert second.warming_up is False
    assert second.samples[0].cpu_ready is True and second.samples[0].cpu_percent is not None


def test_cpu_percent_is_normalised_by_core_count_and_capped():
    ps, mon = make(cpu_count=4)
    ps.add(10, cpu=(0.0, 200.0))          # 200 % of one core on a 4-core machine = 50 % overall
    mon.collect()
    s = mon.collect().samples[0]
    assert s.cpu_percent_per_core == 200.0 and s.cpu_percent == 50.0
    ps.add(11, cpu=(0.0, 900.0))
    mon.collect()
    assert mon.collect().samples[1].cpu_percent == 100.0


def test_cumulative_cpu_time_is_separate_from_current_percentage():
    ps, mon = make()
    ps.add(10, cpu=(0.0, 0.0), user=100.0, system=20.0)
    mon.collect()
    s = mon.collect().samples[0]
    assert s.cpu_percent == 0.0 and s.cpu_time_total_s == 120.0


def test_inaccessible_attributes_are_recorded_not_fatal():
    ps, mon = make()
    ps.add(10, name="vault.exe", deny=("exe", "cpu_times"))
    ps.add(11, name="ok.exe")
    result = mon.collect()
    by_pid = {s.pid: s for s in result.samples}
    assert by_pid[10].exe is None and by_pid[10].cpu_time_total_s is None
    assert "exe" in by_pid[10].missing and "cpu_times" in by_pid[10].missing
    assert by_pid[10].access == "partial"
    assert by_pid[11].access == "ok"


def test_fully_inaccessible_process_is_marked_denied_and_counted():
    ps, mon = make()
    ps.add(10, name="locked.exe", deny=("cpu_times", "memory", "cpu_percent"))
    result = mon.collect()
    assert result.samples[0].access == "denied" and result.skipped_denied == 1


def test_process_that_exits_during_collection_is_skipped_and_counted():
    ps, mon = make()
    ps.add(10, name="gone.exe", gone=True)
    ps.add(11, name="stays.exe")
    result = mon.collect()
    assert [s.pid for s in result.samples] == [11]
    assert result.skipped_exited == 1


def test_pid_reuse_is_detected_and_not_confused_with_old_process():
    ps, mon = make()
    ps.add(10, name="old.exe", create_time=1000.0, cpu=(0.0, 5.0))
    mon.collect()
    assert mon.collect().samples[0].cpu_ready is True
    ps.registry.clear()
    ps.add(10, name="new.exe", create_time=2000.0, cpu=(0.0, 5.0))   # same PID, new process
    s = mon.collect().samples[0]
    assert s.pid_reused is True
    assert s.cpu_ready is False                    # no baseline for the new process
    assert s.key == (10, 2000.0)


def test_listing_failure_returns_empty_result_with_error_not_exception():
    ps, mon = make()
    ps.fail_listing = True
    result = mon.collect()
    assert result.samples == [] and any("Could not list" in e for e in result.errors)


def test_system_sample_first_cpu_reading_is_none_then_value():
    ps, mon = make()
    ps.add(10)
    first = mon.collect().system
    second = mon.collect().system
    assert first.cpu_percent is None and second.cpu_percent == 12.0
    assert second.mem_percent == 50.0 and second.cpu_count == 4


def test_unexpected_error_in_one_process_does_not_stop_others():
    ps, mon = make()
    bad = ps.add(10, name="bad.exe")
    bad.name = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    ps.add(11, name="good.exe")
    result = mon.collect()
    assert [s.pid for s in result.samples] == [10, 11] or [s.pid for s in result.samples] == [11]
    assert any(s.pid == 11 for s in result.samples)


def test_missing_name_gets_placeholder_and_marker():
    ps, mon = make()
    ps.add(10, deny=("name",))
    s = mon.collect().samples[0]
    assert s.name == "<pid 10>" and "name" in s.missing


def test_reset_makes_next_pass_a_warm_up_again():
    ps, mon = make()
    ps.add(10)
    mon.collect(); mon.collect()
    mon.reset()
    assert mon.collect().warming_up is True
