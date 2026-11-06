"""Long-press state machine, driven by a deterministic fake event source."""

from __future__ import annotations

import pytest

from textsnap.keyboard import detector as det
from textsnap.keyboard.detector import LongPressDetector, TriggerConfig
from textsnap.keyboard.keys import VK_LCONTROL, VK_LSHIFT, VK_RCONTROL

VK_C = 0x43


class FakeScheduler:
    """Records one-shot timers as {handle: delay_ms} plus absolute deadlines."""

    def __init__(self, clock):
        self.clock = clock
        self.active: dict[int, int] = {}
        self.deadlines: dict[int, float] = {}
        self._next = 1
        self.started = 0

    def start(self, ms: int) -> int:
        handle = self._next
        self._next += 1
        self.active[handle] = ms
        self.deadlines[handle] = self.clock() + ms / 1000.0
        self.started += 1
        return handle

    def cancel(self, handle: int) -> None:
        self.active.pop(handle, None)


class Harness:
    """Fake keyboard: tracks physical state, time and pending timers."""

    def __init__(self, keys=(VK_RCONTROL,), hold_ms=500, cancel_on_other=True):
        self.now = 0.0
        self.down: set[int] = set()
        self.extra_held = False
        self.activations = 0
        self.events: list[tuple[str, dict]] = []
        self.sched = FakeScheduler(lambda: self.now)
        self.d = LongPressDetector(
            self.sched, self._activate, lambda n, i: self.events.append((n, i)),
            clock=lambda: self.now, is_key_down=lambda vk: vk in self.down,
            other_keys_held=lambda keys: self.extra_held,
        )
        self.d.configure(TriggerConfig(frozenset(keys), hold_ms, cancel_on_other))

    def _activate(self):
        self.activations += 1

    def press(self, vk):
        self.down.add(vk)
        self.d.key_event(vk, True)

    def release(self, vk):
        self.down.discard(vk)
        self.d.key_event(vk, False)

    def advance(self, ms):
        """Move time forward, firing any timer whose deadline passed."""
        self.now += ms / 1000.0
        for handle in list(self.sched.active):
            if handle in self.sched.active and self.sched.deadlines[handle] <= self.now + 1e-9:
                self.sched.active.pop(handle)
                self.d.timer_fired(handle)

    def names(self):
        return [n for n, _ in self.events]


def test_short_press_does_not_activate():
    h = Harness()
    h.press(VK_RCONTROL)
    h.advance(80)
    h.release(VK_RCONTROL)
    h.advance(1000)
    assert h.activations == 0
    assert not h.sched.active


def test_hold_below_threshold_does_not_activate():
    h = Harness(hold_ms=500)
    h.press(VK_RCONTROL)
    h.advance(450)
    h.release(VK_RCONTROL)
    assert h.activations == 0
    cancelled = [i for n, i in h.events if n == det.CANCELLED]
    assert cancelled and cancelled[-1]["reason"] == "released_early"


def test_hold_beyond_threshold_activates_exactly_once():
    h = Harness(hold_ms=500)
    h.press(VK_RCONTROL)
    h.advance(500)
    assert h.activations == 1
    h.advance(2000)
    assert h.activations == 1


def test_release_cancels_pending_timer():
    h = Harness()
    h.press(VK_RCONTROL)
    assert h.d.pending and len(h.sched.active) == 1
    h.release(VK_RCONTROL)
    assert not h.d.pending and not h.sched.active


def test_key_up_after_activation_does_nothing():
    """Releasing the trigger must not dismiss (or re-trigger) the overlay."""
    h = Harness()
    h.press(VK_RCONTROL)
    h.advance(600)
    events_before = len(h.events)
    h.release(VK_RCONTROL)
    assert h.activations == 1
    assert h.names()[events_before:] == [det.RELEASED]


def test_auto_repeat_does_not_restart_or_reactivate():
    h = Harness(hold_ms=500)
    h.press(VK_RCONTROL)
    for _ in range(10):
        h.now += 0.03
        h.d.key_event(VK_RCONTROL, True)  # auto-repeat key-downs
    assert h.sched.started == 1
    h.advance(500)
    for _ in range(50):
        h.now += 0.03
        h.d.key_event(VK_RCONTROL, True)
    h.advance(1000)
    assert h.activations == 1


def test_second_hold_after_release_activates_again():
    h = Harness()
    for _ in range(3):
        h.press(VK_RCONTROL)
        h.advance(600)
        h.release(VK_RCONTROL)
    assert h.activations == 3


def test_other_key_while_holding_cancels_and_blocks():
    """Right Ctrl + C (a shortcut) must never open the overlay."""
    h = Harness()
    h.press(VK_RCONTROL)
    h.advance(100)
    h.d.other_input()  # C pressed
    # Auto-repeat key-downs while still held must not re-arm the attempt.
    for _ in range(40):
        h.now += 0.03
        h.d.key_event(VK_RCONTROL, True)
    assert not h.d.pending
    h.advance(5000)
    assert h.activations == 0
    h.release(VK_RCONTROL)
    h.press(VK_RCONTROL)
    h.advance(600)
    assert h.activations == 1


