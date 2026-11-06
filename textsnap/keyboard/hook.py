"""Low-level keyboard hook running on its own thread.

The thread owns a Win32 message loop, the WH_KEYBOARD_LL hook, the hold
timers (``SetTimer`` thread timers), the :class:`LongPressDetector` and the
:class:`KeyInterceptor`. The hook callback only classifies the event and
updates that state; it never logs keys. Every event is passed on with
``CallNextHookEx`` except one case: when the trigger is the Spacebar, a
plain Space press is held back while the hold is pending and re-sent (in
order) if it turns out to be a tap or the start of typing - see
intercept.py. A WH_MOUSE_LL hook is installed only while a hold is pending,
so mouse clicks or wheel turns can cancel it (Ctrl+wheel zoom must not open
the overlay); it is removed as soon as the hold resolves.

Results leave the thread through plain callbacks; the Qt wrapper turns them
into queued signals.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
import time
from typing import Callable

from textsnap.keyboard import detector as det
from textsnap.keyboard.detector import LongPressDetector, TriggerConfig
from textsnap.keyboard.intercept import KeyInterceptor, Synthetic, SyntheticKey, SyntheticMouse
from textsnap.keyboard.keys import GUARD_VKS, VK_ESCAPE, is_altgr_fake_ctrl, normalize_vk

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)

WH_KEYBOARD_LL, WH_MOUSE_LL, HC_ACTION = 13, 14, 0
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
WM_TIMER, WM_QUIT, WM_USER, WM_APP = 0x113, 0x12, 0x400, 0x8000
WM_APP_CONFIG, WM_APP_MOUSE, WM_APP_REHOOK = WM_APP + 1, WM_APP + 2, WM_APP + 3
PM_NOREMOVE = 0
LLKHF_INJECTED = 0x10
MOUSE_CANCEL_MESSAGES = frozenset({0x201, 0x204, 0x207, 0x20B, 0x20A, 0x20E})  # button downs, wheels

# dwExtraInfo tag on input TextSnap itself synthesises (opt-in auto-paste).
TEXTSNAP_INPUT_TAG = 0x54534E50  # "TSNP"


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
LLKHF_EXTENDED = 0x01
MOUSE_FLAGS = {0x201: 0x0002, 0x204: 0x0008, 0x207: 0x0020, 0x20B: 0x0080, 0x20A: 0x0800, 0x20E: 0x1000}
user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
user32.SendInput.restype = wt.UINT


def send_synthetic(events) -> bool:
    """Re-send held-back input, tagged so TextSnap's own hooks ignore it."""
    arr = (_INPUT * len(events))()
    for i, e in enumerate(events):
        if isinstance(e, SyntheticKey):
            flags = (KEYEVENTF_EXTENDEDKEY if e.extended else 0) | (KEYEVENTF_KEYUP if e.up else 0)
            arr[i].type = INPUT_KEYBOARD
            arr[i].u.ki = _KEYBDINPUT(e.vk, e.scan, flags, 0, TEXTSNAP_INPUT_TAG)
        else:
            arr[i].type = INPUT_MOUSE
            arr[i].u.mi = _MOUSEINPUT(0, 0, e.data & 0xFFFFFFFF, MOUSE_FLAGS[e.message], 0, TEXTSNAP_INPUT_TAG)
    sent = user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))
    if sent != len(events):
        log.warning("Re-sending held-back input failed (error %s)", ctypes.get_last_error())
    return sent == len(events)


user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.UnhookWindowsHookEx.restype = wt.BOOL
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.GetMessageW.restype = wt.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
user32.PeekMessageW.restype = wt.BOOL
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.PostThreadMessageW.restype = wt.BOOL
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wt.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wt.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetCurrentThreadId.restype = wt.DWORD


def key_is_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def other_guard_keys_held(trigger: frozenset[int]) -> bool:
    return any(key_is_down(vk) for vk in GUARD_VKS if vk not in trigger)


class HookInstallError(RuntimeError):
    pass


class _ThreadTimers:
    """Scheduler backed by Win32 thread timers (WM_TIMER on the hook thread)."""

    def start(self, ms: int) -> int:
        handle = user32.SetTimer(None, 0, max(1, int(ms)), None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "SetTimer failed")
        return int(handle)

    def cancel(self, handle: int) -> None:
        user32.KillTimer(None, handle)


