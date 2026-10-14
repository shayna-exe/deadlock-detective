from process_monitor.activity_tracker import ActivityTracker
from process_monitor.recommendations import RecommendationEngine
from ui.guide_content import GUIDE
from ui.viewmodels import (ALL, badge_text, card_parts, filter_and_sort, nice_max, overview_attention, process_row,
                           scale_series)
from tests.helpers import feed, sample, small_settings


def assessed(specs):
    """specs: list of (pid, name, cpus, rss_mb) -> assessments produced by the real engine.

    All processes are recorded together tick by tick (a process missing from a pass is treated as
    exited and its history is dropped); shorter series simply start later.
    """
    from tests.helpers import T0
    st = small_settings()
    tr = ActivityTracker(st)
    ticks = max(len(cpus) for _, _, cpus, _ in specs)
    last = {}
    for i in range(ticks):
        batch = []
        for pid, name, cpus, rss in specs:
            j = i - (ticks - len(cpus))
            if j >= 0:
                last[pid] = sample(pid=pid, name=name, t=T0 + i, cpu=cpus[j], rss_mb=rss, create=1000.0 + pid,
                                   exe=f"/home/u/{name}", status="sleeping" if pid % 2 else "running")
                batch.append(last[pid])
        tr.record(batch, None)
    eng = RecommendationEngine(st, own_pids={99999})
    return [eng.assess(s, tr) for s in last.values()]


SPECS = [(101, "alpha", [0.1] * 30, 400.0), (102, "Beta", [50.0] * 30, 100.0), (103, "gamma", [95.0] * 15, 900.0)]


def test_search_by_name_and_pid_is_case_insensitive():
    items = assessed(SPECS)
    assert [a.name for a in filter_and_sort(items, "BETA")] == ["Beta"]
    assert [a.pid for a in filter_and_sort(items, "103")] == [103]
    assert filter_and_sort(items, "zzz") == []


def test_sorting_by_each_key():
    items = assessed(SPECS)
    assert [a.pid for a in filter_and_sort(items, sort="CPU %")] == [103, 102, 101]
    assert [a.pid for a in filter_and_sort(items, sort="Memory")] == [103, 101, 102]
    assert [a.name for a in filter_and_sort(items, sort="Name")] == ["alpha", "Beta", "gamma"]
    assert filter_and_sort(items, sort="CPU time", descending=False)[0].pid in (101, 102, 103)


def test_filters_by_category_and_state():
    items = assessed(SPECS)
    closing = filter_and_sort(items, category="Consider Closing")
    assert [a.pid for a in closing] == [101]
    assert [a.pid for a in filter_and_sort(items, status="running")] == [102]
    assert len(filter_and_sort(items, category=ALL, status=ALL)) == 3


def test_row_formatting_is_honest_about_missing_values():
    st = small_settings()
    tr = ActivityTracker(st)
    s = sample(ready=False)
    tr.record([s], None)
    a = RecommendationEngine(st, own_pids=set()).assess(s, tr)
    row = process_row(a)
    assert row[2] == "warming up" and "Monitoring Unavailable" in row[7]


def test_badges_use_symbols_not_just_colour():
    assert badge_text("Consider Closing").startswith("◆") and badge_text("Keep Running").startswith("✔")


def test_scale_series_keeps_gaps_and_clamps():
    pts = scale_series([0, None, 50, 200], 200, 100, (10, 10, 10, 10), 100)
    assert pts[1] is None and pts[0][1] == 90 and pts[3][1] == 10
    assert scale_series([], 100, 100, (0, 0, 0, 0), 0) == []


def test_nice_max():
    assert nice_max(3) == 10 and nice_max(73) == 100 and nice_max(1800) == 2000


def test_overview_orders_actionable_items_first_and_skips_keep():
    items = assessed(SPECS + [(104, "delta", [20.0] * 30, 50.0)])
    top = overview_attention(items)
    assert [a.name for a in top][0] == "alpha" and all(a.name != "delta" for a in top)


def test_card_separates_information_advice_and_limits_and_labels_estimates():
    a = assessed(SPECS)[0]
    parts = card_parts(a)
    heads = [t for t, tag in parts if tag == "h"]
    assert "INFORMATION: what was measured" in heads and "ADVICE: suggested next step" in heads and "LIMITATIONS" in heads
    assert "ESTIMATE" in " ".join(t for t, _ in parts)
    assert card_parts(None)[0][0] == "Select a process"


def test_guide_covers_required_concepts_and_links_each_to_the_implementation():
    titles = " ".join(t for t, _, _ in GUIDE).lower()
    for needed in ("process management", "process states", "mutual exclusion", "hold-and-wait", "no preemption",
                   "circular wait", "wait-for graph", "dfs", "scheduling", "memory", "signals",
                   "detection vs prevention vs recovery"):
        assert needed in titles
    assert all(where.strip() for _, _, where in GUIDE)
