"""Clipboard access with retries.

Text is placed as CF_UNICODETEXT (plain Unicode, never HTML-only). Another
process may hold the clipboard open for a moment (clipboard managers, RDP),
so opening is retried with a short back-off and a failure is reported to
the caller instead of being silently ignored.

Optionally the text can be kept out of Windows clipboard history (Win+V)
and cloud clipboard sync with the documented "CanIncludeInClipboardHistory"
and "CanUploadToCloudClipboard" formats.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import time
from dataclasses import dataclass
from typing import Callable, Protocol

log = logging.getLogger(__name__)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class ClipboardBackend(Protocol):
    def open(self, owner: int) -> bool: ...
    def close(self) -> None: ...
    def empty(self) -> bool: ...
    def set_text(self, text: str) -> bool: ...
    def set_dword_format(self, name: str, value: int) -> bool: ...
    def get_text(self) -> str | None: ...


class Win32ClipboardBackend:
    def __init__(self) -> None:
        self.user32 = u = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = k = ctypes.WinDLL("kernel32", use_last_error=True)
        u.OpenClipboard.argtypes = [wt.HWND]
        u.OpenClipboard.restype = wt.BOOL
        u.CloseClipboard.restype = wt.BOOL
        u.EmptyClipboard.restype = wt.BOOL
        u.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
        u.SetClipboardData.restype = wt.HANDLE
        u.GetClipboardData.argtypes = [wt.UINT]
        u.GetClipboardData.restype = wt.HANDLE
        u.IsClipboardFormatAvailable.argtypes = [wt.UINT]
        u.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
        u.RegisterClipboardFormatW.restype = wt.UINT
        k.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
        k.GlobalAlloc.restype = wt.HGLOBAL
        k.GlobalLock.argtypes = [wt.HGLOBAL]
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalUnlock.argtypes = [wt.HGLOBAL]
        k.GlobalFree.argtypes = [wt.HGLOBAL]
        k.GlobalFree.restype = wt.HGLOBAL

    def open(self, owner: int) -> bool:
        return bool(self.user32.OpenClipboard(owner or None))

    def close(self) -> None:
        self.user32.CloseClipboard()

    def empty(self) -> bool:
        return bool(self.user32.EmptyClipboard())

    def _set_bytes(self, fmt: int, data: bytes) -> bool:
        handle = self.kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ptr = self.kernel32.GlobalLock(handle)
        if not ptr:
            self.kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(ptr, data, len(data))
        self.kernel32.GlobalUnlock(handle)
        if not self.user32.SetClipboardData(fmt, handle):
            self.kernel32.GlobalFree(handle)  # ownership stays with us on failure
            return False
        return True

    def set_text(self, text: str) -> bool:
        return self._set_bytes(CF_UNICODETEXT, text.encode("utf-16-le") + b"\x00\x00")

    def set_dword_format(self, name: str, value: int) -> bool:
        fmt = self.user32.RegisterClipboardFormatW(name)
        return bool(fmt) and self._set_bytes(fmt, int(value).to_bytes(4, "little"))

    def get_text(self) -> str | None:
        if not self.user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = self.user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = self.kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            self.kernel32.GlobalUnlock(handle)


@dataclass
class ClipboardResult:
    ok: bool
    attempts: int
    error: str = ""


class ClipboardService:
    def __init__(
        self,
        backend: ClipboardBackend | None = None,
        owner: Callable[[], int] | None = None,
        attempts: int = 10,
        delay_s: float = 0.015,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.backend = backend or Win32ClipboardBackend()
        self._owner = owner or (lambda: 0)
        self.attempts = attempts
        self.delay_s = delay_s
        self._sleep = sleep

    def _open(self) -> int:
        """Open the clipboard; returns the attempt number, or 0 when it stayed locked."""
        for attempt in range(1, self.attempts + 1):
            if self.backend.open(self._owner()):
                return attempt
            if attempt < self.attempts:
                self._sleep(self.delay_s * attempt)
        return 0

    def set_text(self, text: str, exclude_from_history: bool = False) -> ClipboardResult:
        attempt = self._open()
        if not attempt:
            log.warning("Clipboard stayed locked by another application after %d attempts", self.attempts)
            return ClipboardResult(False, self.attempts, "The clipboard is in use by another application. "
                                   "Use Copy in the result window to try again.")
        try:
            if not self.backend.empty() or not self.backend.set_text(text):
                log.warning("Writing to the clipboard failed")
                return ClipboardResult(False, attempt, "Windows refused the clipboard update.")
            if exclude_from_history:
                self.backend.set_dword_format("CanIncludeInClipboardHistory", 0)
                self.backend.set_dword_format("CanUploadToCloudClipboard", 0)
            return ClipboardResult(True, attempt)
        finally:
            self.backend.close()

    def get_text(self) -> str | None:
        if not self._open():
            return None
        try:
            return self.backend.get_text()
        finally:
            self.backend.close()
