"""Foreground-window helpers.

The overlay must receive keyboard focus (for Esc) even though TextSnap is a
background process. Windows only lets the foreground process change the
foreground window, so the input queues are attached to the current
foreground thread for the duration of the call - the documented
AttachThreadInput technique. No input is synthesised.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.BringWindowToTop.argtypes = [wt.HWND]
user32.IsWindow.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.SetFocus.argtypes = [wt.HWND]
kernel32.GetCurrentThreadId.restype = wt.DWORD


def foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


def window_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def foreign_foreground_window() -> int:
    """The foreground window if it belongs to another process, else 0."""
    hwnd = foreground_window()
    return hwnd if hwnd and window_pid(hwnd) != os.getpid() else 0


def force_foreground(hwnd: int) -> bool:
    if not hwnd:
        return False
    fg = foreground_window()
    if fg == hwnd:
        return True
    current = kernel32.GetCurrentThreadId()
    target = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(target and target != current and user32.AttachThreadInput(current, target, True))
    try:
        user32.BringWindowToTop(hwnd)
        ok = bool(user32.SetForegroundWindow(hwnd))
        user32.SetFocus(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current, target, False)
    return ok or foreground_window() == hwnd


def restore_foreground(hwnd: int) -> bool:
    """Give focus back to the window that was active before the capture."""
    if not hwnd or not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return False
    return bool(user32.SetForegroundWindow(hwnd)) or force_foreground(hwnd)
