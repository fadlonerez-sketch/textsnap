"""Full capture workflow through the controller, offscreen, with real OCR.

The "desktop" is synthetic (rendered Hebrew/English text); the trigger and
clipboard are fakes, so nothing touches the real screen, keyboard or
clipboard.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from textsnap.app.controller import AppController
from textsnap.capture.geometry import Monitor, Rect
from textsnap.clipboard.clipboard import ClipboardService
from textsnap.ocr import samples
from textsnap.storage import paths
from textsnap.storage.settings import SettingsStore

from helpers import FakeClipboardBackend, FakeTrigger, snapshot_from

pytestmark = pytest.mark.ocr
MON = Monitor(0, Rect(0, 0, 800, 800), Rect(0, 0, 800, 800), 1.0)


def desktop_with_text(render) -> np.ndarray:
    img = np.full((800, 800, 3), 255, np.uint8)
    text = render(samples.MIXED, px=15)
    img[200:200 + text.shape[0], 100:100 + text.shape[1]] = text
    return img, Rect(100, 200, text.shape[1], text.shape[0])


@pytest.fixture
def ctl(qtbot, render, isolated_data_dir):
    rgb, text_rect = desktop_with_text(render)
    store = SettingsStore(paths.settings_path())
    clip = FakeClipboardBackend()
    trig = FakeTrigger()
    snaps = []

    def snapshotter(with_windows=True):
        s = snapshot_from([MON], rgb)
        snaps.append(s)
        return s

    c = AppController(store, trigger=trig, clipboard=ClipboardService(clip, sleep=lambda s: None),
                      snapshotter=snapshotter)
    c.update_settings(restore_focus=False)  # never touch the real foreground window in tests
    c.start()
    qtbot.waitUntil(lambda: c.engine_status is not None, timeout=10000)
    c.test_clip, c.test_trigger, c.test_rect, c.test_snaps = clip, trig, text_rect, snaps
    yield c
    c.shutdown()


def select(qtbot, c, rect: Rect):
    qtbot.waitUntil(lambda: c.session is not None, timeout=3000)
    win = c.session.windows[0]
    qtbot.waitExposed(win)
    a = QPoint(rect.x - 6, rect.y - 6)
    b = QPoint(rect.right + 6, rect.bottom + 6)
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(win, b)
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)


def test_trigger_capture_ocr_and_copy(qtbot, ctl):
    assert ctl.engine_status.ok
    assert ctl.test_trigger.applied[-1] == (True, ["Space"], 500)
    with qtbot.waitSignal(ctl.result_ready, timeout=20000) as sig:
        ctl.test_trigger.activated.emit()  # the hook detected a long press
        select(qtbot, ctl, ctl.test_rect)
    record = sig.args[0]
    assert record.copied and not record.copy_error
    copied = ctl.test_clip.text
    assert copied == record.text
    for word in ["Microsoft", "report.pdf", "הפגישה", "שלישי"]:
        assert word in copied
    assert ctl.toast.isVisible()
    assert "Copied" in ctl.last_status and "characters" in ctl.last_status
    assert ctl.test_snaps[-1].image.isNull()  # frozen desktop released after the crop
    assert not paths.history_db_path().exists()  # history is off by default: nothing stored


def test_duplicate_activation_is_ignored(qtbot, ctl):
    assert ctl.start_capture()
    qtbot.waitUntil(lambda: ctl.session is not None, timeout=3000)
    assert not ctl.start_capture()
    ctl.test_trigger.activated.emit()
    assert len(ctl.test_snaps) == 1
    ctl.session.cancel()


def test_escape_from_hook_cancels_without_ocr(qtbot, ctl):
    ctl.start_capture()
    qtbot.waitUntil(lambda: ctl.session is not None, timeout=3000)
    assert ctl.test_trigger.watch_escape
    with qtbot.assertNotEmitted(ctl.result_ready, wait=500):
        ctl.test_trigger.escape_pressed.emit()
    assert ctl.session is None and not ctl.test_trigger.watch_escape
    assert ctl.test_clip.text is None
    assert ctl.test_snaps[-1].image.isNull()


def test_history_only_when_enabled(qtbot, ctl):
    ctl.update_settings(history_enabled=True)
    with qtbot.waitSignal(ctl.result_ready, timeout=20000):
        ctl.start_capture()
        select(qtbot, ctl, ctl.test_rect)
    entries = ctl.history.search()
    assert len(entries) == 1 and "Microsoft" in entries[0].text and entries[0].source == "region"
    ctl.disable_history(delete_entries=True)
    assert not paths.history_db_path().exists()


def test_auto_copy_off_does_not_touch_clipboard(qtbot, ctl):
    ctl.update_settings(auto_copy=False)
    with qtbot.waitSignal(ctl.result_ready, timeout=20000) as sig:
        ctl.start_capture()
        select(qtbot, ctl, ctl.test_rect)
    assert not sig.args[0].copied and ctl.test_clip.opens == 0


def test_clipboard_locked_is_reported(qtbot, ctl):
    ctl.test_clip.fail_opens = 100
    with qtbot.waitSignal(ctl.result_ready, timeout=20000) as sig:
        ctl.start_capture()
        select(qtbot, ctl, ctl.test_rect)
    assert not sig.args[0].copied and "in use" in sig.args[0].copy_error


def test_blank_area_reports_no_text(qtbot, ctl):
    with qtbot.waitSignal(ctl.result_ready, timeout=20000) as sig:
        ctl.start_capture()
        select(qtbot, ctl, Rect(500, 600, 120, 80))  # empty white area
    assert sig.args[0].result.empty and ctl.test_clip.text is None
    assert "No text" in ctl.last_status


def test_rerun_with_other_language_does_not_recopy(qtbot, ctl):
    with qtbot.waitSignal(ctl.result_ready, timeout=20000):
        ctl.start_capture()
        select(qtbot, ctl, ctl.test_rect)
    opens = ctl.test_clip.opens
    ctl.show_result(activate=False)
    with qtbot.waitSignal(ctl.jobs.finished, timeout=20000):
        ctl.rerun("heb", "fast")
    qtbot.waitUntil(lambda: ctl.last_record.result.language == "heb", timeout=5000)
    assert ctl.test_clip.opens == opens  # re-running never overwrites the clipboard by itself
    ctl.forget_capture()
    ctl.rerun("eng", "fast")
    assert "no longer in memory" in ctl.result_window.feedback.text()


def test_repeat_last_region(qtbot, ctl):
    with qtbot.waitSignal(ctl.result_ready, timeout=20000) as first:
        ctl.start_capture()
        select(qtbot, ctl, ctl.test_rect)
    with qtbot.waitSignal(ctl.result_ready, timeout=20000) as again:
        ctl.repeat_last_region()
    assert again.args[0].source == "repeat" and again.args[0].rect == first.args[0].rect


def test_full_desktop_mode_skips_overlay(qtbot, ctl):
    with qtbot.waitSignal(ctl.result_ready, timeout=30000) as sig:
        ctl.capture_full_desktop("trigger")
    assert sig.args[0].source == "desktop" and "Microsoft" in sig.args[0].text


def test_image_file_ocr_leaves_file_unchanged(qtbot, ctl, render, tmp_path):
    from PIL import Image
    path = tmp_path / "sample.png"
    Image.fromarray(render(samples.ENGLISH, px=16)).save(path)
    before = path.read_bytes()
    with qtbot.waitSignal(ctl.result_ready, timeout=20000) as sig:
        ctl.ocr_image_file(str(path))
    assert "quick brown fox" in sig.args[0].text
    assert path.read_bytes() == before
    assert ctl.result_window is not None and ctl.result_window.isVisible()


def test_screenshot_saving_obeys_setting(qtbot, ctl, tmp_path):
    out = tmp_path / "shots"
    with qtbot.waitSignal(ctl.result_ready, timeout=20000):
        ctl.start_capture()
        select(qtbot, ctl, ctl.test_rect)
    assert not out.exists()
    ctl.update_settings(save_captures=True, save_captures_dir=str(out))
    with qtbot.waitSignal(ctl.result_ready, timeout=20000):
        ctl.start_capture()
        select(qtbot, ctl, ctl.test_rect)
    assert len(list(out.glob("TextSnap-*.png"))) == 1


def test_settings_change_reconfigures_trigger(ctl):
    ctl.update_settings(trigger_keys=["LCtrl", "LShift"], hold_ms=800)
    assert ctl.test_trigger.applied[-1] == (True, ["LCtrl", "LShift"], 800)
    ctl.update_settings(trigger_enabled=False)
    assert ctl.test_trigger.applied[-1][0] is False
    reloaded = SettingsStore(paths.settings_path()).load()
    assert reloaded.trigger_keys == ["LCtrl", "LShift"] and reloaded.trigger_enabled is False


def test_trigger_test_mode_does_not_capture(qtbot, ctl):
    ctl.begin_trigger_test(5)
    with qtbot.waitSignal(ctl.trigger_test_event, timeout=1000) as sig:
        ctl.test_trigger.activated.emit()
    assert sig.args[0] == "activated" and ctl.session is None


def test_ocr_text_not_in_log_file(qtbot, ctl):
    from textsnap.app import logs
    log_path = logs.setup("DEBUG", paths.logs_dir())
    try:
        with qtbot.waitSignal(ctl.result_ready, timeout=20000) as sig:
            ctl.start_capture()
            select(qtbot, ctl, ctl.test_rect)
        text = sig.args[0].text
    finally:
        logs.shutdown()
    content = log_path.read_text(encoding="utf-8")
    assert "OCR finished" in content  # logging works...
    for word in ["Microsoft", "report.pdf", "הפגישה", "שלישי"]:
        assert word in text and word not in content  # ...but never contains the text


def test_shutdown_stops_trigger(ctl):
    ctl.shutdown()
    assert ctl.test_trigger.shut


def test_active_window_mode_reads_focused_window(qtbot, ctl, monkeypatch):
    from textsnap.capture import windows
    from textsnap.winsys import focus
    monkeypatch.setattr(focus, "foreign_foreground_window", lambda: 4242)
    r = ctl.test_rect
    monkeypatch.setattr(windows, "window_rect", lambda hwnd: Rect(r.x - 10, r.y - 10, r.w + 20, r.h + 20)
                        if hwnd == 4242 else None)
    ctl.update_settings(capture_mode="active")
    with qtbot.waitSignal(ctl.result_ready, timeout=20000) as sig:
        ctl.test_trigger.activated.emit()
    assert ctl.session is None  # no overlay
    assert sig.args[0].source == "active" and "Microsoft" in sig.args[0].text


def test_active_window_mode_falls_back_to_picker(qtbot, ctl, monkeypatch):
    from textsnap.winsys import focus
    monkeypatch.setattr(focus, "foreign_foreground_window", lambda: 0)
    ctl.update_settings(capture_mode="active")
    ctl.test_trigger.activated.emit()
    qtbot.waitUntil(lambda: ctl.session is not None, timeout=3000)
    assert ctl.session.mode == "window"
    ctl.session.cancel()


def test_cancelled_pdf_is_not_copied(qtbot, ctl, tmp_path):
    from test_services import make_pdf
    path = tmp_path / "doc.pdf"
    make_pdf(path, [["Page one says hello"], ["Second page"], ["Third page"]])
    with qtbot.waitSignal(ctl.jobs.failed, timeout=20000) as sig:
        job = ctl.ocr_pdf(str(path), [0, 1, 2], use_embedded=False)
        ctl.cancel_job(job)
    assert sig.args == [job, "cancelled"]
    assert ctl.test_clip.text is None


def test_no_auto_paste_into_result_window(qtbot, ctl, monkeypatch):
    pasted = []
    monkeypatch.setattr(ctl, "_auto_paste", lambda: pasted.append(1))
    ctl.update_settings(auto_paste=True, open_result_window=True)
    with qtbot.waitSignal(ctl.result_ready, timeout=20000):
        ctl.start_capture()
        select(qtbot, ctl, ctl.test_rect)
    qtbot.wait(300)
    assert pasted == []
    ctl.update_settings(open_result_window=False)
    with qtbot.waitSignal(ctl.result_ready, timeout=20000):
        ctl.start_capture()
        select(qtbot, ctl, ctl.test_rect)
    qtbot.waitUntil(lambda: pasted == [1], timeout=2000)


def test_search_web_never_opens_non_http_template(ctl, monkeypatch):
    from textsnap.app import controller as controller_mod
    opened = []
    monkeypatch.setattr(controller_mod.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url)))
    ctl.settings.search_url = "file:///C:/Windows/System32/calc.exe?{query}"  # bypasses validation on purpose
    ctl.search_web("hello world")
    ctl.settings.search_url = "https://duckduckgo.com/?q={query}"
    ctl.search_web("a&b")
    assert [u.toString() for u in opened] == ["https://www.google.com/search?q=hello+world",
                                              "https://duckduckgo.com/?q=a%26b"]


def test_update_settings_rejects_custom_protocol_search_url(ctl):
    before = ctl.settings.search_url
    ctl.update_settings(search_url="ms-settings:{query}")
    assert ctl.settings.search_url == before
