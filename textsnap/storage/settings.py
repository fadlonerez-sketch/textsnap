"""Persistent user settings.

Settings are a flat dataclass serialised to JSON. Every field carries its own
validation rule, so a hand-edited or corrupted file degrades to defaults
field-by-field instead of breaking start-up. Writes are atomic.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

SCHEMA_VERSION = 3
DEFAULT_SEARCH_URL = "https://www.google.com/search?q={query}"


def validate_search_url(template: Any) -> str | None:
    """Return an error message, or None if the template is a usable http(s) search URL.

    The template is handed to the system URL opener, so anything other than a
    plain web address (file:, custom protocols, javascript: ...) is refused.
    """
    if not isinstance(template, str) or "{query}" not in template:
        return "the search address must contain {query} where the search text goes"
    url = template.replace("{query}", "test")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return "the search address must not contain spaces or control characters"
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        host = None
        parts = None
    if parts is None or parts.scheme.lower() not in ("http", "https") or not host:
        return "the search address must be a valid http:// or https:// URL"
    return None


def safe_search_url(template: Any) -> str:
    """The template if it is a valid http(s) search URL, otherwise the default."""
    return template if validate_search_url(template) is None else DEFAULT_SEARCH_URL


def _choice(default: str, choices: list[str]) -> Any:
    return field(default=default, metadata={"choices": choices})


def _range(default: float, lo: float, hi: float) -> Any:
    return field(default=default, metadata={"min": lo, "max": hi})


LANGUAGE_CHOICES = ["heb+eng", "heb", "eng", "auto"]
LANGUAGE_LABELS = {
    "heb+eng": "Hebrew + English",
    "heb": "Hebrew",
    "eng": "English",
    "auto": "Auto-detect (best effort)",
}


@dataclass
class Settings:
    # Keyboard trigger
    trigger_enabled: bool = True
    trigger_keys: list[str] = field(default_factory=lambda: ["Space"])
    hold_ms: int = _range(500, 200, 3000)
    cancel_on_other_input: bool = True
    hold_back_trigger_key: bool = True  # Spacebar: hold back, replay taps
    accept_injected_keys: bool = True

    # Capture
    capture_mode: str = _choice("region", ["region", "window", "monitor", "desktop", "active"])
    show_magnifier: bool = True
    show_crosshair: bool = False
    show_dimensions: bool = True
    overlay_dim_percent: int = _range(45, 10, 85)
    min_selection_px: int = _range(8, 3, 200)
    restore_focus: bool = True

    # OCR
    ocr_language: str = _choice("heb+eng", LANGUAGE_CHOICES)
    ocr_quality: str = _choice("fast", ["fast", "thorough"])
    ocr_model: str = _choice("best", ["best", "fast"])
    ocr_layout: str = _choice("auto", ["auto", "block", "line", "sparse", "columns"])
    ocr_timeout_s: int = _range(20, 3, 180)
    preprocess: str = _choice("auto", ["auto", "light", "off"])
    strip_bidi_marks: bool = True
    fix_mixed_script: bool = True
    detect_qr: bool = False
    tesseract_dir: str = ""

    # Results
    auto_copy: bool = True
    copy_cleaned: bool = False
    preserve_line_breaks: bool = True
    show_toast: bool = True
    toast_seconds: float = _range(3.5, 1.0, 20.0)
    open_result_window: bool = False
    result_on_top: bool = True
    auto_paste: bool = False
    exclude_from_clipboard_history: bool = False
    search_url: str = DEFAULT_SEARCH_URL
    last_save_dir: str = ""

    # History (opt-in)
    history_enabled: bool = False
    history_retention_days: int = _range(30, 0, 3650)

    # Storage
    save_captures: bool = False
    save_captures_dir: str = ""

    # Diagnostics / startup
    log_level: str = _choice("INFO", ["WARNING", "INFO", "DEBUG"])
    start_with_windows: bool = False

    # UI state
    first_run_done: bool = False
    onboarding_done: bool = False  # the welcome tour was shown (or skipped)
    reduce_motion: bool = False  # minimise non-essential animation

    def copy(self) -> "Settings":
        return dataclasses.replace(self, trigger_keys=list(self.trigger_keys))

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["_schema"] = SCHEMA_VERSION
        return data


def _defaults() -> Settings:
    return Settings()


def validate(raw: dict[str, Any]) -> tuple[Settings, list[str]]:
    """Build Settings from untrusted data. Invalid fields fall back to defaults."""
    settings = _defaults()
    problems: list[str] = []
    if not isinstance(raw, dict):
        return settings, ["settings file is not a JSON object"]
    for f in dataclasses.fields(Settings):
        if f.name not in raw:
            continue
        value = raw[f.name]
        default = getattr(settings, f.name)
        meta = f.metadata
        try:
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    raise ValueError("expected true/false")
            elif isinstance(default, int):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("expected a number")
                value = int(round(value))
            elif isinstance(default, float):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("expected a number")
                value = float(value)
            elif isinstance(default, str):
                if not isinstance(value, str):
                    raise ValueError("expected text")
            elif isinstance(default, list):
                if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                    raise ValueError("expected a list of names")
                value = list(value)
            if "choices" in meta and value not in meta["choices"]:
                raise ValueError(f"must be one of {meta['choices']}")
            if "min" in meta:
                clamped = min(max(value, meta["min"]), meta["max"])
                if clamped != value:
                    problems.append(f"{f.name}: {value} out of range, clamped")
                value = type(default)(clamped)
        except ValueError as exc:
            problems.append(f"{f.name}: {exc}; using default")
            continue
        setattr(settings, f.name, value)

    from textsnap.keyboard.keys import validate_trigger  # local import: avoid cycle

    trigger_error = validate_trigger(settings.trigger_keys)
    if trigger_error:
        problems.append(f"trigger_keys: {trigger_error}; using default")
        settings.trigger_keys = _defaults().trigger_keys
    search_error = validate_search_url(settings.search_url)
    if search_error:
        problems.append(f"search_url: {search_error}; using default")
        settings.search_url = DEFAULT_SEARCH_URL
    return settings, problems


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade older settings files.

    Schema 2 made the Spacebar the default trigger. A file that still holds
    the previous default (Right Ctrl alone) is moved to the Spacebar; any
    other, customised trigger is kept. Schema 3 added the welcome tour, which
    existing installations skip.
    """
    raw = dict(raw)
    version = raw.get("_schema", 1)
    if isinstance(version, int) and version < 2 and raw.get("trigger_keys") == ["RCtrl"]:
        raw["trigger_keys"] = ["Space"]
        log.info("Settings migrated: default trigger changed from Right Ctrl to Spacebar")
    if isinstance(version, int) and version < 3 and "onboarding_done" not in raw:
        raw["onboarding_done"] = True  # existing users are not sent through the new welcome tour
    return raw


class SettingsStore:
    """Loads and atomically saves settings.json."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.load_problems: list[str] = []

    def load(self) -> Settings:
        if not self.path.exists():
            return _defaults()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Settings file unreadable (%s); backing it up and using defaults", type(exc).__name__)
            self._backup_corrupt()
            self.load_problems = ["settings file was unreadable; defaults restored"]
            return _defaults()
        if isinstance(raw, dict):
            raw = migrate(raw)
        settings, problems = validate(raw)
        self.load_problems = problems
        for p in problems:
            log.warning("Settings: %s", p)
        return settings

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def reset(self) -> Settings:
        settings = _defaults()
        self.save(settings)
        return settings

    def _backup_corrupt(self) -> None:
        try:
            self.path.replace(self.path.with_name(f"settings.corrupt-{int(time.time())}.json"))
        except OSError:
            pass
