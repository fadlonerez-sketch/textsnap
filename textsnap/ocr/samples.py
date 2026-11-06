"""Synthetic text images for the self-test and the automated tests.

Text is drawn with Qt (HarfBuzz shaping and the Unicode bidi algorithm), the
same way applications render it on screen. No real screen content is used.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter

from textsnap.capture.convert import qimage_to_rgb

FONT_FILES = ["segoeui.ttf", "arial.ttf", "tahoma.ttf", "consola.ttf", "times.ttf"]

ENGLISH = ["The quick brown fox jumps over the lazy dog.", "Invoice #4521 total: $1,299.50 (due 2026-11-03)"]
HEBREW = ["שלום עולם, זהו מבחן של זיהוי טקסט.", "המחיר הכולל הוא 120 שקלים בלבד"]
MIXED = ["הפגישה עם Microsoft תתקיים ביום שלישי", "נא לשלוח את הקובץ report.pdf עד מחר"]

_fonts_checked = False


def ensure_fonts() -> None:
    """Register Windows fonts when Qt has none (the offscreen platform)."""
    global _fonts_checked
    if _fonts_checked:
        return
    _fonts_checked = True
    if QFontDatabase.families():
        return
    folder = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in FONT_FILES:
        path = folder / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


def has_hebrew(s: str) -> bool:
    return any("\u0590" <= c <= "\u05ff" for c in s)


def render_lines(lines: list[str], px: int = 15, family: str = "Segoe UI",
                 fg: tuple[int, int, int] = (25, 25, 25), bg: tuple[int, int, int] = (255, 255, 255),
                 width: int | None = None, spacing: float = 1.6, margin: int = 10,
                 bold: bool = False) -> np.ndarray:
    ensure_fonts()
    font = QFont(family)
    font.setPixelSize(px)
    font.setBold(bold)
    line_h = int(round(px * spacing))
    width = width or max(200, int(px * 0.62 * max(len(s) for s in lines)) + 2 * margin)
    img = QImage(width, line_h * len(lines) + 2 * margin, QImage.Format.Format_RGB32)
    img.fill(QColor(*bg))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setFont(font)
    p.setPen(QColor(*fg))
    for i, s in enumerate(lines):
        align = Qt.AlignmentFlag.AlignRight if has_hebrew(s[:1] or s) else Qt.AlignmentFlag.AlignLeft
        p.drawText(QRect(margin, margin + i * line_h, width - 2 * margin, line_h),
                   align | Qt.AlignmentFlag.AlignVCenter, s)
    p.end()
    return qimage_to_rgb(img)
