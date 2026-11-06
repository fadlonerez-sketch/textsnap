"""Long-press detection state machine.

Pure logic with no Windows or Qt dependencies. The hook thread feeds it key
transitions for the configured trigger keys only, plus an anonymous
"other input" notification (another key or a mouse button went down). Timers,
the clock and the physical key state are injected so tests are deterministic.

Rules:
* Activation requires every trigger key to be held, with no other modifier or
  mouse button already held, for ``hold_ms`` without interruption.
* It fires at most once per press; auto-repeat key-downs are ignored.
* Releasing any trigger key before the threshold cancels the pending timer.
* After firing, nothing happens on release (the overlay stays open).
* Another key or mouse button pressed while pending cancels and blocks the
  attempt until all trigger keys are released (so Ctrl+C never triggers).
* A configuration change while trigger keys are held is deferred until they
  are all released.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol


class Scheduler(Protocol):
    def start(self, ms: int) -> int: ...
    def cancel(self, handle: int) -> None: ...


@dataclass(frozen=True)
class TriggerConfig:
    keys: frozenset[int]
    hold_ms: int = 500
    cancel_on_other_input: bool = True
    hold_back: bool = True  # hold back a character trigger key (Spacebar) while pending


# Event names reported through ``on_event``.
PRESSED, ARMED, ACTIVATED, CANCELLED, RELEASED, CONFIG_APPLIED, CONFIG_DEFERRED = (
    "pressed", "armed", "activated", "cancelled", "released", "config_applied", "config_deferred",
)


class LongPressDetector:
    # Auto-repeat delivers key-downs every ~30-500 ms while a key is held. A
    # repeat arriving later than this means the matching key-up was missed
    # (for example during a secure-desktop switch) and the state is stale.
    STALE_REPEAT_S = 1.5

    def __init__(
        self,
        scheduler: Scheduler,
        on_activate: Callable[[], None],
        on_event: Callable[[str, dict], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        is_key_down: Callable[[int], bool] | None = None,
        other_keys_held: Callable[[frozenset[int]], bool] | None = None,
    ):
        self._scheduler = scheduler
        self._on_activate = on_activate
        self._on_event = on_event or (lambda name, info: None)
        self._clock = clock
        self._is_key_down = is_key_down or (lambda vk: True)
        self._other_keys_held = other_keys_held or (lambda keys: False)
        self._config: TriggerConfig | None = None
        self._deferred: TriggerConfig | None | bool = False  # False = nothing deferred
        self._pressed: set[int] = set()
        self._last_seen: dict[int, float] = {}
        self._timer: int | None = None
        self._armed_at = 0.0
        self._fired = False
        self._blocked = False
        self.activation_count = 0

    # -- configuration -------------------------------------------------
    @property
    def config(self) -> TriggerConfig | None:
        return self._config

    @property
    def watched_keys(self) -> frozenset[int]:
        return self._config.keys if self._config else frozenset()

    @property
    def pending(self) -> bool:
        return self._timer is not None

    @property
    def idle(self) -> bool:
        return not self._pressed and self._timer is None

    def configure(self, config: TriggerConfig | None) -> bool:
        """Apply a new trigger (``None`` disables). Returns False if deferred."""
        if self._pressed:
            self._deferred = config
            self._on_event(CONFIG_DEFERRED, {})
            return False
        self._apply(config)
        return True

    def _apply(self, config: TriggerConfig | None) -> None:
        self._cancel_timer()
        self._config = config
        self._deferred = False
        self._clear_state()
        self._on_event(CONFIG_APPLIED, {"enabled": config is not None})

    # -- input ---------------------------------------------------------
    def key_event(self, vk: int, down: bool) -> None:
        if vk not in self.watched_keys:
            return
        now = self._clock()
        if down:
            self._key_down(vk, now)
        else:
            self._key_up(vk, now)

    def _key_down(self, vk: int, now: float) -> None:
        if vk in self._pressed:
            if now - self._last_seen.get(vk, now) <= self.STALE_REPEAT_S:
                self._last_seen[vk] = now
                return  # auto-repeat
            # Stale: we never saw this key's release. Start over.
            self._cancel_timer()
            self._clear_state()
            if self._deferred is not False:
                self._apply(self._deferred)  # type: ignore[arg-type]
                if vk not in self.watched_keys:
                    return
        self._pressed.add(vk)
        self._last_seen[vk] = now
        keys = self.watched_keys
        if not keys or self._pressed != set(keys):
            self._on_event(PRESSED, {"held": len(self._pressed), "needed": len(keys)})
            return
        if self._fired or self._blocked or self._deferred is not False:
            return
        if self._other_keys_held(keys):
            self._blocked = True
            self._on_event(CANCELLED, {"reason": "other_keys_held"})
            return
        assert self._config is not None
        self._armed_at = now
        self._timer = self._scheduler.start(self._config.hold_ms)
        self._on_event(ARMED, {"hold_ms": self._config.hold_ms})

    def _key_up(self, vk: int, now: float) -> None:
        if vk not in self._pressed:
            return  # release of a press that began before we started listening
        self._pressed.discard(vk)
        self._last_seen.pop(vk, None)
        if self._timer is not None:
            held_ms = int((now - self._armed_at) * 1000)
            self._cancel_timer()
            self._on_event(CANCELLED, {"reason": "released_early", "held_ms": held_ms})
        if not self._pressed:
            self._fired = False
            self._blocked = False
            self._on_event(RELEASED, {})
            if self._deferred is not False:
                self._apply(self._deferred)  # type: ignore[arg-type]

    def other_input(self) -> None:
        """Another key or a mouse button was pressed."""
        if not self._pressed or self._fired:
            return
        if self._config is not None and not self._config.cancel_on_other_input:
            return
        self._blocked = True
        if self._timer is not None:
            self._cancel_timer()
            self._on_event(CANCELLED, {"reason": "other_input"})

    def timer_fired(self, handle: int) -> None:
        if handle != self._timer:
            return  # a timer we already cancelled
        self._timer = None
        keys = self.watched_keys
        if not keys or not all(self._is_key_down(vk) for vk in keys):
            # We missed a release; the keys are not physically down any more.
            self._clear_state()
            self._on_event(CANCELLED, {"reason": "not_held"})
            return
        self._fired = True
        self.activation_count += 1
        self._on_event(ACTIVATED, {})
        self._on_activate()

    def reset(self) -> None:
        """Forget all key state (shutdown, session switch, hook reinstall)."""
        self._cancel_timer()
        self._clear_state()
        if self._deferred is not False:
            self._apply(self._deferred)  # type: ignore[arg-type]

    # -- helpers -------------------------------------------------------
    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._scheduler.cancel(self._timer)
            self._timer = None

    def _clear_state(self) -> None:
        self._pressed.clear()
        self._last_seen.clear()
        self._fired = False
        self._blocked = False
