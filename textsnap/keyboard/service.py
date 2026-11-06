"""Qt wrapper around the keyboard hook thread.

Callbacks from the hook thread are re-emitted as Qt signals; because the
service lives on the GUI thread, the connections are queued and every slot
runs on the GUI thread.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from textsnap.keyboard.detector import TriggerConfig
from textsnap.keyboard.keys import describe_trigger, trigger_vks

log = logging.getLogger(__name__)

STOPPED, ACTIVE, DISABLED, ERROR = "stopped", "active", "disabled", "error"


class TriggerService(QObject):
    activated = Signal()
    detector_event = Signal(str, dict)
    escape_pressed = Signal()
    status_changed = Signal(str, str)  # state, human-readable message

    REFRESH_MS = 120_000

    def __init__(self, hook_factory: Callable[..., object] | None = None, parent: QObject | None = None):
        super().__init__(parent)
        if hook_factory is None:
            from textsnap.keyboard.hook import KeyboardHook
            hook_factory = KeyboardHook
        self._hook_factory = hook_factory
        self._hook = None
        self._state = STOPPED
        self._message = "Not started"
        self._description = ""
        self._refresh = QTimer(self)
        self._refresh.setInterval(self.REFRESH_MS)
        self._refresh.timeout.connect(self._refresh_hook)

    @property
    def state(self) -> str:
        return self._state

    @property
    def message(self) -> str:
        return self._message

    @property
    def hook(self):
        return self._hook

    def apply(self, enabled: bool, keys: list[str], hold_ms: int,
              cancel_on_other_input: bool = True, accept_injected: bool = True, hold_back: bool = True) -> None:
        """Start, reconfigure or stop the global trigger."""
        if not enabled:
            self._stop_hook()
            self._set_state(DISABLED, "Global trigger is turned off")
            return
        try:
            config = TriggerConfig(trigger_vks(keys), int(hold_ms), cancel_on_other_input, hold_back)
        except ValueError as exc:
            self._stop_hook()
            self._set_state(ERROR, f"Invalid trigger: {exc}")
            return
        self._description = f"{describe_trigger(keys)}, hold {hold_ms} ms"
        if self._hook is not None and getattr(self._hook, "running", False):
            self._hook.update(config, accept_injected)
            self._set_state(ACTIVE, f"Active: {self._description}")
            return
        self._stop_hook()
        hook = self._hook_factory(self.activated.emit, self._forward_event, self.escape_pressed.emit)
        try:
            hook.start(config, accept_injected)
        except Exception as exc:  # HookInstallError or OSError
            log.error("Global trigger unavailable: %s", exc)
            try:
                hook.stop()
            except Exception:
                pass
            self._set_state(ERROR, f"Global trigger unavailable: {exc}. "
                                   "Use the tray menu or the dashboard to start a capture.")
            return
        self._hook = hook
        self._refresh.start()
        self._set_state(ACTIVE, f"Active: {self._description}")

    def set_watch_escape(self, enabled: bool) -> None:
        if self._hook is not None:
            self._hook.set_watch_escape(enabled)

    def shutdown(self) -> None:
        self._stop_hook()
        self._set_state(STOPPED, "Stopped")

    def _forward_event(self, name: str, info: dict) -> None:
        if name == "config_applied" and self._state == ACTIVE:
            info = dict(info, description=self._description)
        self.detector_event.emit(name, dict(info))

    def _refresh_hook(self) -> None:
        if self._hook is not None:
            self._hook.refresh()

    def _stop_hook(self) -> None:
        self._refresh.stop()
        hook, self._hook = self._hook, None
        if hook is not None:
            hook.stop()

    def _set_state(self, state: str, message: str) -> None:
        self._state, self._message = state, message
        self.status_changed.emit(state, message)
