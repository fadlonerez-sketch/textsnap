from __future__ import annotations

import json

import pytest

from textsnap.keyboard import keys as k
from textsnap.storage import paths
from textsnap.storage.settings import Settings, SettingsStore, validate


# ------------------------------------------------------------------ keys
def test_default_trigger_is_spacebar():
    assert Settings().trigger_keys == ["Space"] == k.DEFAULT_TRIGGER
    assert Settings().hold_ms == 500
    assert Settings().hold_back_trigger_key is True
    assert k.trigger_vks(["Space"]) == frozenset({k.VK_SPACE})
    assert k.describe_trigger(["Space"]) == "Spacebar"
    assert k.PRESETS[0] == ("Spacebar (default)", ["Space"])
    assert k.trigger_vks(["RCtrl"]) == frozenset({k.VK_RCONTROL})  # still supported


def test_left_right_ctrl_have_distinct_codes():
    assert k.KEYS["LCtrl"].vk != k.KEYS["RCtrl"].vk


@pytest.mark.parametrize("vk,scan,flags,expected", [
    (k.VK_CONTROL, 0x1D, 0, k.VK_LCONTROL),
    (k.VK_CONTROL, 0x1D, k.LLKHF_EXTENDED, k.VK_RCONTROL),
    (k.VK_MENU, 0x38, k.LLKHF_EXTENDED, k.VK_RMENU),
    (k.VK_SHIFT, 0x36, 0, k.VK_RSHIFT),
    (k.VK_SHIFT, 0x2A, 0, k.VK_LSHIFT),
    (k.VK_RCONTROL, 0x1D, k.LLKHF_EXTENDED, k.VK_RCONTROL),
])
def test_normalize_generic_modifiers(vk, scan, flags, expected):
    assert k.normalize_vk(vk, scan, flags) == expected


def test_altgr_fake_ctrl_detected():
    assert k.is_altgr_fake_ctrl(k.VK_LCONTROL, 0x21D)
    assert not k.is_altgr_fake_ctrl(k.VK_LCONTROL, 0x1D)


@pytest.mark.parametrize("names,ok", [
    (["RCtrl"], True), (["LCtrl", "LShift"], True), (["LCtrl", "LAlt", "T"], True),
    ([], False), (["Nope"], False), (["RCtrl", "RCtrl"], False), (["A", "B"], False),
    (["LCtrl", "LShift", "LAlt", "LWin", "A"], False),
])
def test_validate_trigger(names, ok):
    assert (k.validate_trigger(names) is None) == ok


def test_describe_orders_modifiers_first():
    assert k.describe_trigger(["T", "LShift", "LCtrl"]) == "Left Ctrl + Left Shift + T"
    assert k.describe_trigger(["RCtrl"]) == "Right Ctrl"


def test_conflict_warnings():
    assert k.conflict_warnings(["RCtrl"]) == []
    assert any("character" in w for w in k.conflict_warnings(["A"]))
    assert any("Caps Lock" in w for w in k.conflict_warnings(["CapsLock"]))
    assert any("Start menu" in w for w in k.conflict_warnings(["LWin"]))
    assert any("shortcut" in w for w in k.conflict_warnings(["LCtrl", "T"]))
    assert k.conflict_warnings(["LCtrl"])


def test_presets_are_valid():
    for _label, names in k.PRESETS:
        assert k.validate_trigger(names) is None


# ------------------------------------------------------------------ settings
def test_settings_roundtrip_persists(isolated_data_dir):
    store = SettingsStore(paths.settings_path())
    s = store.load()
    assert s == Settings()
    s.hold_ms = 750
    s.trigger_keys = ["LCtrl", "LShift"]
    s.ocr_language = "heb"
    s.history_enabled = True
    store.save(s)
    reloaded = SettingsStore(paths.settings_path()).load()
    assert reloaded.hold_ms == 750
    assert reloaded.trigger_keys == ["LCtrl", "LShift"]
    assert reloaded.ocr_language == "heb"
    assert reloaded.history_enabled is True
    assert str(paths.settings_path()).startswith(str(isolated_data_dir))


def test_privacy_defaults_are_off():
    s = Settings()
    assert s.history_enabled is False
    assert s.save_captures is False
    assert s.start_with_windows is False
    assert s.auto_paste is False
    assert s.auto_copy is True


def test_invalid_fields_fall_back_individually():
    s, problems = validate({"hold_ms": "fast", "ocr_language": "klingon", "show_toast": 1,
                            "trigger_keys": ["Bogus"], "overlay_dim_percent": 5000, "auto_copy": False})
    assert s.hold_ms == 500 and s.ocr_language == "heb+eng" and s.show_toast is True
    assert s.trigger_keys == ["Space"]
    assert s.overlay_dim_percent == 85  # clamped
    assert s.auto_copy is False  # valid field kept
    assert len(problems) == 5


