"""Top-level window rectangles for the overlay's window-picking mode.

Only geometry is collected (no titles or contents). The list is taken once
per capture, in z-order, before the overlay appears, and excludes TextSnap's
own windows, minimised windows and cloaked windows (other virtual desktops,
suspended UWP apps).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
from dataclasses import dataclass

from textsnap.capture.geometry import Rect

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

DWMWA_EXTENDED_FRAME_BOUNDS, DWMWA_CLOAKED = 9, 14
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x80, 0x20, 0x08000000

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetForegroundWindow.restype = wt.HWND
dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]

_SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    rect: Rect
    foreground: bool = False


def window_rect(hwnd: int) -> Rect | None:
    rc = wt.RECT()
    if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rc), ctypes.sizeof(rc)) != 0:
        if not user32.GetWindowRect(hwnd, ctypes.byref(rc)):
            return None
    r = Rect.from_edges(rc.left, rc.top, rc.right, rc.bottom)
    return None if r.empty else r


def _cloaked(hwnd: int) -> bool:
    value = wt.DWORD(0)
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    return bool(value.value)


def visible_windows() -> list[WindowInfo]:
    own_pid = os.getpid()
    foreground = int(user32.GetForegroundWindow() or 0)
    found: list[WindowInfo] = []
    name = ctypes.create_unicode_buffer(64)

    def callback(hwnd, _):
        h = int(hwnd or 0)
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd) or _cloaked(hwnd):
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own_pid:
            return True
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TRANSPARENT or (ex & WS_EX_TOOLWINDOW and ex & WS_EX_NOACTIVATE):
            return True
        user32.GetClassNameW(hwnd, name, 64)
        if name.value in _SKIP_CLASSES:
            return True
        rect = window_rect(h)
        if rect is not None and rect.w >= 16 and rect.h >= 16:
            found.append(WindowInfo(h, rect, h == foreground))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def window_at(windows: list[WindowInfo], px: int, py: int) -> WindowInfo | None:
    """Topmost window containing the point (the list is in z-order)."""
    for w in windows:
        if w.rect.contains(px, py):
            return w
    return None
