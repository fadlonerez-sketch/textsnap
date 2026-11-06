"""Desktop integration tests: real keyboard hook, real clipboard, real app process.

Opt-in (TEXTSNAP_DESKTOP_TESTS=1) because they inject OS-level input. They
use F23/F24 (keys no application reacts to) except one brief Right Ctrl
check, select only a TextSnap-owned test window, keep every capture in
memory, and restore the clipboard's previous text afterwards.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import winput
from textsnap.keyboard.detector import TriggerConfig
from textsnap.keyboard.hook import KeyboardHook
from textsnap.keyboard.keys import trigger_vks

ROOT = Path(__file__).resolve().parents[1]
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetClipboardSequenceNumber.restype = wt.DWORD
user32.OpenInputDesktop.restype = ctypes.c_void_p
user32.CloseDesktop.argtypes = [ctypes.c_void_p]


def _interactive_desktop() -> bool:
    """False while the workstation is locked (Windows then rejects SendInput)."""
    h = user32.OpenInputDesktop(0, False, 0x0100)
    if h:
        user32.CloseDesktop(h)
    return bool(h) and bool(user32.GetForegroundWindow())


pytestmark = [pytest.mark.desktop,
              pytest.mark.skipif(not _interactive_desktop(),
                                 reason="the interactive desktop is locked; synthetic input is impossible")]


def wait_for(predicate, timeout: float, step: float = 0.05, pump=None) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pump:
            pump()
        if predicate():
            return True
        time.sleep(step)
    if pump:
        pump()
    return predicate()


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def seconds_since_user_input() -> float:
    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    user32.GetLastInputInfo(ctypes.byref(info))
    now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF  # DWORD; ctypes returns it as a signed int
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0  # both wrap every 49.7 days


@pytest.fixture
def user_idle():
    """Only inject input while nobody is using the keyboard or mouse."""
    if not wait_for(lambda: seconds_since_user_input() >= 10, 120, step=1):
        pytest.skip("the keyboard/mouse is in use; not injecting input")


def text_sink(qapp):
    """A TextSnap-owned text box with keyboard focus: every replayed key lands here."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLineEdit
    from textsnap.winsys.focus import force_foreground
    box = QLineEdit()
    box.setWindowTitle("TextSnap test input")
    box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    box.resize(420, 40)
    box.move(160, 60)
    box.show()
    qapp.processEvents()
    force_foreground(int(box.winId()))
    box.activateWindow()
    box.setFocus()
    assert wait_for(lambda: box.hasFocus() and user32.GetForegroundWindow() == int(box.winId()), 3,
                    pump=qapp.processEvents), "could not focus the test text box"
    return box


class Recorder:
    def __init__(self):
        self.activations = 0
        self.events: list[str] = []

    def activate(self):
        self.activations += 1

    def event(self, name, info):
        self.events.append(name)


def start_hook(names, hold=500) -> tuple[KeyboardHook, Recorder]:
    rec = Recorder()
    hook = KeyboardHook(rec.activate, rec.event)
    hook.start(TriggerConfig(trigger_vks(names), hold))
    return hook, rec


def test_real_hook_long_press_short_press_and_interruption(user_idle):
    hook, rec = start_hook(["F24"], 400)
    try:
        assert hook.hooks_installed
        winput.hold(winput.VK_F24, 0.08)  # short press
        time.sleep(0.6)
        assert rec.activations == 0
        winput.hold(winput.VK_F24, 0.25)  # below threshold
        time.sleep(0.4)
        assert rec.activations == 0
        winput.hold(winput.VK_F24, 0.7)  # long press
        assert wait_for(lambda: rec.activations == 1, 1.0)
        time.sleep(0.5)
        assert rec.activations == 1  # exactly once
        winput.key(winput.VK_F24, True)  # hold, but press another key meanwhile
        time.sleep(0.1)
        winput.tap(winput.VK_F23)
        time.sleep(0.6)
        winput.key(winput.VK_F24, False)
        time.sleep(0.2)
        assert rec.activations == 1
        assert "cancelled" in rec.events
    finally:
        hook.stop()
    assert not hook.hooks_installed


def test_real_hook_right_ctrl_default_trigger(user_idle):
    hook, rec = start_hook(["RCtrl"], 500)
    try:
        winput.hold(winput.VK_RCONTROL, 0.1, extended=True)
        time.sleep(0.7)
        assert rec.activations == 0
        winput.hold(winput.VK_RCONTROL, 0.75, extended=True)
        assert wait_for(lambda: rec.activations == 1, 1.0)
    finally:
        hook.stop()


