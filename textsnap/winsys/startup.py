"""Opt-in "Start with Windows" via the per-user Run key.

Only HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\TextSnap is
touched, and only when the user turns the option on (after confirming).
Turning it off deletes that one value.
"""

from __future__ import annotations

import subprocess
from typing import Protocol

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TextSnap"


class RegistryBackend(Protocol):
    def get(self, key: str, name: str) -> str | None: ...
    def set(self, key: str, name: str, value: str) -> None: ...
    def delete(self, key: str, name: str) -> None: ...


class WinRegBackend:
    def get(self, key: str, name: str) -> str | None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                value, _ = winreg.QueryValueEx(k, name)
                return str(value)
        except OSError:
            return None

    def set(self, key: str, name: str, value: str) -> None:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)

    def delete(self, key: str, name: str) -> None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
        except FileNotFoundError:
            pass


class StartupManager:
    def __init__(self, command: list[str], backend: RegistryBackend | None = None):
        self.command = subprocess.list2cmdline(command + ["--minimized"])
        self.backend = backend or WinRegBackend()

    def is_enabled(self) -> bool:
        return self.backend.get(RUN_KEY, VALUE_NAME) is not None

    def points_here(self) -> bool:
        return self.backend.get(RUN_KEY, VALUE_NAME) == self.command

    def enable(self) -> None:
        self.backend.set(RUN_KEY, VALUE_NAME, self.command)

    def disable(self) -> None:
        self.backend.delete(RUN_KEY, VALUE_NAME)
