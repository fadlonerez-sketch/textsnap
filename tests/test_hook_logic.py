"""KeyboardHook callbacks without installing a real hook (no OS input involved)."""

from __future__ import annotations

import ctypes

from textsnap.keyboard import hook as hk
from textsnap.keyboard.detector import LongPressDetector, TriggerConfig
from textsnap.keyboard.keys import VK_SPACE, trigger_vks

from test_detector import FakeScheduler


def make_hook(keys=("Space",), accept_injected=True):
    sent = []
    h = hk.KeyboardHook(lambda: None)
    h._accept_injected = accept_injected
    h._interceptor._inject = lambda events: sent.append(list(events)) or True
    h._interceptor._guard_keys_held = lambda keys: False
    now = [0.0]
    d = LongPressDetector(FakeScheduler(lambda: now[0]), h._activated, clock=lambda: now[0],
                          is_key_down=lambda vk: h._interceptor.holding(vk))
    h._detector = d
    h._interceptor.attach(d)
    h._apply_config(TriggerConfig(trigger_vks(list(keys)), 500, True, True))
    return h, sent


def test_space_press_is_blocked_and_tap_replayed():
    h, sent = make_hook()
    assert h._handle_key(VK_SPACE, 0x39, 0, 0, hk.WM_KEYDOWN) is True
    assert h._handle_key(VK_SPACE, 0x39, 0, 0, hk.WM_KEYUP) is True
    assert [(e.vk, e.scan, e.up) for e in sent[0]] == [(VK_SPACE, 0x39, False), (VK_SPACE, 0x39, True)]


def test_textsnap_tagged_input_passes_untouched():
    h, sent = make_hook()
    assert h._handle_key(VK_SPACE, 0x39, hk.LLKHF_INJECTED, hk.TEXTSNAP_INPUT_TAG, hk.WM_KEYDOWN) is False
    assert sent == [] and h._interceptor.mode is None


def test_injected_input_ignored_when_setting_off():
    h, _ = make_hook(accept_injected=False)
    assert h._handle_key(VK_SPACE, 0x39, hk.LLKHF_INJECTED, 0, hk.WM_KEYDOWN) is False
    assert h._handle_key(VK_SPACE, 0x39, 0, 0, hk.WM_KEYDOWN) is True  # physical keys still work


def test_hold_back_off_never_blocks():
    h, _ = make_hook()
    h._apply_config(TriggerConfig(trigger_vks(["Space"]), 500, True, False))
    assert h._handle_key(VK_SPACE, 0x39, 0, 0, hk.WM_KEYDOWN) is False


def test_mouse_click_during_hold_is_reordered():
    h, sent = make_hook()
    h._handle_key(VK_SPACE, 0x39, 0, 0, hk.WM_KEYDOWN)
    m = hk.MSLLHOOKSTRUCT()
    assert h._mouse_proc(0, 0x201, ctypes.addressof(m)) == 1  # blocked, re-sent after Space
    assert sent[0][0].vk == VK_SPACE and sent[0][1].message == 0x201


def test_wheel_delta_is_signed():
    h, sent = make_hook()
    h._handle_key(VK_SPACE, 0x39, 0, 0, hk.WM_KEYDOWN)
    m = hk.MSLLHOOKSTRUCT()
    m.mouseData = (0x10000 - 120) << 16  # WHEEL_DELTA * -1
    h._mouse_proc(0, 0x20A, ctypes.addressof(m))
    assert sent[0][1].data == -120


def test_send_synthetic_builds_tagged_events(monkeypatch):
    captured = {}

    def fake_send(n, arr, size):
        captured["events"] = [(arr[i].type, arr[i].u.ki.wVk, arr[i].u.ki.dwFlags, arr[i].u.ki.dwExtraInfo)
                              for i in range(n)]
        return n

    monkeypatch.setattr(hk.user32, "SendInput", fake_send)
    from textsnap.keyboard.intercept import SyntheticKey
    assert hk.send_synthetic([SyntheticKey(VK_SPACE, 0x39, False, False), SyntheticKey(VK_SPACE, 0x39, False, True)])
    assert captured["events"] == [(1, VK_SPACE, 0, hk.TEXTSNAP_INPUT_TAG),
                                  (1, VK_SPACE, hk.KEYEVENTF_KEYUP, hk.TEXTSNAP_INPUT_TAG)]