def test_real_hook_spacebar_trigger_preserves_typing(qapp, user_idle):
    box = text_sink(qapp)
    hook, rec = start_hook(["Space"], 500)
    pump = qapp.processEvents
    try:
        winput.hold(winput.VK_SPACE, 0.08)  # quick tap: one space, no overlay
        assert wait_for(lambda: box.text() == " ", 2, pump=pump), repr(box.text())
        assert rec.activations == 0
        # "1 2" typed with roll-over: 2 pressed before Space is released.
        winput.tap(winput.VK_1)
        winput.key(winput.VK_SPACE, True)
        time.sleep(0.04)
        winput.key(winput.VK_2, True)
        time.sleep(0.03)
        winput.key(winput.VK_SPACE, False)
        winput.key(winput.VK_2, False)
        assert wait_for(lambda: box.text() == " 1 2", 2, pump=pump), repr(box.text())
        # Long hold: activates once, types nothing (no space, no auto-repeat).
        winput.hold(winput.VK_SPACE, 1.2)
        assert wait_for(lambda: rec.activations == 1, 1.0, pump=pump)
        wait_for(lambda: False, 0.4, pump=pump)
        assert box.text() == " 1 2" and rec.activations == 1
        # Shift+Space is never held back (no activation, the space is typed immediately).
        winput.key(winput.VK_LSHIFT, True)
        winput.hold(winput.VK_SPACE, 0.9)
        winput.key(winput.VK_LSHIFT, False)
        assert wait_for(lambda: box.text().startswith(" 1 2 "), 2, pump=pump), repr(box.text())
        assert rec.activations == 1
    finally:
        hook.stop()
        box.close()
    assert not hook.hooks_installed


def test_hook_restart_leaves_no_duplicate(user_idle):
    first, rec1 = start_hook(["F24"], 300)
    first.stop()
    second, rec2 = start_hook(["F24"], 300)
    try:
        winput.hold(winput.VK_F24, 0.5)
        assert wait_for(lambda: rec2.activations == 1, 1.0)
        assert rec1.activations == 0
    finally:
        second.stop()


def test_real_clipboard_unicode_roundtrip(qapp):
    from PySide6.QtWidgets import QWidget
    from textsnap.clipboard.clipboard import ClipboardService
    owner = QWidget()
    svc = ClipboardService(owner=lambda: int(owner.winId()))
    previous = svc.get_text()
    try:
        for text in ["שלום עולם", "הפגישה עם Microsoft ב-3.2\nשורה שנייה", "plain ascii"]:
            res = svc.set_text(text)
            assert res.ok, res.error
            assert svc.get_text() == text
    finally:
        if previous is not None:
            svc.set_text(previous)


# ---------------------------------------------------------------- full application
def _app_windows(pid: int, title: str) -> list[int]:
    found = []
    proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, _):
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == title:
                found.append(hwnd)
        return True

    user32.EnumWindows(proc(cb), 0)
    return found


def _launch(data: Path, instance: str, *args: str, exe: list[str] | None = None) -> subprocess.Popen:
    env = dict(os.environ, TEXTSNAP_INSTANCE_ID=instance)
    env.pop("QT_QPA_PLATFORM", None)
    cmd = (exe or [sys.executable, str(ROOT / "main.py")]) + ["--data-dir", str(data), *args]
    return subprocess.Popen(cmd, env=env, cwd=str(ROOT), creationflags=0x08000000)


