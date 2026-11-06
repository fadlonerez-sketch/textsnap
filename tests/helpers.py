"""Synthetic desktops and fakes shared by UI/controller tests."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, Signal

from textsnap.capture.convert import rgb_to_qimage
from textsnap.capture.geometry import Monitor, Rect, virtual_bounds
from textsnap.capture.screen import DesktopSnapshot


def coordinate_image(bounds: Rect) -> np.ndarray:
    """Every pixel encodes its own physical position: R=x%256, G=y%256, B=hi bits."""
    ys, xs = np.mgrid[bounds.y:bounds.bottom, bounds.x:bounds.right]
    xs_u, ys_u = xs - bounds.x, ys - bounds.y
    img = np.zeros((bounds.h, bounds.w, 3), np.uint8)
    img[..., 0] = xs_u % 256
    img[..., 1] = ys_u % 256
    img[..., 2] = (xs_u // 256) % 16 * 16 + (ys_u // 256) % 16
    return img


def decode(pixel, bounds: Rect) -> tuple[int, int]:
    r, g, b = (int(v) for v in pixel)
    return bounds.x + (b // 16) * 256 + r, bounds.y + (b % 16) * 256 + g


def snapshot_from(monitors: list[Monitor], rgb: np.ndarray, windows=None) -> DesktopSnapshot:
    bounds = virtual_bounds(monitors)
    assert rgb.shape[:2] == (bounds.h, bounds.w)
    return DesktopSnapshot(monitors, bounds, rgb_to_qimage(rgb), windows or [])


class FakeTrigger(QObject):
    activated = Signal()
    detector_event = Signal(str, dict)
    escape_pressed = Signal()
    status_changed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.state, self.message, self.hook = "stopped", "", None
        self.applied: list[tuple] = []
        self.watch_escape = False
        self.shut = False

    def apply(self, enabled, keys, hold_ms, cancel_on_other_input=True, accept_injected=True, hold_back=True):
        self.applied.append((enabled, list(keys), hold_ms))
        self.hold_back = hold_back
        self.state = "active" if enabled else "disabled"
        self.status_changed.emit(self.state, "fake")

    def set_watch_escape(self, on):
        self.watch_escape = on

    def shutdown(self):
        self.shut = True


class FakeClipboardBackend:
    def __init__(self, fail_opens: int = 0):
        self.fail_opens = fail_opens
        self.opens = 0
        self.is_open = False
        self.text: str | None = None
        self.formats: dict[str, int] = {}

    def open(self, owner):
        self.opens += 1
        if self.fail_opens > 0:
            self.fail_opens -= 1
            return False
        self.is_open = True
        return True

    def close(self):
        self.is_open = False

    def empty(self):
        self.text, self.formats = None, {}
        return True

    def set_text(self, text):
        assert self.is_open
        self.text = text
        return True

    def set_dword_format(self, name, value):
        self.formats[name] = value
        return True

    def get_text(self):
        return self.text