class KeyboardHook:
    """Background thread hosting the global long-press trigger."""

    REHOOK_IDLE_S = 10.0

    def __init__(
        self,
        on_activate: Callable[[], None],
        on_event: Callable[[str, dict], None] | None = None,
        on_escape: Callable[[], None] | None = None,
    ):
        self._on_activate = on_activate
        self._on_event = on_event or (lambda name, info: None)
        self._on_escape = on_escape or (lambda: None)
        self._lock = threading.Lock()
        self._next_config: TriggerConfig | None = None
        self._accept_injected = True
        self._watch_escape = False
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._error: str | None = None
        self._kb_hook: int | None = None
        self._mouse_hook: int | None = None
        self._mouse_wanted = False
        self._pending_hold_back: bool | None = None
        self._last_input = 0.0
        self._detector: LongPressDetector | None = None
        self._interceptor = KeyInterceptor(send_synthetic, other_guard_keys_held)
        # Keep the ctypes callbacks alive for the lifetime of the object.
        self._kb_proc = HOOKPROC(self._keyboard_proc)
        self._ms_proc = HOOKPROC(self._mouse_proc)

    # -- public API (any thread) -----------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._error is None

    @property
    def error(self) -> str | None:
        return self._error

    def start(self, config: TriggerConfig, accept_injected: bool = True, timeout: float = 3.0) -> None:
        if self._thread is not None:
            raise RuntimeError("hook already started")
        with self._lock:
            self._next_config = config
            self._accept_injected = accept_injected
        self._thread = threading.Thread(target=self._run, name="TextSnapKeyboardHook", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            self._error = "keyboard hook thread did not start in time"
            self.stop()
        if self._error:
            raise HookInstallError(self._error)

    def update(self, config: TriggerConfig, accept_injected: bool = True) -> None:
        with self._lock:
            self._next_config = config
            self._accept_injected = accept_injected
        self._post(WM_APP_CONFIG)

    def set_watch_escape(self, enabled: bool) -> None:
        self._watch_escape = enabled

    def refresh(self) -> None:
        """Reinstall the hook if idle (Windows silently drops slow LL hooks)."""
        self._post(WM_APP_REHOOK)

    def stop(self, timeout: float = 3.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop_requested.set()  # a thread that has not started its loop yet exits on its own
        if thread.is_alive():
            self._ready.wait(timeout)
            self._post(WM_QUIT)
            thread.join(timeout)
        self._thread = None

    @property
    def hooks_installed(self) -> bool:
        return self._kb_hook is not None

    # -- thread internals ---------------------------------------------
    def _post(self, message: int, wparam: int = 0) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, message, wparam, 0)

    def _run(self) -> None:
        msg = wt.MSG()
        self._thread_id = kernel32.GetCurrentThreadId()
        user32.PeekMessageW(ctypes.byref(msg), None, WM_USER, WM_USER, PM_NOREMOVE)  # create the queue
        interceptor = self._interceptor
        # A held-back key never reaches the async key state, so ask the interceptor first.
        self._detector = LongPressDetector(
            _ThreadTimers(), self._activated, self._detector_event,
            is_key_down=lambda vk: interceptor.holding(vk) or key_is_down(vk),
            other_keys_held=other_guard_keys_held,
        )
        interceptor.attach(self._detector)
        with self._lock:
            self._apply_config(self._next_config)
        if not self._install_keyboard_hook():
            self._ready.set()
            return
        self._ready.set()
        try:
            while not self._stop_requested.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0 or result == -1:
                    break
                self._dispatch(msg)
        finally:
            self._interceptor.reset()
            self._remove_mouse_hook()
            if self._kb_hook:
                user32.UnhookWindowsHookEx(self._kb_hook)
                self._kb_hook = None
            self._detector.reset()
            self._thread_id = 0

    def _dispatch(self, msg: wt.MSG) -> None:
        assert self._detector is not None
        if msg.message == WM_TIMER and not msg.hWnd:
            user32.KillTimer(None, msg.wParam)  # thread timers repeat; we want one shot
            self._detector.timer_fired(int(msg.wParam))
        elif msg.message == WM_APP_CONFIG:
            with self._lock:
                config = self._next_config
            self._apply_config(config)
        elif msg.message == WM_APP_MOUSE:
            if msg.wParam:
                self._install_mouse_hook()
            else:
                self._remove_mouse_hook()
        elif msg.message == WM_APP_REHOOK:
            stale = time.monotonic() - self._last_input > self.REHOOK_IDLE_S
            if self._detector.idle or stale:
                self._interceptor.reset()
                self._detector.reset()
                self._reinstall_keyboard_hook()

    def _apply_config(self, config: TriggerConfig | None) -> None:
        assert self._detector is not None
        if self._detector.configure(config):
            self._interceptor.suppress = bool(config and config.hold_back)
        else:  # deferred until the trigger keys are released
            self._pending_hold_back = bool(config and config.hold_back)

    def _install_keyboard_hook(self) -> bool:
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc, kernel32.GetModuleHandleW(None), 0)
        if not hook:
            err = ctypes.get_last_error()
            self._error = f"SetWindowsHookEx failed (Windows error {err}: {ctypes.FormatError(err).strip()})"
            log.error("Keyboard hook installation failed: %s", self._error)
            return False
        self._kb_hook = hook
        return True

    def _reinstall_keyboard_hook(self) -> None:
        old = self._kb_hook
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_proc, kernel32.GetModuleHandleW(None), 0)
        if not hook:
            log.warning("Keyboard hook refresh failed (error %s); keeping the existing hook",
                        ctypes.get_last_error())
            return
        self._kb_hook = hook
        if old:
            user32.UnhookWindowsHookEx(old)

    def _install_mouse_hook(self) -> None:
        if self._mouse_hook or not self._mouse_wanted:
            return
        hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._ms_proc, kernel32.GetModuleHandleW(None), 0)
        if hook:
            self._mouse_hook = hook
        else:
            log.warning("Mouse hook unavailable (error %s); clicks will not cancel a pending hold",
                        ctypes.get_last_error())

    def _remove_mouse_hook(self) -> None:
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None

    def _activated(self) -> None:
        self._interceptor.on_activated()
        try:
            self._on_activate()
        except Exception:  # never let a callback error escape into the hook
            log.exception("Trigger activation callback failed")

    def _detector_event(self, name: str, info: dict) -> None:
        config = self._detector.config if self._detector else None
        if name == det.CONFIG_APPLIED and self._pending_hold_back is not None:
            self._interceptor.suppress, self._pending_hold_back = self._pending_hold_back, None
        if name == det.ARMED and config is not None and (config.cancel_on_other_input
                                                          or self._interceptor.target_vk() is not None):
            self._mouse_wanted = True
            self._post(WM_APP_MOUSE, 1)
        elif name in (det.CANCELLED, det.ACTIVATED, det.RELEASED, det.CONFIG_APPLIED) and self._mouse_wanted:
            self._mouse_wanted = False
            self._post(WM_APP_MOUSE, 0)
        try:
            self._on_event(name, info)
        except Exception:
            log.exception("Trigger event callback failed")

    # -- hook procedures (keep these tiny) ------------------------------
    def _keyboard_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code == HC_ACTION:
            try:
                k = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if self._handle_key(k.vkCode, k.scanCode, k.flags, k.dwExtraInfo, w_param):
                    return 1  # held back (re-sent later or swallowed by design)
            except Exception:
                log.exception("Keyboard hook handler error")
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _handle_key(self, vk: int, scan: int, flags: int, extra: int, w_param: int) -> bool:
        """Returns True when the event must be blocked."""
        if extra == TEXTSNAP_INPUT_TAG:
            return False
        if flags & LLKHF_INJECTED and not self._accept_injected:
            return False
        vk = normalize_vk(vk, scan, flags)
        if is_altgr_fake_ctrl(vk, scan):
            return False
        down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
        self._last_input = time.monotonic()
        if down and vk == VK_ESCAPE and self._watch_escape:
            self._on_escape()
        return self._interceptor.on_key(vk, scan, bool(flags & LLKHF_EXTENDED), down)

    def _mouse_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code == HC_ACTION and w_param in MOUSE_CANCEL_MESSAGES:
            try:
                m = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if m.dwExtraInfo != TEXTSNAP_INPUT_TAG:
                    data = (m.mouseData >> 16) & 0xFFFF
                    if w_param in (0x20A, 0x20E) and data & 0x8000:
                        data -= 0x10000  # signed wheel delta
                    if self._interceptor.on_mouse(w_param, data):
                        return 1  # re-sent right after the held-back Space
            except Exception:
                log.exception("Mouse hook handler error")
        return user32.CallNextHookEx(None, n_code, w_param, l_param)