def run_app_end_to_end(qapp, tmp_path, exe: list[str] | None = None) -> dict:
    """Drive a real TextSnap process with its default Spacebar trigger: tap, hold, overlay,
    Esc, drag, OCR, clipboard, focus return, quit. A focused text box owned by the test
    receives every key the app lets through, so leaked or lost spaces are detected."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QLabel
    from textsnap.capture.convert import rgb_to_qimage
    from textsnap.clipboard.clipboard import ClipboardService
    from textsnap.ocr import samples

    data = tmp_path / "app-data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({
        "hold_ms": 500, "first_run_done": True, "show_toast": True,
        "restore_focus": True, "show_magnifier": True}), encoding="utf-8")
    instance = "e2e-" + uuid.uuid4().hex
    report: dict = {}

    owner = QLabel()
    clip = ClipboardService(owner=lambda: int(owner.winId()))
    previous = clip.get_text()
    app = _launch(data, instance, "--minimized", exe=exe)
    target = box = None
    pump = qapp.processEvents
    try:
        log = data / "logs" / "textsnap.log"
        assert wait_for(lambda: log.exists() and "TextSnap started" in log.read_text(encoding="utf-8"), 30), \
            "app did not start"
        time.sleep(2.0)  # engine probe
        # A controlled, synthetic text source: TextSnap's own test window.
        lines = ["TextSnap end-to-end check 4521", "שלום עולם, בדיקה של זיהוי טקסט"]
        target = QLabel()
        target.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                              | Qt.WindowType.Tool)
        target.setPixmap(QPixmap.fromImage(rgb_to_qimage(samples.render_lines(lines, px=18))))
        target.adjustSize()
        target.move(160, 160)
        target.show()
        qapp.processEvents()
        time.sleep(0.4)
        qapp.processEvents()
        rc = wt.RECT()
        user32.GetWindowRect(int(target.winId()), ctypes.byref(rc))
        report["target_physical"] = [rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top]
        box = text_sink(qapp)

        # 1. A short Space press types one space and does not open the overlay.
        winput.hold(winput.VK_SPACE, 0.1)
        assert wait_for(lambda: box.text() == " ", 2, pump=pump), repr(box.text())
        wait_for(lambda: False, 0.8, pump=pump)
        assert not _app_windows(app.pid, "TextSnap selection"), "short press opened the overlay"
        # 2. A long press opens it without typing anything; Esc cancels it.
        winput.hold(winput.VK_SPACE, 0.8)
        assert wait_for(lambda: bool(_app_windows(app.pid, "TextSnap selection")), 3, pump=pump), \
            "overlay did not open"
        time.sleep(0.3)
        winput.tap(winput.VK_ESCAPE)
        assert wait_for(lambda: not _app_windows(app.pid, "TextSnap selection"), 3, pump=pump), \
            "Esc did not close overlay"
        assert box.text() == " ", f"a long press leaked input: {box.text()!r}"
        report["space_tap_typed_one_space"] = True
        # 3. Long press, drag over the test window, text lands on the clipboard.
        seq = user32.GetClipboardSequenceNumber()
        t0 = time.perf_counter()
        winput.hold(winput.VK_SPACE, 0.8)
        assert wait_for(lambda: bool(_app_windows(app.pid, "TextSnap selection")), 3, pump=pump), \
            "overlay did not open"
        report["overlay_after_s"] = round(time.perf_counter() - t0, 2)
        time.sleep(0.3)
        winput.drag(rc.left - 6, rc.top - 6, rc.right + 6, rc.bottom + 6)
        t1 = time.perf_counter()
        assert wait_for(lambda: user32.GetClipboardSequenceNumber() != seq, 15, pump=pump), \
            "clipboard never changed"
        report["ocr_to_clipboard_s"] = round(time.perf_counter() - t1, 2)
        text = clip.get_text() or ""
        report["clipboard_chars"] = len(text)
        for word in ["TextSnap", "end-to-end", "4521", "שלום", "עולם", "טקסט"]:
            assert word in text, (word, text)
        assert not _app_windows(app.pid, "TextSnap selection")
        fg = user32.GetForegroundWindow()
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        report["focus_returned_to_other_app"] = pid.value != app.pid
        assert pid.value != app.pid, "TextSnap kept focus; Ctrl+V would not reach the previous app"
        wait_for(lambda: False, 0.5, pump=pump)
        assert box.text() == " ", f"the capture leaked input: {box.text()!r}"
        # 4. A second launch forwards --quit; the first instance exits cleanly.
        second = _launch(data, instance, "--quit", exe=exe)
        assert second.wait(15) == 0
        assert app.wait(20) == 0, "app did not exit cleanly"
        report["exit_code"] = app.returncode
        report["log_contains_text"] = any(w in log.read_text(encoding="utf-8") for w in ["שלום", "4521", "end-to-end"])
        assert not report["log_contains_text"]
        assert "Exited cleanly" in log.read_text(encoding="utf-8")
    finally:
        for w in (target, box):
            if w is not None:
                w.close()
        if app.poll() is None:
            app.kill()
        if previous is not None:
            clip.set_text(previous)
    return report


def test_app_end_to_end(qapp, tmp_path, user_idle):
    report = run_app_end_to_end(qapp, tmp_path)
    print("E2E", json.dumps(report))


def test_second_instance_does_not_start_twice(tmp_path):
    data = tmp_path / "d"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"first_run_done": True, "trigger_enabled": False}),
                                        encoding="utf-8")
    instance = "si-" + uuid.uuid4().hex
    first = _launch(data, instance, "--minimized")
    try:
        log = data / "logs" / "textsnap.log"
        assert wait_for(lambda: log.exists() and "TextSnap started" in log.read_text(encoding="utf-8"), 30)
        second = _launch(data, instance, "--minimized")
        assert second.wait(15) == 0  # forwarded "show" and exited
        assert first.poll() is None
        assert log.read_text(encoding="utf-8").count("TextSnap started") == 1
    finally:
        _launch(data, instance, "--quit").wait(15)
        assert first.wait(20) == 0


def _packaged_command(path: str) -> list[str]:
    """TextSnap.exe, or a portable build (its folder or TextSnap.bat) run on its signed runtime."""
    p = Path(path)
    if p.is_dir() or p.suffix.lower() == ".bat":
        root = p if p.is_dir() else p.parent
        return [str(root / "runtime" / "pythonw.exe"), str(root / "app" / "main.py")]
    return [str(p)]


@pytest.mark.skipif(not os.environ.get("TEXTSNAP_EXE"),
                    reason="set TEXTSNAP_EXE to the packaged TextSnap.exe or a portable TextSnap.bat")
def test_packaged_app_end_to_end(qapp, tmp_path, user_idle):
    report = run_app_end_to_end(qapp, tmp_path, exe=_packaged_command(os.environ["TEXTSNAP_EXE"]))
    print("PACKAGED E2E", json.dumps(report))
