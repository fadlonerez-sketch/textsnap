"""Hold-back logic for trigger keys that type characters (the Spacebar).

Windows types a space the moment Space goes down and auto-repeats it while
the key is held, so a long-press on Space cannot be detected without holding
the key back. This module decides, per keyboard or mouse event, whether the
hook should block it, and which events must be re-sent so the focused
application still receives exactly what the user typed, in order:

* Space pressed while no modifier or mouse button is held: held back while
  the hold is pending (the detector is armed).
* Released before the threshold (a tap): one Space press + release is
  re-sent, so the application gets a normal space (on release, not on press).
* Another key, mouse button or wheel while held back: Space is re-sent first,
  then that key/click is re-sent in place of the original, preserving order
  for fast typing and Space+click. The rest of that press passes normally.
* Held past the threshold: the overlay is activated once; the auto-repeats and
  the release are swallowed, so no space is typed.
* Space with a modifier or mouse button already held (Win+Space, Ctrl+Space,
  Shift+Space, Alt+Space, ...) is never held back.

Pure logic: the injector, clock and modifier probe are injected, so every
sequence is unit-tested without touching the real keyboard.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Sequence

from textsnap.keyboard.detector import LongPressDetector
from textsnap.keyboard.keys import VK_SPACE

# Trigger keys that produce input in applications and are therefore held back.
INTERCEPTABLE = frozenset({VK_SPACE})

HELD, PASS, CONSUMED = "held", "pass", "consumed"


@dataclass(frozen=True)
class SyntheticKey:
    vk: int
    scan: int
    extended: bool
    up: bool


@dataclass(frozen=True)
class SyntheticMouse:
    message: int  # WM_LBUTTONDOWN, WM_MOUSEWHEEL, ...
    data: int  # wheel delta or XBUTTON number


Synthetic = SyntheticKey | SyntheticMouse


class KeyInterceptor:
    STALE_S = 1.5  # a repeat arriving later than this means the release was missed

    def __init__(
        self,
        inject: Callable[[Sequence[Synthetic]], bool],
        guard_keys_held: Callable[[frozenset[int]], bool],
        clock: Callable[[], float] = time.monotonic,
    ):
        self._inject = inject
        self._guard_keys_held = guard_keys_held
        self._clock = clock
        self.detector: LongPressDetector | None = None
        self.suppress = True
        self.mode: str | None = None  # None, HELD, PASS or CONSUMED for the current press
        self._vk = 0
        self._scan = 0
        self._extended = False
        self._last = 0.0
        self.replay_failures = 0

    def attach(self, detector: LongPressDetector) -> None:
        self.detector = detector

    # -- queries -------------------------------------------------------------
    def target_vk(self) -> int | None:
        """The trigger key that is held back, or None when nothing is."""
        d = self.detector
        if not self.suppress or d is None or d.config is None or len(d.config.keys) != 1:
            return None
        vk = next(iter(d.config.keys))
        return vk if vk in INTERCEPTABLE else None

    def holding(self, vk: int) -> bool:
        """True while the key is physically down but hidden from applications."""
        return self.mode in (HELD, CONSUMED) and vk == self._vk

    # -- events (hook thread) --------------------------------------------------
    def on_key(self, vk: int, scan: int, extended: bool, down: bool) -> bool:
        """Feed one key transition. Returns True when the hook must block it."""
        d = self.detector
        if d is None:
            return False
        now = self._clock()
        if self.mode is not None and vk == self._vk:
            if down and now - self._last <= self.STALE_S:
                self._last = now
                d.key_event(vk, True)  # auto-repeat
                return self.mode in (HELD, CONSUMED)
            if not down:
                mode, self.mode = self.mode, None
                d.key_event(vk, False)
                if mode == HELD:  # a tap: give the application its space now
                    self._replay([self._key(up=False), self._key(up=True)])
                    return True
                return mode == CONSUMED
            self.mode = None  # the release was missed; this is a new press
        if down and self.mode is None and vk == self.target_vk():
            self._vk, self._scan, self._extended, self._last = vk, scan, extended, now
            if self._guard_keys_held(d.watched_keys):
                self.mode = PASS  # Win+Space, Ctrl+Space, ... : never interfere
                d.key_event(vk, True)
                return False
            d.key_event(vk, True)
            self.mode = HELD if d.pending else PASS
            return self.mode == HELD
        if vk in d.watched_keys:
            d.key_event(vk, down)
            return False
        if down:
            d.other_input()
            if self.mode == HELD:
                self.mode = PASS
                self._replay([self._key(up=False), SyntheticKey(vk, scan, extended, up=False)])
                return True
        return False

    def on_mouse(self, message: int, data: int) -> bool:
        """A mouse button or wheel event. Returns True when the hook must block it."""
        d = self.detector
        if d is None:
            return False
        d.other_input()
        if self.mode == HELD:
            self.mode = PASS
            self._replay([self._key(up=False), SyntheticMouse(message, data)])
            return True
        return False

    def on_activated(self) -> None:
        if self.mode == HELD:
            self.mode = CONSUMED

    def reset(self) -> None:
        """Hook stopping or being reinstalled: never leave a key hidden."""
        if self.mode == HELD:
            self._replay([self._key(up=False)])
        self.mode = None

    # -- helpers -----------------------------------------------------------------
    def _key(self, up: bool) -> SyntheticKey:
        return SyntheticKey(self._vk, self._scan, self._extended, up)

    def _replay(self, events: list[Synthetic]) -> None:
        if not self._inject(events):
            self.replay_failures += 1
