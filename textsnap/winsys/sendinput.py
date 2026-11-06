"""Opt-in automatic paste: one synthesised Ctrl+V into the restored window.

Disabled by default and enabled only after the user confirms. The events
carry TextSnap's tag so its own keyboard hook ignores them.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

from textsnap.keyboard.hook import TEXTSNAP_INPUT_TAG, key_is_down
from textsnap.keyboard.keys import GUARD_VKS

user32 = ctypes.WinDLL("user32", use_last_error=True)
INPUT_KEYBOARD, KEYEVENTF_KEYUP = 1, 0x0002
VK_CONTROL, VK_V = 0x11, 0x56


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT


def _key(vk: int, up: bool) -> INPUT:
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, TEXTSNAP_INPUT_TAG)
    return i


def modifiers_held() -> bool:
    return any(key_is_down(vk) for vk in GUARD_VKS)


def send_paste() -> bool:
    """Send Ctrl+V. Refuses while the user still holds modifiers or buttons."""
    if modifiers_held():
        return False
    seq = (INPUT * 4)(_key(VK_CONTROL, False), _key(VK_V, False), _key(VK_V, True), _key(VK_CONTROL, True))
    return user32.SendInput(4, seq, ctypes.sizeof(INPUT)) == 4
