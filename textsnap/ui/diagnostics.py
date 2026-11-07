"""Plain-text diagnostics for About & diagnostics (no recognised text, ever)."""

from __future__ import annotations

import platform
import sys
from typing import TYPE_CHECKING

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import qVersion

from textsnap import APP_NAME, __version__
from textsnap.storage import paths
from textsnap.ui import motion

if TYPE_CHECKING:
    from textsnap.app.controller import AppController


def diagnostics(c: AppController) -> str:
    from textsnap.capture.screen import current_monitors
    lines = [f"{APP_NAME} {__version__}", f"Python {sys.version.split()[0]} · Qt {qVersion()} · "
             f"PySide6 {PYSIDE_VERSION}", f"Windows {platform.version()} ({platform.machine()})",
             f"Frozen build: {paths.is_frozen()}", f"Data folder: {paths.data_dir()}", ""]
    st = c.engine_status
    lines.append(f"OCR engine: {st.summary() if st else 'not checked yet'}")
    if st and st.ok:
        for model in ("best", "fast"):
            lines.append(f"  {model}: {', '.join(st.languages.get(model, []))}")
    lines.append(f"  folder: {c.engine.folder}")
    lines.append("")
    lines.append(f"Trigger: {c.trigger.state} — {c.trigger.message}")
    hook = c.trigger.hook
    lines.append(f"  keyboard hook installed: {bool(hook and getattr(hook, 'hooks_installed', False))}")
    try:
        import ctypes
        u = ctypes.windll.user32
        aware = u.GetAwarenessFromDpiAwarenessContext(u.GetThreadDpiAwarenessContext())
        lines.append(f"  DPI awareness: {['unaware', 'system', 'per-monitor'][aware] if 0 <= aware <= 2 else aware}")
    except Exception:
        pass
    lines.append(f"  reduced motion: {motion.reduced()} (setting {c.settings.reduce_motion}, Windows animations "
                 f"{'on' if motion.system_animations_enabled() else 'off'})")
    lines.append("")
    try:
        for m in current_monitors():
            p, g = m.physical, m.logical
            lines.append(f"Display {m.index + 1}{' (primary)' if m.primary else ''}: {p.w}x{p.h} at ({p.x}, {p.y}) "
                         f"physical, {m.scale_percent}% scale, logical {g.w}x{g.h} at ({g.x}, {g.y})")
    except Exception as exc:
        lines.append(f"Displays: unavailable ({exc})")
    s = c.settings
    lines += ["", f"Language {s.ocr_language}, quality {s.ocr_quality}, model {s.ocr_model}, layout {s.ocr_layout}, "
                  f"preprocess {s.preprocess}",
              f"History {'on' if s.history_enabled else 'off'}, save captures {'on' if s.save_captures else 'off'}, "
              f"auto copy {'on' if s.auto_copy else 'off'}, auto paste {'on' if s.auto_paste else 'off'}"]
    return "\n".join(lines)
