"""Clipboard, history, startup, single instance, trigger service, documents, QR."""

from __future__ import annotations

import time
import uuid

import numpy as np
import pytest

from textsnap.clipboard.clipboard import ClipboardService
from textsnap.history.store import HistoryError, HistoryStore
from textsnap.keyboard.service import TriggerService
from textsnap.ocr import documents, qr, samples
from textsnap.storage import paths
from textsnap.winsys.single_instance import InstanceLock
from textsnap.winsys.startup import RUN_KEY, VALUE_NAME, StartupManager

from helpers import FakeClipboardBackend


# ------------------------------------------------------------------ clipboard
def test_clipboard_unicode_hebrew_mixed():
    be = FakeClipboardBackend()
    svc = ClipboardService(be, sleep=lambda s: None)
    for text in ["Hello", "שלום עולם", "הפגישה עם Microsoft ב-3.2", "emoji \U0001F600 and \u200f marks"]:
        res = svc.set_text(text)
        assert res.ok and be.text == text and not be.is_open


def test_clipboard_retries_when_locked():
    be = FakeClipboardBackend(fail_opens=3)
    sleeps = []
    svc = ClipboardService(be, attempts=10, sleep=sleeps.append)
    res = svc.set_text("x")
    assert res.ok and res.attempts == 4 and len(sleeps) == 3
    assert sleeps == sorted(sleeps)  # growing back-off


def test_clipboard_failure_reported():
    be = FakeClipboardBackend(fail_opens=99)
    res = ClipboardService(be, attempts=5, sleep=lambda s: None).set_text("x")
    assert not res.ok and res.attempts == 5 and "in use" in res.error and be.text is None


def test_clipboard_history_exclusion_formats():
    be = FakeClipboardBackend()
    ClipboardService(be, sleep=lambda s: None).set_text("secret", exclude_from_history=True)
    assert be.formats == {"CanIncludeInClipboardHistory": 0, "CanUploadToCloudClipboard": 0}
    ClipboardService(be, sleep=lambda s: None).set_text("normal")
    assert be.formats == {}


def test_clipboard_single_write_per_call():
    be = FakeClipboardBackend()
    svc = ClipboardService(be, sleep=lambda s: None)
    svc.set_text("one")
    assert be.opens == 1


# ------------------------------------------------------------------ history
@pytest.fixture
def store(isolated_data_dir):
    s = HistoryStore(paths.history_db_path())
    s.open()
    yield s
    s.close()


def test_history_disabled_creates_no_file(isolated_data_dir):
    HistoryStore(paths.history_db_path())  # constructing does not open
    assert not paths.history_db_path().exists()
    with pytest.raises(HistoryError):
        HistoryStore(paths.history_db_path()).add("x")


def test_history_crud_and_search(store):
    a = store.add("first שלום", "heb+eng", "region")
    b = store.add("second 100%_off", "eng", "file")
    assert store.count() == 2
    assert [e.id for e in store.search()] == [b, a]  # newest first
    assert [e.id for e in store.search("שלום")] == [a]
    assert [e.id for e in store.search("100%_")] == [b]  # LIKE wildcards are escaped
    assert [e.id for e in store.search("%")] == [b]  # literal percent sign, not "match all"
    assert store.search("d_1") == []  # "_" is literal too
    store.set_pinned(a, True, "greeting")
    assert store.search(pinned_only=True)[0].title == "greeting"
    store.delete(b)
    assert store.get(b) is None and store.count() == 1


def test_history_persists_across_reopen(store):
    store.add("persist me")
    store.close()
    again = HistoryStore(paths.history_db_path())
    again.open()
    assert again.search()[0].text == "persist me"
    again.close()


def test_history_clear_keeps_pinned_then_clear_pinned(store):
    store.add("a")
    pinned = store.add("b", pinned=True)
    assert store.clear() == 1
    assert [e.id for e in store.search()] == [pinned]
    assert store.clear_pinned() == 1 and store.count() == 0


def test_history_retention(store):
    now = time.time()
    old = store.add("old", when=now - 40 * 86400)
    store.add("old pinned", pinned=True, when=now - 400 * 86400)
    new = store.add("new", when=now - 86400)
    assert store.purge_older_than(30, now=now) == 1
    ids = {e.id for e in store.search()}
    assert old not in ids and new in ids and len(ids) == 2
    assert store.purge_older_than(0, now=now) == 0  # 0 = keep forever


