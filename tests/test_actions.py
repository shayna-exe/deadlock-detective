"""Management-action safety tests.  A fake psutil is used: no real process is touched."""
from process_monitor.actions import (DENIED, FAILED, FORCE_KILL, GONE, LOWER_PRIORITY, OK, REFUSED, RESUME,
                                     SUSPEND, TERMINATE, TIMEOUT, UNVERIFIED, ProcessController)
from process_monitor.models import ProcessSample
from process_monitor.monitor import ProcessMonitor
from tests.fakes import make_fake_psutil
from tests.helpers import small_settings


def setup(platform="linux", **proc_kw):
    ps = make_fake_psutil()
    proc = ps.add(500, name="notes.exe", create_time=1000.0, exe="/home/u/notes", **proc_kw)
    ctl = ProcessController(small_settings(), ps, own_pids={99999}, platform=platform)
    mon = ProcessMonitor(ps)
    mon.collect()
    sample = mon.collect().samples[0]
    return ps, proc, ctl, sample


def test_nothing_happens_without_explicit_confirmation():
    ps, proc, ctl, s = setup()
    rec = ctl.execute(s, TERMINATE, confirmed=False)
    assert rec.outcome == REFUSED and proc.calls == [] and rec.user_confirmed is False


def test_confirmed_terminate_succeeds_and_is_logged():
    ps, proc, ctl, s = setup()
    rec = ctl.execute(s, TERMINATE, confirmed=True)
    assert rec.outcome == OK and proc.calls == ["terminate", "wait"]
    assert ctl.log[-1] is rec and rec.pid == 500 and rec.name == "notes.exe"
    assert "cmdline" not in rec.to_dict() and "exe" not in rec.to_dict()


def test_protected_process_cannot_be_acted_on_at_all():
    ps = make_fake_psutil()
    proc = ps.add(4, name="System")
    ps.add(600, name="lsass.exe", exe="C:/Windows/System32/lsass.exe")
    ctl = ProcessController(small_settings(), ps, own_pids={99999}, platform="win32")
    mon = ProcessMonitor(ps); mon.collect()
    for s in mon.collect().samples:
        avail = ctl.availability(s)
        assert not any(a.available for a in avail.values())
        for op in (TERMINATE, FORCE_KILL, SUSPEND, LOWER_PRIORITY):
            assert ctl.execute(s, op, True).outcome == REFUSED
    assert proc.calls == []


def test_own_process_is_protected():
    ps = make_fake_psutil()
    me = ps.add(99999, name="python.exe")
    ctl = ProcessController(small_settings(), ps, own_pids={99999})
    mon = ProcessMonitor(ps); mon.collect()
    s = mon.collect().samples[0]
    assert ctl.execute(s, TERMINATE, True).outcome == REFUSED and me.calls == []


def test_pid_reuse_is_caught_before_acting():
    ps, proc, ctl, s = setup()
    ps.registry.clear()
    impostor = ps.add(500, name="notes.exe", create_time=5000.0)     # same PID and name, new process
    rec = ctl.execute(s, TERMINATE, True)
    assert rec.outcome == REFUSED and "different process" in rec.detail and impostor.calls == []


def test_name_change_is_caught_before_acting():
    ps, proc, ctl, s = setup()
    proc.name_ = "other.exe"
    assert ctl.execute(s, TERMINATE, True).outcome == REFUSED and proc.calls == []


def test_process_that_already_exited_is_reported_honestly():
    ps, proc, ctl, s = setup()
    proc.gone = True
    rec = ctl.execute(s, TERMINATE, True)
    assert rec.outcome == GONE and "already exited" in rec.detail


def test_permission_denied_is_reported_not_hidden():
    ps, proc, ctl, s = setup()
    proc.terminate = lambda: (_ for _ in ()).throw(ps.AccessDenied(500))
    assert ctl.execute(s, TERMINATE, True).outcome == DENIED


def test_timeout_then_force_kill_is_only_offered_afterwards():
    ps, proc, ctl, s = setup()
    proc.wait_times_out = True
    assert ctl.availability(s)[FORCE_KILL].available is False        # graceful comes first
    assert ctl.execute(s, FORCE_KILL, True).outcome == REFUSED
    rec = ctl.execute(s, TERMINATE, True)
    assert rec.outcome == TIMEOUT
    assert ctl.availability(s)[FORCE_KILL].available is True
    assert ctl.execute(s, FORCE_KILL, True).outcome == OK and "kill" in proc.calls


def test_force_kill_never_offered_on_windows_and_can_be_disabled():
    ps, proc, ctl, s = setup(platform="win32")
    proc.wait_times_out = True
    ctl.execute(s, TERMINATE, True)
    assert ctl.availability(s)[FORCE_KILL].available is False
    ps2, proc2, ctl2, s2 = setup()
    proc2.wait_times_out = True
    ctl2.settings = small_settings(allow_force_kill=False)
    ctl2.execute(s2, TERMINATE, True)
    assert ctl2.availability(s2)[FORCE_KILL].available is False


def test_windows_confirmation_text_warns_that_terminate_is_immediate():
    ps, proc, ctl, s = setup(platform="win32")
    text = ctl.describe(s, TERMINATE)
    assert "notes.exe" in text and "500" in text and "IMMEDIATELY" in text and "REAL" in text


def test_lower_priority_is_verified():
    ps, proc, ctl, s = setup()
    rec = ctl.execute(s, LOWER_PRIORITY, True)
    assert rec.outcome == OK and proc.nice_ == 10
    ps, proc, ctl, s = setup(platform="win32")
    assert ctl.execute(s, LOWER_PRIORITY, True).outcome == OK and proc.nice_ == 16384


def test_unverifiable_priority_change_is_not_called_success():
    ps, proc, ctl, s = setup()
    proc.nice = lambda value=None: 0       # system ignores the change
    assert ctl.execute(s, LOWER_PRIORITY, True).outcome == UNVERIFIED


def test_suspend_then_resume_and_exit_warning_list():
    ps, proc, ctl, s = setup()
    assert ctl.availability(s)[RESUME].available is False
    assert ctl.execute(s, SUSPEND, True).outcome == OK
    assert ctl.suspended_processes() == [(500, "notes.exe")]
    stopped = ProcessMonitor(ps).collect().samples[0]
    assert ctl.availability(stopped)[RESUME].available and not ctl.availability(stopped)[SUSPEND].available
    assert ctl.execute(stopped, RESUME, True).outcome == OK
    assert ctl.suspended_processes() == []


def test_unsupported_suspend_is_unavailable():
    ps, proc, ctl, s = setup()
    del ps.Process.suspend
    assert ctl.availability(s)[SUSPEND].available is False


def test_unreadable_or_identity_unknown_process_fails_safe():
    ps, proc, ctl, s = setup()
    no_time = ProcessSample(pid=500, name="notes.exe", sampled_at=1.0, create_time=None, access="partial")
    assert not ctl.availability(no_time)[TERMINATE].available
    denied = ProcessSample(pid=500, name="notes.exe", sampled_at=1.0, create_time=1000.0, access="denied")
    assert ctl.execute(denied, TERMINATE, True).outcome == REFUSED


def test_unexpected_failure_is_reported_as_failed_not_raised():
    ps, proc, ctl, s = setup()
    proc.terminate = lambda: (_ for _ in ()).throw(RuntimeError("weird"))
    assert ctl.execute(s, TERMINATE, True).outcome == FAILED


def test_unknown_operation_is_refused():
    ps, proc, ctl, s = setup()
    assert ctl.execute(s, "format_disk", True).outcome == REFUSED and proc.calls == []
