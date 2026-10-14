"""Rule engine tests with synthetic measurements (no invented values in the engine itself)."""
from process_monitor.activity_tracker import ActivityTracker
from process_monitor.recommendations import (CLOSE, HIGH_CPU, HIGH_MEM, IDLE, INVESTIGATE, KEEP, LOWER,
                                             PROTECTED, UNAVAILABLE, RecommendationEngine)
from tests.helpers import T0, feed, sample, small_settings

OWN = {99999}


def assess(cpus, settings=None, rss_mb=300.0, **kw):
    st = settings or small_settings()
    tr = ActivityTracker(st)
    last = feed(tr, cpus, rss_mb=rss_mb, **kw)
    return RecommendationEngine(st, own_pids=OWN).assess(last, tr)


def test_too_few_samples_is_monitoring_unavailable():
    a = assess([0.1, 0.1])
    assert a.category == UNAVAILABLE and "only 2 of the 3" in a.headline


def test_first_sample_without_baseline_is_unavailable():
    st = small_settings()
    tr = ActivityTracker(st)
    s = sample(ready=False)
    tr.record([s], None)
    a = RecommendationEngine(st, own_pids=OWN).assess(s, tr)
    assert a.category == UNAVAILABLE and "baseline" in a.headline


def test_access_denied_is_unavailable_with_explanation():
    st = small_settings()
    tr = ActivityTracker(st)
    s = sample(access="denied")
    tr.record([s], None)
    a = RecommendationEngine(st, own_pids=OWN).assess(s, tr)
    assert a.category == UNAVAILABLE and "access denied" in a.headline


def test_active_process_is_keep_running():
    a = assess([20, 25, 30, 22, 28, 24])
    assert a.category == KEEP and a.rule_id == "R9"


def test_idle_but_short_is_not_flagged():
    a = assess([0.1] * 6)          # 5 s of low activity < idle_min_seconds (10 s)
    assert a.category == KEEP


def test_potentially_idle_needs_duration_and_memory():
    a = assess([0.1] * 14)         # 13 s >= 10 s, 300 MB >= 100 MB
    assert a.category == IDLE and a.rule_id == "R7"
    small = assess([0.1] * 14, rss_mb=20.0)   # not enough memory held
    assert small.category == KEEP


def test_consider_closing_after_longer_low_activity():
    a = assess([0.1] * 30)         # 29 s >= close_min_seconds (20 s)
    assert a.category == CLOSE and a.rule_id == "R6"
    assert "Check whether you still need this application" in a.headline
    assert a.memory_estimate_mb == 300.0
    assert a.low_activity_s == 29.0


def test_close_recommendation_uses_real_numbers_in_the_text():
    a = assess([0.1] * 30, rss_mb=350.0)
    assert "350 MB" in a.headline and "29 s" in a.headline and "30 samples" in a.headline


def test_evidence_strength_grows_with_duration():
    moderate = assess([0.1] * 30)
    strong = assess([0.1] * 70)          # >= 3x close_min_seconds
    assert moderate.strength == "Moderate" and strong.strength == "Strong"


def test_every_assessment_explains_itself():
    a = assess([0.1] * 30)
    assert a.evidence and a.limitations and a.next_step and a.rule_detail
    assert any("Cumulative CPU time" in e for e in a.evidence)
    assert any("not elapsed time" in e for e in a.evidence)
    assert a.samples_observed == 30
    d = a.to_dict()
    assert d["recommendation"] == CLOSE and d["memory_estimate_note"].startswith("Estimate only")


def test_high_cpu_requires_sustained_usage():
    spike = assess([5, 5, 5, 90, 5, 5])
    assert spike.category == KEEP
    sustained = assess([5] * 3 + [70] * 8, settings=small_settings(lower_priority_cpu_percent=90.0))
    assert sustained.category == HIGH_CPU and "High CPU" in sustained.headline


def test_lower_priority_for_heavy_noncritical_process():
    a = assess([95] * 15)
    assert a.category == LOWER
    assert "Heavy CPU use may be exactly what you want" in " ".join(a.limitations)


def test_already_low_priority_falls_back_to_high_cpu():
    import sys
    already = 16384 if sys.platform == "win32" else 15
    a = assess([95] * 15, nice=already)
    assert a.category == HIGH_CPU


def test_protected_process_is_never_recommended_for_action():
    a = assess([0.1] * 40, name="svchost.exe", exe="C:/Windows/System32/svchost.exe")
    assert a.category == PROTECTED and a.protected and a.memory_estimate_mb is None
    assert "protected" in a.headline.lower()


def test_protected_by_system_folder_even_if_name_is_unknown():
    a = assess([0.1] * 40, name="mystery.exe", exe="C:\\Windows\\System32\\mystery.exe")
    assert a.category == PROTECTED


def test_own_process_is_protected():
    st = small_settings()
    tr = ActivityTracker(st)
    last = feed(tr, [0.1] * 40, pid=99999)
    assert RecommendationEngine(st, own_pids=OWN).assess(last, tr).category == PROTECTED


def test_unidentifiable_process_fails_safe():
    a = assess([0.1] * 40, name="<pid 500>", missing=("name",))
    assert a.category == PROTECTED


def test_custom_protected_list_is_honoured():
    st = small_settings(protected_names=["notes.exe"])
    a = assess([0.1] * 40, settings=st)
    assert a.category == PROTECTED


def test_high_memory_absolute_and_percentage_rules_are_explained():
    absolute = assess([10] * 6, rss_mb=2000.0, settings=small_settings(high_memory_mb=1500.0, high_memory_percent=50.0))
    assert absolute.category == HIGH_MEM and "absolute rule" in absolute.headline
    pct = assess([10] * 6, rss_mb=2000.0, settings=small_settings(high_memory_mb=9000.0, high_memory_percent=5.0))
    assert pct.category == HIGH_MEM and "percentage rule" in pct.headline


def test_memory_growth_triggers_investigate_not_certainty():
    a = assess([10] * 5, rss_mb=[100, 160, 230, 300, 380])
    assert a.category == INVESTIGATE
    assert "not proof of a leak" in " ".join(a.limitations)


def test_thresholds_are_configurable():
    cpus = [0.1] * 14
    default = assess(cpus)
    stricter = assess(cpus, settings=small_settings(idle_min_seconds=60.0, close_min_seconds=120.0))
    assert default.category == IDLE and stricter.category == KEEP


def test_idle_cpu_threshold_is_configurable():
    cpus = [2.0] * 30
    assert assess(cpus).category == KEEP
    assert assess(cpus, settings=small_settings(idle_cpu_percent=5.0)).category == CLOSE


def test_recommendation_changes_are_logged_on_timeline():
    st = small_settings()
    tr = ActivityTracker(st)
    eng = RecommendationEngine(st, own_pids=OWN)
    for i in range(30):
        s = sample(t=T0 + i, cpu=0.1)
        tr.record([s], None)
        eng.assess_all([s], tr)
    cats = [e.category for e in tr.timeline]
    assert cats[-1] == CLOSE and KEEP not in cats and len(cats) == len(set(cats))


def test_no_performance_gain_claims_anywhere():
    a = assess([0.1] * 30)
    blob = " ".join([a.headline, a.next_step, *a.evidence, *a.limitations]).lower()
    assert "% faster" not in blob and "speed up" not in blob and "will improve" not in blob