def test_history_export(store, tmp_path):
    a = store.add("line one\nline two", title="T")
    out = tmp_path / "export.txt"
    assert store.export([a], out) == 1
    assert "line one\nline two" in out.read_text(encoding="utf-8")


def test_history_destroy_removes_files(store):
    store.add("x")
    store.destroy()
    assert not paths.history_db_path().exists()


def test_history_corrupt_database_is_reported(isolated_data_dir):
    path = paths.history_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a sqlite database" * 100)
    with pytest.raises(HistoryError):
        HistoryStore(path).open()


def test_history_rejects_empty(store):
    with pytest.raises(HistoryError):
        store.add("   ")


# ------------------------------------------------------------------ startup
class FakeRegistry:
    def __init__(self):
        self.values = {}

    def get(self, key, name):
        return self.values.get((key, name))

    def set(self, key, name, value):
        self.values[(key, name)] = value

    def delete(self, key, name):
        self.values.pop((key, name), None)


def test_startup_is_opt_in_and_reversible():
    reg = FakeRegistry()
    mgr = StartupManager([r"C:\Apps\TextSnap\TextSnap.exe"], reg)
    assert not mgr.is_enabled() and reg.values == {}
    mgr.enable()
    assert reg.values == {(RUN_KEY, VALUE_NAME): r"C:\Apps\TextSnap\TextSnap.exe --minimized"}
    assert mgr.points_here()
    mgr.disable()
    assert reg.values == {} and not mgr.is_enabled()


def test_startup_command_quotes_spaces():
    reg = FakeRegistry()
    StartupManager([r"C:\Program Files\Text Snap\TextSnap.exe"], reg).enable()
    assert reg.values[(RUN_KEY, VALUE_NAME)] == '"C:\\Program Files\\Text Snap\\TextSnap.exe" --minimized'


# ------------------------------------------------------------------ single instance
def test_single_instance_lock():
    key = "TextSnapTest-" + uuid.uuid4().hex
    first, second = InstanceLock(key), InstanceLock(key)
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


# ------------------------------------------------------------------ trigger service
class FailingHook:
    def __init__(self, *callbacks):
        self.stopped = False

    def start(self, config, accept_injected=True):
        from textsnap.keyboard.hook import HookInstallError
        raise HookInstallError("SetWindowsHookEx failed (Windows error 5: Access is denied.)")

    def stop(self):
        self.stopped = True


class RecordingHook:
    instances: list["RecordingHook"] = []

    def __init__(self, on_activate, on_event, on_escape):
        self.on_activate = on_activate
        self.running = False
        self.configs = []
        self.stopped = False
        RecordingHook.instances.append(self)

    def start(self, config, accept_injected=True):
        self.running = True
        self.configs.append(config)

    def update(self, config, accept_injected=True):
        self.configs.append(config)

    def set_watch_escape(self, on):
        pass

    def refresh(self):
        pass

    def stop(self):
        self.running = False
        self.stopped = True


def test_hook_failure_is_reported(qtbot):
    svc = TriggerService(FailingHook)
    with qtbot.waitSignal(svc.status_changed) as sig:
        svc.apply(True, ["RCtrl"], 500)
    state, message = sig.args
    assert state == "error" and "Access is denied" in message and "tray" in message
    assert svc.hook is None


def test_trigger_reconfigure_and_disable_cleanup(qtbot):
    RecordingHook.instances.clear()
    svc = TriggerService(RecordingHook)
    svc.apply(True, ["RCtrl"], 500)
    hook = svc.hook
    assert svc.state == "active" and hook.running
    svc.apply(True, ["LCtrl"], 700)
    assert svc.hook is hook and len(hook.configs) == 2 and hook.configs[-1].hold_ms == 700
    svc.apply(False, ["LCtrl"], 700)
    assert hook.stopped and svc.hook is None and svc.state == "disabled"
    svc.apply(True, ["RCtrl"], 500)
    assert len(RecordingHook.instances) == 2  # a fresh hook, never two at once
    svc.shutdown()
    assert RecordingHook.instances[-1].stopped and svc.state == "stopped"