def test_other_input_ignored_when_option_disabled():
    h = Harness(cancel_on_other=False)
    h.press(VK_RCONTROL)
    h.d.other_input()
    h.advance(600)
    assert h.activations == 1


def test_modifier_already_held_blocks_arming():
    h = Harness()
    h.extra_held = True  # e.g. Shift held, then Right Ctrl: a Ctrl+Shift shortcut
    h.press(VK_RCONTROL)
    h.advance(1000)
    assert h.activations == 0
    assert ("cancelled", {"reason": "other_keys_held"}) in h.events


def test_left_and_right_ctrl_are_distinct():
    h = Harness(keys=(VK_RCONTROL,))
    h.press(VK_LCONTROL)
    h.advance(1000)
    assert h.activations == 0
    assert h.events == [(det.CONFIG_APPLIED, {"enabled": True})]  # left ctrl ignored entirely

    h2 = Harness(keys=(VK_LCONTROL,))
    h2.press(VK_RCONTROL)
    h2.advance(1000)
    assert h2.activations == 0
    h2.press(VK_LCONTROL)
    h2.advance(500)
    assert h2.activations == 1


def test_combination_requires_all_keys():
    h = Harness(keys=(VK_LCONTROL, VK_LSHIFT))
    h.press(VK_LCONTROL)
    h.advance(1000)
    assert h.activations == 0 and not h.d.pending
    h.press(VK_LSHIFT)
    assert h.d.pending
    h.advance(500)
    assert h.activations == 1


def test_combination_release_of_one_key_cancels():
    h = Harness(keys=(VK_LCONTROL, VK_LSHIFT))
    h.press(VK_LSHIFT)
    h.press(VK_LCONTROL)
    h.advance(200)
    h.release(VK_LSHIFT)
    h.advance(1000)
    assert h.activations == 0
    assert not h.sched.active


def test_combination_any_order_and_other_key_blocks():
    h = Harness(keys=(VK_LCONTROL, VK_LSHIFT))
    h.press(VK_LSHIFT)
    h.d.other_input()  # typing a capital letter before Ctrl joins
    h.press(VK_LCONTROL)
    h.advance(1000)
    assert h.activations == 0


def test_timer_fire_after_missed_release_is_discarded():
    """If the key-up was missed (secure desktop), the physical check stops activation."""
    h = Harness()
    h.press(VK_RCONTROL)
    h.down.discard(VK_RCONTROL)  # released, but the hook never saw it
    h.advance(600)
    assert h.activations == 0
    assert ("cancelled", {"reason": "not_held"}) in h.events
    h.press(VK_RCONTROL)  # state was reset: a fresh press works
    h.advance(600)
    assert h.activations == 1


def test_stale_pressed_state_recovers():
    h = Harness()
    h.press(VK_RCONTROL)
    h.advance(600)
    assert h.activations == 1
    # key-up missed; much later the key is pressed again
    h.now += 30
    h.d.key_event(VK_RCONTROL, True)
    h.advance(600)
    assert h.activations == 2


def test_stale_timer_handle_is_ignored():
    h = Harness()
    h.press(VK_RCONTROL)
    first = next(iter(h.sched.active))
    h.release(VK_RCONTROL)
    h.d.timer_fired(first)  # a WM_TIMER that was already queued when we cancelled
    assert h.activations == 0


def test_config_change_while_held_is_deferred():
    h = Harness(keys=(VK_RCONTROL,))
    h.press(VK_RCONTROL)
    applied = h.d.configure(TriggerConfig(frozenset({VK_LCONTROL}), 300))
    assert applied is False
    assert h.d.config.keys == frozenset({VK_RCONTROL})
    h.release(VK_RCONTROL)
    assert h.d.config.keys == frozenset({VK_LCONTROL})
    h.press(VK_LCONTROL)
    h.advance(300)
    assert h.activations == 1


def test_config_change_cleans_old_state():
    h = Harness()
    h.d.configure(TriggerConfig(frozenset({VK_LCONTROL}), 400))
    assert not h.sched.active
    h.press(VK_RCONTROL)
    h.advance(1000)
    assert h.activations == 0
    h.press(VK_LCONTROL)
    h.advance(400)
    assert h.activations == 1


def test_disable_with_none_config():
    h = Harness()
    h.d.configure(None)
    h.press(VK_RCONTROL)
    h.advance(1000)
    assert h.activations == 0 and h.d.watched_keys == frozenset()


def test_reset_cancels_pending_timer():
    h = Harness()
    h.press(VK_RCONTROL)
    h.d.reset()
    assert not h.sched.active and h.d.idle
    h.advance(1000)
    assert h.activations == 0


def test_unmatched_key_up_is_ignored():
    h = Harness()
    h.d.key_event(VK_RCONTROL, False)
    assert h.activations == 0 and h.d.idle


@pytest.mark.parametrize("hold", [200, 500, 1500, 3000])
def test_threshold_is_respected(hold):
    h = Harness(hold_ms=hold)
    h.press(VK_RCONTROL)
    assert list(h.sched.active.values()) == [hold]
