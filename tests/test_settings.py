import json

import pytest

from process_monitor.settings import MonitorSettings, SettingsError, load_settings, save_settings


def test_defaults_are_valid():
    st = MonitorSettings().validate()
    assert st.sample_interval_s == 2.0 and "lsass.exe" in st.protected_names


@pytest.mark.parametrize("field,value", [
    ("sample_interval_s", 0.01), ("sample_interval_s", "fast"), ("idle_cpu_percent", -1),
    ("max_samples_per_process", 3), ("max_samples_per_process", 10.5), ("high_cpu_percent", 500),
    ("allow_force_kill", "yes"),
])
def test_invalid_values_are_rejected(field, value):
    with pytest.raises(SettingsError):
        MonitorSettings(**{field: value}).validate()


def test_cross_field_rules():
    with pytest.raises(SettingsError, match="close_min_seconds"):
        MonitorSettings(idle_min_seconds=600.0, close_min_seconds=300.0).validate()
    with pytest.raises(SettingsError, match="lower_priority"):
        MonitorSettings(high_cpu_percent=90.0, lower_priority_cpu_percent=80.0).validate()


def test_unknown_keys_and_wrong_types_rejected():
    with pytest.raises(SettingsError, match="Unknown"):
        MonitorSettings.from_dict({"nonsense": 1})
    with pytest.raises(SettingsError):
        MonitorSettings.from_dict([1, 2])


def test_protected_names_are_normalised():
    st = MonitorSettings(protected_names=[" Foo.EXE ", "foo.exe"]).validate()
    assert st.protected_names == ["foo.exe"]


def test_save_and_load_roundtrip_and_missing_file(tmp_path):
    path = tmp_path / "s.json"
    assert load_settings(path).sample_interval_s == 2.0
    save_settings(MonitorSettings(sample_interval_s=5.0).validate(), path)
    assert load_settings(path).sample_interval_s == 5.0


def test_corrupt_file_raises_settings_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(path)
    path.write_text(json.dumps({"sample_interval_s": -5}), encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(path)


def test_with_changes_validates():
    st = MonitorSettings().validate()
    assert st.with_changes(sample_interval_s=3.0).sample_interval_s == 3.0
    with pytest.raises(SettingsError):
        st.with_changes(sample_interval_s=0)
