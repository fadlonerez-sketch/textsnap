"""One TextSnap per user session.

A named mutex decides which process is the primary instance (so two
processes can never both install the trigger hook). A QLocalServer in the
primary receives commands such as "show" or "capture" from later launches.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import getpass
import hashlib
import os

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
ERROR_ALREADY_EXISTS = 183
ERROR_ACCESS_DENIED = 5
ENV_INSTANCE = "TEXTSNAP_INSTANCE_ID"


def instance_key() -> str:
    """Per-user key; tests set TEXTSNAP_INSTANCE_ID to run isolated instances."""
    seed = os.environ.get(ENV_INSTANCE) or getpass.getuser()
    return "TextSnap-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


class InstanceLock:
    def __init__(self, key: str | None = None):
        self.key = key or instance_key()
        self._handle = None

    def acquire(self) -> bool:
        """True when this process is the only instance."""
        handle = kernel32.CreateMutexW(None, False, "Local\\" + self.key)
        error = ctypes.get_last_error()
        if not handle:
            # ACCESS_DENIED: the mutex exists but belongs to an elevated instance.
            return error != ERROR_ACCESS_DENIED
        if error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None
