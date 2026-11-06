"""Styled modal dialogs (replacing the stock QMessageBox / QInputDialog look).

All dialogs share one layout: a tinted icon badge, a title, the explanation,
optional extra content and right-aligned actions where the primary action is
visually distinct and destructive actions are red.
"""

from __future__ import annotations

import ctypes
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from textsnap.ui import motion, theme
from textsnap.ui.theme import C, S
from textsnap.ui.widgets import button, label

DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR = 20, 34, 35


def _colorref(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def dark_title_bar(widget: QWidget, caption: str = C.BG) -> None:
    """Dark native title bar matching the window canvas (Windows 10 2004+ / 11)."""
    try:
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(on), 4)
        color = ctypes.c_int(_colorref(caption))
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(color), 4)  # Windows 11 only
        border = ctypes.c_int(_colorref(C.BORDER_STRONG))
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(border), 4)
    except (AttributeError, OSError):
        pass


KIND_ICON = {"info": ("info", C.ACCENT), "question": ("info", C.ACCENT), "success": ("success", C.SUCCESS),
             "warning": ("warning", C.WARNING), "danger": ("delete", C.DANGER), "error": ("error", C.DANGER)}


class Dialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, text: str = "", kind: str = "info"):
        super().__init__(parent)
        self.setObjectName("appRoot")
        self.setWindowTitle(title)
        self.setWindowIcon(theme.app_icon())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(440)
        self.setMaximumWidth(560)
        self.result_value: Any = None
        root = QVBoxLayout(self)
        root.setContentsMargins(S.XXL, S.XXL, S.XXL, S.XL)
        root.setSpacing(S.LG)
        head = QHBoxLayout()
        head.setSpacing(S.LG)
        name, color = KIND_ICON.get(kind, KIND_ICON["info"])
        badge = QLabel(theme.GLYPH[name], objectName="dialogBadge")
        badge.setProperty("kind", kind if kind in theme.STATE_COLOR else "info")
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(6)
        col.addWidget(label(title, "dialogTitle"))
        if text:
            body = label(text, "muted")
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            col.addWidget(body)
        self.extra = QVBoxLayout()
        self.extra.setSpacing(S.SM)
        col.addLayout(self.extra)
        head.addLayout(col, 1)
        root.addLayout(head)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(S.SM)
        self.buttons.addStretch(1)
        root.addLayout(self.buttons)
        self._default: QPushButton | None = None

    def add_button(self, text: str, value: Any, variant: str = "", default: bool = False) -> QPushButton:
        b = button(text, variant=variant)
        b.clicked.connect(lambda _=False, v=value: self._finish(v))
        self.buttons.addWidget(b)
        if default:
            b.setDefault(True)
            b.setFocus()
            self._default = b
        return b

    def _finish(self, value: Any) -> None:
        self.result_value = value
        self.accept()

    def showEvent(self, e) -> None:  # noqa: N802
        dark_title_bar(self)
        motion.window_fade_in(self, motion.Duration.FAST)
        if self._default is not None:
            self._default.setFocus()
        super().showEvent(e)

    def run(self) -> Any:
        self.exec()
        return self.result_value


def confirm(parent: QWidget | None, title: str, text: str, confirm_text: str = "Continue",
            cancel_text: str = "Cancel", danger: bool = False, kind: str | None = None) -> bool:
    d = Dialog(parent, title, text, kind or ("danger" if danger else "question"))
    d.add_button(cancel_text, False, default=danger)
    d.add_button(confirm_text, True, "danger" if danger else "primary", default=not danger)
    return bool(d.run())


def inform(parent: QWidget | None, title: str, text: str, kind: str = "info", ok_text: str = "OK") -> None:
    d = Dialog(parent, title, text, kind)
    d.add_button(ok_text, True, "primary", default=True)
    d.run()


def choose(parent: QWidget | None, title: str, text: str, options: list[tuple[str, Any, str]],
           kind: str = "question") -> Any:
    """Several actions; returns the chosen value (None when closed)."""
    d = Dialog(parent, title, text, kind)
    for i, (caption, value, variant) in enumerate(options):
        d.add_button(caption, value, variant, default=(variant == "primary"))
    return d.run()


def prompt(parent: QWidget | None, title: str, text: str, value: str = "", ok_text: str = "Save") -> str | None:
    d = Dialog(parent, title, text, "info")
    field = QLineEdit(value)
    field.selectAll()
    d.extra.addWidget(field)
    d.add_button("Cancel", None)
    ok = d.add_button(ok_text, True, "primary")
    field.returnPressed.connect(ok.click)
    field.setFocus()
    return field.text().strip() if d.run() else None