def test_hold_duration_clamped():
    assert validate({"hold_ms": 10})[0].hold_ms == 200
    assert validate({"hold_ms": 99999})[0].hold_ms == 3000


def test_corrupt_settings_file_recovers(isolated_data_dir):
    path = paths.settings_path()
    path.write_text("{not json", encoding="utf-8")
    store = SettingsStore(path)
    s = store.load()
    assert s == Settings()
    assert store.load_problems
    assert list(isolated_data_dir.glob("settings.corrupt-*.json"))


def test_non_object_settings_file():
    s, problems = validate([1, 2, 3])
    assert s == Settings() and problems


def test_reset(isolated_data_dir):
    store = SettingsStore(paths.settings_path())
    s = Settings()
    s.hold_ms = 900
    store.save(s)
    assert store.reset() == Settings()
    assert json.loads(paths.settings_path().read_text(encoding="utf-8"))["hold_ms"] == 500


def test_unicode_paths_saved(isolated_data_dir):
    store = SettingsStore(paths.settings_path())
    s = Settings()
    s.save_captures_dir = r"C:\תמונות\snap"
    store.save(s)
    assert store.load().save_captures_dir == r"C:\תמונות\snap"


def test_data_dir_override(tmp_path):
    paths.set_data_dir(tmp_path / "x")
    try:
        assert paths.data_dir() == (tmp_path / "x").resolve()
    finally:
        paths.set_data_dir(None)


# ------------------------------------------------------------------ Spacebar default & migration
def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_old_default_right_ctrl_migrates_to_spacebar(isolated_data_dir):
    _write(paths.settings_path(), {"trigger_keys": ["RCtrl"], "hold_ms": 700, "_schema": 1})
    s = SettingsStore(paths.settings_path()).load()
    assert s.trigger_keys == ["Space"] and s.hold_ms == 700  # only the trigger changes


def test_customised_trigger_survives_migration(isolated_data_dir):
    _write(paths.settings_path(), {"trigger_keys": ["LCtrl", "LShift"], "_schema": 1})
    assert SettingsStore(paths.settings_path()).load().trigger_keys == ["LCtrl", "LShift"]


def test_right_ctrl_chosen_after_migration_is_kept(isolated_data_dir):
    store = SettingsStore(paths.settings_path())
    s = Settings()
    s.trigger_keys = ["RCtrl"]
    store.save(s)  # written with schema 2
    assert SettingsStore(paths.settings_path()).load().trigger_keys == ["RCtrl"]


def test_spacebar_settings_persist(isolated_data_dir):
    store = SettingsStore(paths.settings_path())
    s = store.load()
    assert s.trigger_keys == ["Space"]
    s.hold_back_trigger_key = False
    s.hold_ms = 650
    store.save(s)
    again = SettingsStore(paths.settings_path()).load()
    assert again.trigger_keys == ["Space"] and again.hold_back_trigger_key is False and again.hold_ms == 650


def test_spacebar_warnings_describe_behaviour():
    on = " ".join(k.conflict_warnings(["Space"], hold_back=True))
    assert "release" in on and "games" in on
    off = " ".join(k.conflict_warnings(["Space"], hold_back=False))
    assert "repeated spaces" in off


@pytest.mark.parametrize("template", [
    "https://duckduckgo.com/?q={query}",
    "http://example.com/search?q={query}",
    "HTTPS://www.bing.com/search?q={query}",
])
def test_search_url_accepts_http_templates(template):
    from textsnap.storage.settings import validate_search_url
    assert validate_search_url(template) is None
    s, problems = validate({"search_url": template})
    assert s.search_url == template and not problems


@pytest.mark.parametrize("template", [
    "file:///C:/Windows/System32/calc.exe?{query}",
    "file://server/share/{query}",
    "ms-settings:{query}",
    "javascript:alert('{query}')",
    "search-ms:query={query}",
    "https://example.com/?q=",          # no {query}
    "https:///?q={query}",              # no host
    "https://exa mple.com/?q={query}",  # whitespace
    "//example.com/?q={query}",         # scheme-relative
    "C:\\tools\\run.bat {query}",
    "",
])
def test_search_url_rejects_non_http_templates(template):
    from textsnap.storage.settings import DEFAULT_SEARCH_URL, safe_search_url, validate_search_url
    assert validate_search_url(template) is not None
    assert safe_search_url(template) == DEFAULT_SEARCH_URL
    s, problems = validate({"search_url": template})
    assert s.search_url == DEFAULT_SEARCH_URL
    assert any(p.startswith("search_url:") for p in problems)


def test_edited_settings_file_with_file_search_url_loads_default(isolated_data_dir):
    from textsnap.storage.settings import DEFAULT_SEARCH_URL
    path = paths.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"search_url": "file:///C:/evil.exe?{query}"}), encoding="utf-8")
    store = SettingsStore(path)
    assert store.load().search_url == DEFAULT_SEARCH_URL
    assert any("search_url" in p for p in store.load_problems)
