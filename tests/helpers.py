"""Builders for synthetic (mocked) measurements used by the recommendation tests."""
from process_monitor.activity_tracker import ActivityTracker
from process_monitor.models import MB, ProcessSample
from process_monitor.settings import MonitorSettings

T0 = 1_700_000_000.0


def sample(pid=500, name="notes.exe", t=T0, cpu=0.2, rss_mb=300.0, ready=True, create=1000.0,
           access="ok", exe="C:/Apps/notes.exe", ppid=100, status="sleeping", nice=0,
           user=2.0, system=1.0, missing=()):
    return ProcessSample(
        pid=pid, name=name, sampled_at=t, ppid=ppid, exe=exe, status=status, create_time=create,
        cpu_percent=cpu if ready else None, cpu_percent_per_core=None if not ready else (cpu or 0) * 4,
        cpu_ready=ready, cpu_time_user_s=user, cpu_time_system_s=system, rss_bytes=int(rss_mb * MB),
        mem_percent=rss_mb / 16384 * 100, num_threads=3, nice=nice, access=access, missing=tuple(missing))


def small_settings(**changes):
    """Short windows so tests need few samples; interval 1 s."""
    base = dict(sample_interval_s=1.0, min_samples_for_analysis=3, idle_min_seconds=10.0,
                close_min_seconds=20.0, idle_min_memory_mb=100.0, close_min_memory_mb=200.0,
                high_cpu_min_seconds=5.0, lower_priority_min_seconds=10.0, growth_min_samples=5,
                growth_min_mb=100.0)
    base.update(changes)
    return MonitorSettings(**base).validate()


def feed(tracker: ActivityTracker, cpus, rss_mb=300.0, step=1.0, **kw):
    """Record one sample per cpu value (1 s apart) and return the LAST sample."""
    last = None
    for i, c in enumerate(cpus):
        r = rss_mb[i] if isinstance(rss_mb, (list, tuple)) else rss_mb
        last = sample(t=T0 + i * step, cpu=c, rss_mb=r, **kw)
        tracker.record([last], None)
    return last
