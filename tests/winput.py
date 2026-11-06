"""Synthetic OS-level input for desktop integration tests (SendInput)."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x8000, 0x4000
VK_F23, VK_F24, VK_RCONTROL, VK_ESCAPE = 0x86, 0x87, 0xA3, 0x1B
VK_SPACE, VK_LSHIFT, VK_1, VK_2 = 0x20, 0xA0, 0x31, 0x32  # digits type the same in Hebrew/English layouts


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    assert sent == len(inputs), f"SendInput failed (error {ctypes.get_last_error()}; 5 = desktop locked or blocked)"


def key(vk: int, down: bool, extended: bool = False) -> None:
    i = INPUT(type=INPUT_KEYBOARD)
    flags = (0 if down else KEYEVENTF_KEYUP) | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    i.u.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    _send(i)


def hold(vk: int, seconds: float, extended: bool = False) -> None:
    key(vk, True, extended)
    try:
        time.sleep(seconds)
    finally:
        key(vk, False, extended)


def tap(vk: int) -> None:
    key(vk, True)
    key(vk, False)


def _abs(x: int, y: int) -> tuple[int, int]:
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    return int((x - vx) * 65535 / max(1, vw - 1)), int((y - vy) * 65535 / max(1, vh - 1))


def mouse_move(x: int, y: int) -> None:
    i = INPUT(type=INPUT_MOUSE)
    dx, dy = _abs(x, y)
    i.u.mi = MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, 0)
    _send(i)


def mouse_button(down: bool) -> None:
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN if down else MOUSEEVENTF_LEFTUP, 0, 0)
    _send(i)


def drag(x1: int, y1: int, x2: int, y2: int, steps: int = 12, pause: float = 0.015) -> None:
    mouse_move(x1, y1)
    time.sleep(0.08)
    mouse_button(True)
    for s in range(1, steps + 1):
        mouse_move(x1 + (x2 - x1) * s // steps, y1 + (y2 - y1) * s // steps)
        time.sleep(pause)
    time.sleep(0.05)
    mouse_button(False)


def cursor_pos() -> tuple[int, int]:
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y