def test_trigger_activation_signal(qtbot):
    RecordingHook.instances.clear()
    svc = TriggerService(RecordingHook)
    svc.apply(True, ["RCtrl"], 500)
    with qtbot.waitSignal(svc.activated, timeout=1000):
        RecordingHook.instances[-1].on_activate()
    svc.shutdown()


def test_invalid_trigger_is_rejected(qtbot):
    svc = TriggerService(RecordingHook)
    svc.apply(True, ["Bogus"], 500)
    assert svc.state == "error" and "Invalid trigger" in svc.message


# ------------------------------------------------------------------ documents
def test_page_range_parsing():
    assert documents.parse_page_range("", 3) == [0, 1, 2]
    assert documents.parse_page_range("1-3, 5", 6) == [0, 1, 2, 4]
    assert documents.parse_page_range("2-", 4) == [1, 2, 3]
    assert documents.parse_page_range("3,3,1", 4) == [2, 0]
    for bad in ["0", "5", "3-1", "x"]:
        with pytest.raises(ValueError):
            documents.parse_page_range(bad, 4)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "BMP", "TIFF"])
def test_image_formats_load_unchanged(tmp_path, render, fmt):
    from PIL import Image
    path = tmp_path / f"img.{fmt.lower()}"
    Image.fromarray(render(samples.ENGLISH)).save(path, fmt)
    before = path.read_bytes()
    rgb = documents.load_image(path)
    assert rgb.ndim == 3 and rgb.shape[2] == 3 and rgb.dtype == np.uint8
    assert path.read_bytes() == before


def test_malformed_image(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    with pytest.raises(documents.DocumentError):
        documents.load_image(path)


def test_oversized_image_rejected(tmp_path, monkeypatch):
    from PIL import Image
    path = tmp_path / "big.png"
    Image.new("L", (3000, 3000), 255).save(path)
    monkeypatch.setattr(documents, "MAX_IMAGE_PIXELS", 1_000_000)
    with pytest.raises(documents.DocumentError):
        documents.load_image(path)


def make_pdf(path, lines):
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPainter, QPdfWriter
    samples.ensure_fonts()
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A5))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    writer.setResolution(150)
    p = QPainter(writer)
    font = QFont("Segoe UI")
    font.setPointSize(14)
    p.setFont(font)
    for i, page_lines in enumerate(lines):
        if i:
            writer.newPage()
        for j, line in enumerate(page_lines):
            p.drawText(40, 80 + j * 60, line)
    p.end()


@pytest.mark.ocr
def test_pdf_embedded_text_and_ocr(tmp_path, pipeline, qapp):
    from textsnap.ocr.pipeline import OcrOptions
    path = tmp_path / "doc.pdf"
    make_pdf(path, [["Page one says hello"], ["Second page here"]])
    doc = documents.PdfDocument(path)
    try:
        assert len(doc) == 2
        assert "hello" in doc.embedded_text(0)
        rendered = doc.render(1, dpi=150)
        assert rendered.ndim == 3 and rendered.shape[0] > 300
        assert "Second page" in pipeline.recognize(rendered, OcrOptions(language="eng")).text
    finally:
        doc.close()


def test_bad_pdf(tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.4 garbage")
    with pytest.raises(documents.DocumentError):
        documents.PdfDocument(path)


# ------------------------------------------------------------------ QR
def test_qr_detection():
    import zxingcpp
    code = np.asarray(zxingcpp.create_barcode("https://example.com/qr", zxingcpp.BarcodeFormat.QRCode)
                      .to_image(scale=6))
    canvas = np.full((code.shape[0] + 80, code.shape[1] + 300, 3), 255, np.uint8)
    canvas[40:40 + code.shape[0], 40:40 + code.shape[1]] = code[..., None]
    assert qr.decode_qr(canvas) == ["https://example.com/qr"]
    assert qr.decode_qr(np.full((50, 50, 3), 255, np.uint8)) == []


def test_quit_without_running_instance_starts_nothing(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, TEXTSNAP_INSTANCE_ID="quit-" + uuid.uuid4().hex)
    started = time.monotonic()
    code = subprocess.run([sys.executable, str(root / "main.py"), "--data-dir", str(tmp_path / "d"), "--quit"],
                          env=env, timeout=60).returncode
    assert code == 0 and time.monotonic() - started < 30
    assert not (tmp_path / "d" / "logs").exists()  # the app never started
