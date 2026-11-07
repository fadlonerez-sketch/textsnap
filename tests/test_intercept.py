"""Spacebar trigger: hold-back/replay logic with the real detector.

Each test models what the focused application receives: events the hook
blocks are removed, events TextSnap re-sends are added in order.
"""

from __future__ import annotations

import pytest

from textsnap.keyboard.detector import LongPressDetector, TriggerConfig
from textsnap.keyboard.intercept import KeyInterceptor, SyntheticKey
from textsnap.keyboard.keys import VK_LSHIFT, VK_LWIN, VK_RCONTROL, VK_SPACE, trigger_vks

from test_detector import FakeScheduler

SPACE_SCAN = 0x39
WM_LBUTTONDOWN = 0x201
LETTERS = {ord(c): c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


class App:
    """The keyboard/mouse stream as the focused application sees it."""

    def __init__(self):
        self.events: list[tuple] = []

    def typed(self) -> str:
        out = []
        for e in self.events:
            if e[0] == "key" and not e[2]:
                out.append(" " if e[1] == VK_SPACE else LETTERS.get(e[1], "?").lower())
        return "".join(out)


class Harness:
    def __init__(self, keys=("Space",), hold_ms=500, cancel=True, hold_back=True):
        self.now = 0.0
        self.app = App()
        self.activations = 0
        self.modifier_held = False
        self.inject_ok = True
        self.interceptor = KeyInterceptor(self._inject, lambda keys: self.modifier_held, clock=lambda: self.now)
        self.sched = FakeScheduler(lambda: self.now)
        self.detector = LongPressDetector(
            self.sched, self._activate, clock=lambda: self.now,
            is_key_down=lambda vk: self.interceptor.holding(vk) or vk in self.physical,
            other_keys_held=lambda keys: self.modifier_held,
        )
        self.physical: set[int] = set()
        self.interceptor.attach(self.detector)
        self.configure(keys, hold_ms, cancel, hold_back)

    def configure(self, keys, hold_ms=500, cancel=True, hold_back=True):
        applied = self.detector.configure(TriggerConfig(trigger_vks(list(keys)), hold_ms, cancel, hold_back))
        if applied:
            self.interceptor.suppress = hold_back
        return applied

    def _activate(self):
        self.interceptor.on_activated()  # what KeyboardHook._activated does
        self.activations += 1

    def _inject(self, events):
        if not self.inject_ok:
            return False
        for e in events:
            if isinstance(e, SyntheticKey):
                self.app.events.append(("key", e.vk, e.up, "replayed"))
            else:
                self.app.events.append(("mouse", e.message, e.data, "replayed"))
        return True

    # Physical input -------------------------------------------------------------
    def key(self, vk, down, scan=0):
        if down:
            self.physical.add(vk)
        else:
            self.physical.discard(vk)
        blocked = self.interceptor.on_key(vk, scan or (SPACE_SCAN if vk == VK_SPACE else 0), False, down)
        if not blocked:
            self.app.events.append(("key", vk, not down, "real"))
        return blocked

    def tap(self, vk, ms=60):
        self.key(vk, True)
        self.advance(ms)
        self.key(vk, False)

    def click(self):
        blocked = self.interceptor.on_mouse(WM_LBUTTONDOWN, 0)
        if not blocked:
            self.app.events.append(("mouse", WM_LBUTTONDOWN, 0, "real"))
        return blocked

    def advance(self, ms, repeat_vk=None):
        """Let time pass; optionally deliver auto-repeat key-downs every 33 ms."""
        step = 33 if repeat_vk else ms
        elapsed = 0
        while elapsed < ms:
            dt = min(step, ms - elapsed)
            self.now += dt / 1000
            elapsed += dt
            for handle in list(self.sched.active):
                if handle in self.sched.active and self.sched.deadlines[handle] <= self.now + 1e-9:
                    self.sched.active.pop(handle)
                    self.detector.timer_fired(handle)
            if repeat_vk is not None and elapsed < ms:
                self.key(repeat_vk, True)


# ----------------------------------------------------------------- taps and holds
def test_quick_tap_types_exactly_one_space():
    h = Harness()
    assert h.key(VK_SPACE, True) is True  # held back while undecided
    assert h.app.events == []
    h.advance(80)
    assert h.key(VK_SPACE, False) is True  # original release blocked...
    assert h.app.events == [("key", VK_SPACE, False, "replayed"), ("key", VK_SPACE, True, "replayed")]
    assert h.app.typed() == " " and h.activations == 0  # ...and one complete space re-sent


@pytest.mark.parametrize("held_ms", [30, 150, 300, 490])
def test_presses_below_threshold_never_activate(held_ms):
    h = Harness(hold_ms=500)
    h.key(VK_SPACE, True)
    h.advance(held_ms, repeat_vk=VK_SPACE if held_ms > 100 else None)
    h.key(VK_SPACE, False)
    h.advance(2000)
    assert h.activations == 0 and h.app.typed() == " "


def test_long_press_activates_once_and_types_nothing():
    h = Harness(hold_ms=500)
    h.key(VK_SPACE, True)
    h.advance(1500, repeat_vk=VK_SPACE)  # keyboard auto-repeat keeps arriving
    assert h.activations == 1
    assert h.key(VK_SPACE, False) is True  # release after activation is swallowed...
    assert h.app.events == [] and h.activations == 1  # ...no space, no second activation


def test_release_after_activation_does_not_cancel_anything():
    h = Harness()
    h.key(VK_SPACE, True)
    h.advance(600)
    events_before = list(h.app.events)
    h.key(VK_SPACE, False)
    h.advance(1000)
    assert h.activations == 1 and h.app.events == events_before
    assert h.interceptor.mode is None


def test_each_hold_activates_exactly_once():
    h = Harness()
    for _ in range(3):
        h.key(VK_SPACE, True)
        h.advance(700, repeat_vk=VK_SPACE)
        h.key(VK_SPACE, False)
        h.advance(100)
    assert h.activations == 3 and h.app.typed() == ""


def test_physical_state_reported_while_held_back():
    """GetAsyncKeyState never sees a blocked key; the detector must ask the interceptor."""
    h = Harness()
    h.key(VK_SPACE, True)
    h.physical.discard(VK_SPACE)  # model: the OS key state does not know about it
    assert h.interceptor.holding(VK_SPACE)
    h.advance(550)
    assert h.activations == 1


# ----------------------------------------------------------------- typing is preserved
def test_normal_typing_text_is_unchanged():
    h = Harness()
    for ch in "hello world from textsnap":
        h.tap(VK_SPACE if ch == " " else ord(ch.upper()), 70)
        h.advance(40)
    assert h.app.typed() == "hello world from textsnap" and h.activations == 0


def test_fast_typing_rollover_keeps_order():
    """Next letter pressed before Space is released: ' ' must still come before 'b'."""
    h = Harness()
    h.tap(ord("A"))
    h.key(VK_SPACE, True)
    h.advance(40)
    assert h.key(ord("B"), True) is True  # re-sent behind the held-back Space
    h.advance(30)
    assert h.key(VK_SPACE, False) is False  # the rest of this press passes normally
    h.key(ord("B"), False)
    h.advance(2000)
    assert h.app.typed() == "a b" and h.activations == 0
    kinds = [(e[1], e[2]) for e in h.app.events]
    assert kinds.index((VK_SPACE, False)) < kinds.index((ord("B"), False)) < kinds.index((VK_SPACE, True))


def test_other_key_during_hold_cancels_pending_activation():
    h = Harness(cancel=True)
    h.key(VK_SPACE, True)
    h.advance(200, repeat_vk=VK_SPACE)
    h.key(ord("X"), True)
    h.advance(1000, repeat_vk=VK_SPACE)  # still held well past the threshold
    h.key(ord("X"), False)
    h.key(VK_SPACE, False)
    assert h.activations == 0
    assert h.app.typed().startswith(" x")  # space first, then x; repeats pass once the press is released to the app


def test_cancellation_disabled_still_preserves_order():
    h = Harness(cancel=False)
    h.key(VK_SPACE, True)
    h.key(ord("B"), True)
    h.key(ord("B"), False)
    h.advance(600)
    assert h.activations == 1  # the user chose not to cancel on other keys
    assert h.app.typed() == " b"  # but the typed text is still correct
    assert h.key(VK_SPACE, False) is False


def test_mouse_click_during_hold_replays_space_first():
    """Space+click (e.g. panning) keeps its order: Space down, then the click."""
    h = Harness()
    h.key(VK_SPACE, True)
    h.advance(100)
    assert h.click() is True
    assert h.app.events == [("key", VK_SPACE, False, "replayed"), ("mouse", WM_LBUTTONDOWN, 0, "replayed")]
    h.advance(1000)
    assert h.key(VK_SPACE, False) is False and h.activations == 0


def test_modifier_shortcuts_are_never_held_back():
    """Win+Space (input language), Ctrl+Space, Shift+Space, Alt+Space pass untouched."""
    h = Harness()
    h.modifier_held = True
    assert h.key(VK_SPACE, True) is False
    h.advance(1000, repeat_vk=VK_SPACE)
    assert h.key(VK_SPACE, False) is False
    assert h.activations == 0
    assert all(e[3] == "real" for e in h.app.events)


def test_modifier_pressed_while_space_held_is_ordered():
    h = Harness()
    h.key(VK_SPACE, True)
    assert h.key(VK_LSHIFT, True) is True
    assert [(e[1], e[2]) for e in h.app.events] == [(VK_SPACE, False), (VK_LSHIFT, False)]
    h.key(VK_LSHIFT, False)
    h.key(VK_SPACE, False)
    h.advance(1000)
    assert h.activations == 0


# ----------------------------------------------------------------- configuration
def test_hold_back_disabled_passes_every_event():
    h = Harness(hold_back=False)
    assert h.key(VK_SPACE, True) is False
    h.advance(600)
    assert h.activations == 1  # trigger still works
    assert h.key(VK_SPACE, False) is False
    assert all(e[3] == "real" for e in h.app.events)


@pytest.mark.parametrize("keys,vk", [(("RCtrl",), VK_RCONTROL), (("LCtrl", "LShift"), None)])
def test_other_triggers_are_never_held_back(keys, vk):
    h = Harness(keys=keys)
    assert h.interceptor.target_vk() is None
    assert h.key(VK_SPACE, True) is False and h.key(VK_SPACE, False) is False
    if vk:
        assert h.key(vk, True) is False
        h.advance(600)
        assert h.activations == 1


def test_changing_trigger_from_space_to_right_ctrl():
    h = Harness()
    h.tap(VK_SPACE)
    assert h.configure(("RCtrl",))
    assert h.key(VK_SPACE, True) is False  # Space is an ordinary key again
    h.key(VK_SPACE, False)
    h.key(VK_RCONTROL, True)
    h.advance(600)
    h.key(VK_RCONTROL, False)
    assert h.activations == 1
    assert h.configure(("Space",))
    h.key(VK_SPACE, True)
    h.advance(600)
    assert h.activations == 2


def test_trigger_change_while_space_held_is_deferred():
    h = Harness()
    h.key(VK_SPACE, True)
    assert h.configure(("RCtrl",)) is False  # applied only after release
    h.advance(600)
    assert h.activations == 1
    h.key(VK_SPACE, False)
    assert h.detector.watched_keys == trigger_vks(["RCtrl"])
    assert h.key(VK_SPACE, True) is False


def test_disabled_trigger_holds_nothing_back():
    h = Harness()
    h.detector.configure(None)
    assert h.key(VK_SPACE, True) is False and h.key(VK_SPACE, False) is False
    assert h.activations == 0


# ----------------------------------------------------------------- robustness
def test_missed_release_recovers():
    h = Harness()
    h.key(VK_SPACE, True)
    h.advance(600)
    assert h.activations == 1
    h.now += 30  # the release was never seen (e.g. secure desktop)
    h.key(VK_SPACE, True)
    h.advance(80)
    h.key(VK_SPACE, False)
    assert h.app.typed() == " " and h.activations == 1


def test_reset_while_held_back_releases_the_key_to_the_app():
    h = Harness()
    h.key(VK_SPACE, True)
    h.interceptor.reset()  # hook stopping or being reinstalled
    h.detector.reset()
    assert h.app.events == [("key", VK_SPACE, False, "replayed")]
    assert h.key(VK_SPACE, False) is False  # the matching release reaches the app


def test_failed_replay_is_counted():
    h = Harness()
    h.inject_ok = False
    h.tap(VK_SPACE)
    assert h.interceptor.replay_failures == 1


def test_win_key_detection_uses_guard_probe():
    seen = []
    h = Harness()
    h.interceptor._guard_keys_held = lambda keys: seen.append(keys) or VK_LWIN not in keys
    assert h.key(VK_SPACE, True) is False  # a guard key was reported held
    assert seen and VK_SPACE in seen[0]
