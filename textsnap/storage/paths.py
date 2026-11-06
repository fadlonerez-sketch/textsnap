"""Per-user data locations and bundled resource discovery.

The data directory defaults to %LOCALAPPDATA%\\TextSnap. Tests and the
packaged self-test override it (``TEXTSNAP_DATA_DIR`` or ``--data-dir``) so
they never touch the user's real settings or history.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from textsnap import APP_NAME

ENV_DATA_DIR = "TEXTSNAP_DATA_DIR"
ENV_TESSERACT_DIR = "TEXTSNAP_TESSERACT_DIR"

_override: Path | None = None


def set_data_dir(path: str | os.PathLike[str] | None) -> None:
    """Force a data directory for this process (``None`` restores the default)."""
    global _override
    _override = Path(path).resolve() if path else None


def data_dir(create: bool = True) -> Path:
    if _override is not None:
        path = _override
    elif os.environ.get(ENV_DATA_DIR):
        path = Path(os.environ[ENV_DATA_DIR]).resolve()
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / APP_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return data_dir() / "settings.json"


def history_db_path() -> Path:
    return data_dir() / "history.db"


def logs_dir(create: bool = True) -> Path:
    path = data_dir(create) / "logs"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Directory holding ``vendor/`` and ``assets/`` (source tree or PyInstaller bundle)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    return resource_root() / "assets"


def bundled_tesseract_dir() -> Path:
    return resource_root() / "vendor" / "tesseract"


def tesseract_dir(custom: str = "") -> Path:
    """Tesseract folder: explicit setting, then env override, then the bundled copy."""
    if custom:
        return Path(custom)
    if os.environ.get(ENV_TESSERACT_DIR):
        return Path(os.environ[ENV_TESSERACT_DIR])
    return bundled_tesseract_dir()


def executable_command() -> list[str]:
    """Command line that relaunches this application (used for the opt-in autostart)."""
    if is_frozen():
        return [sys.executable]
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    main = resource_root() / "main.py"
    return [str(pythonw if pythonw.exists() else exe), str(main)]
