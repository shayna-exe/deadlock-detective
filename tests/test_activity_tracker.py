from process_monitor.activity_tracker import ActivityTracker

from tests.helpers import T0, feed, sample, small_settings


def test_low_activity_window_counts_trailing_low_samples():
    tr = ActivityTracker(small_settings(idle_cpu_percent=1.0))
    last = feed(tr, [50, 40, 0.5, 0.2, 0.1, 0.3])
    w = tr.low_activity(last.key)
    assert w.samples == 4 and w.seconds == 3.0
    assert w.max_cpu == 0.5 and round(w.mean_cpu, 3) == 0.275


def test_a_spike_resets_the_low_activity_window():
    tr = ActivityTracker(small_settings())
    last = feed(tr, [0.1] * 10 + [30.0] + [0.1] * 2)
    assert tr.low_activity(last.key).samples == 2


def test_samples_without_cpu_baseline_do_not_count_as_observations():
    tr = ActivityTracker(small_settings())
    first = sample(t=T0, ready=False)
    tr.record([first], None)
    assert tr.samples_observed(first.key) == 0
    tr.record([sample(t=T0 + 1, cpu=0.1)], None)
    assert tr.samples_observed(first.key) == 1


def test_configurable_idle_threshold_changes_the_result():
    cpus = [3.0] * 6
    strict = ActivityTracker(small_settings(idle_cpu_percent=1.0))
    loose = ActivityTracker(small_settings(idle_cpu_percent=5.0))
    k1, k2 = feed(strict, cpus).key, feed(loose, cpus).key
    assert strict.low_activity(k1).samples == 0 and loose.low_activity(k2).samples == 6


def test_history_per_process_is_bounded():
    tr = ActivityTracker(small_settings(max_samples_per_process=10))
    last = feed(tr, [1.0] * 50)
    assert len(tr.points(last.key)) == 10


def test_system_history_and_timeline_are_bounded():
    from process_monitor.models import SystemSample
    tr = ActivityTracker(small_settings(max_system_samples=10, max_timeline_events=10))
    for i in range(50):
        tr.record([], SystemSample(T0 + i, 1.0, 2.0, 1, 1, 4, 0))
    assert len(tr.system) == 10
    s = sample()
    for i in range(50):
        tr.note_category(s, "Investigate" if i % 2 == 0 else "Consider Closing", "x")
    assert len(tr.timeline) == 10


def test_history_of_exited_processes_is_dropped():
    tr = ActivityTracker(small_settings())
    a = sample(pid=1, t=T0); b = sample(pid=2, t=T0)
    tr.record([a, b], None)
    tr.record([sample(pid=1, t=T0 + 1)], None)
    assert tr.tracked() == [a.key]


def test_reused_pid_starts_fresh_history():
    tr = ActivityTracker(small_settings())
    old = sample(pid=1, create=1000.0, t=T0)
    tr.record([old], None)
    new = sample(pid=1, create=2000.0, t=T0 + 1)
    tr.record([new], None)
    assert tr.tracked() == [new.key] and len(tr.points(new.key)) == 1


def test_top_consumers_use_latest_real_samples():
    tr = ActivityTracker(small_settings())
    tr.record([sample(pid=1, cpu=5.0, rss_mb=100), sample(pid=2, cpu=50.0, rss_mb=900),
               sample(pid=3, cpu=20.0, rss_mb=500)], None)
    assert [k[0] for k, _ in tr.top_by_cpu(2)] == [2, 3]
    assert [k[0] for k, _ in tr.top_by_memory(1)] == [2]


def test_clear_empties_everything():
    tr = ActivityTracker(small_settings())
    feed(tr, [1.0] * 3)
    tr.clear()
    assert tr.tracked() == [] and tr.passes == 0 and not tr.system and not tr.timeline


def test_memory_growth_requires_monotonic_increase():
    tr = ActivityTracker(small_settings(growth_min_samples=5))
    k = feed(tr, [1.0] * 5, rss_mb=[100, 150, 200, 260, 320]).key
    growth = tr.memory_growth_mb(k, 5)
    assert growth is not None and round(growth[0]) == 220
    tr2 = ActivityTracker(small_settings(growth_min_samples=5))
    k2 = feed(tr2, [1.0] * 5, rss_mb=[100, 400, 100, 400, 450]).key
    assert tr2.memory_growth_mb(k2, 5) is None
