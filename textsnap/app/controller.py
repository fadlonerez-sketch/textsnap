"""Application controller: owns the services and runs the capture workflow.

Flow: trigger (hook, tray or dashboard) -> freeze-frame snapshot ->
overlay -> crop -> focus returns to the previous app -> OCR on a worker
thread -> clipboard copy -> toast / result window -> optional history.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus

import numpy as np
from PySide6.QtCore import QObject, QRect, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

from textsnap.app import logs
from textsnap.app.jobs import JobRunner
from textsnap.app.models import CaptureResult
from textsnap.capture.convert import qimage_to_rgb
from textsnap.capture.geometry import Rect
from textsnap.capture.screen import CaptureError, DesktopSnapshot, take_snapshot
from textsnap.clipboard.clipboard import ClipboardService
from textsnap.history.store import HistoryError, HistoryStore
from textsnap.keyboard.service import TriggerService
from textsnap.ocr.documents import IMAGE_SUFFIXES, DocumentError, PdfDocument, load_image
from textsnap.ocr.engine import EngineStatus, OcrCancelled, TesseractEngine
from textsnap.ocr.pipeline import OcrOptions, OcrPipeline, OcrResult
from textsnap.ocr.qr import decode_qr
from textsnap.storage import paths
from textsnap.storage.settings import LANGUAGE_LABELS, Settings, SettingsStore, safe_search_url, validate
from textsnap.ui.toast import Toast

log = logging.getLogger(__name__)

SCREEN_SOURCES = ("region", "window", "monitor", "desktop", "repeat", "active")
KEEP_CAPTURE_MS = 10 * 60 * 1000  # the last crop is kept in memory for "Run again", then dropped
TRIGGER_KEYS = {"trigger_enabled", "trigger_keys", "hold_ms", "cancel_on_other_input", "accept_injected_keys",
                "hold_back_trigger_key"}


@dataclass
class _JobContext:
    source: str
    rect: Rect | None = None
    file_name: str = ""
    rerun: bool = False
    open_window: bool = False
    can_rerun: bool = True
    started: float = field(default_factory=time.monotonic)


class AppController(QObject):
    settings_changed = Signal(object)
    trigger_status = Signal(str, str)
    trigger_test_event = Signal(str, dict)
    engine_status_changed = Signal(object)
    last_status_changed = Signal(str)
    result_ready = Signal(object)
    history_changed = Signal()
    busy_changed = Signal(bool)
    pdf_progress = Signal(int, int)
    show_dashboard_requested = Signal(str)
    self_check_done = Signal(object)

    def __init__(self, store: SettingsStore, trigger: TriggerService | None = None,
                 clipboard: ClipboardService | None = None, snapshotter: Callable[..., DesktopSnapshot] | None = None):
        super().__init__()
        self.store = store
        self.settings: Settings = store.load()
        self.engine = TesseractEngine(paths.tesseract_dir(self.settings.tesseract_dir))
        self.pipeline = OcrPipeline(self.engine)
        self.engine_status: EngineStatus | None = None
        self.jobs = JobRunner(2, self)
        self.jobs.finished.connect(self._job_finished)
        self.jobs.failed.connect(self._job_failed)
        self.jobs.progress.connect(self._job_progress)
        self.trigger = trigger or TriggerService()
        self.trigger.activated.connect(self._on_trigger)
        self.trigger.escape_pressed.connect(self._on_escape)
        self.trigger.status_changed.connect(self.trigger_status)
        self.trigger.detector_event.connect(self._on_detector_event)
        self._clip_owner = QWidget()
        self._clip_owner.setWindowTitle("TextSnap clipboard owner")
        self.clipboard = clipboard or ClipboardService(owner=lambda: int(self._clip_owner.winId()))
        self.history = HistoryStore(paths.history_db_path())
        self._snapshotter = snapshotter or take_snapshot
        self.toast = Toast()
        self.result_window = None
        self.session = None
        self._starting = False
        self._prev_foreground = 0
        self._last_region: Rect | None = None
        self._last_image: np.ndarray | None = None
        self._last_context: _JobContext | None = None
        self.last_record: CaptureResult | None = None
        self.last_status = "No captures yet"
        self._jobs: dict[int, _JobContext] = {}
        self._current_job = 0
        self._pdf_job = 0
        self._busy_toast_shown = False
        self._retired_pipelines: list[OcrPipeline] = []
        self._capture_seq = 0
        self.test_mode = False
        self._test_timer = QTimer(self)
        self._test_timer.setSingleShot(True)
        self._test_timer.timeout.connect(self.end_trigger_test)
        self._purge_timer = QTimer(self)
        self._purge_timer.setSingleShot(True)
        self._purge_timer.timeout.connect(self.forget_capture)
        self._busy_toast = QTimer(self)
        self._busy_toast.setSingleShot(True)
        self._busy_toast.timeout.connect(self._show_busy_toast)
        self._startup = None
        self._shut_down = False

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.apply_trigger()
        if self.settings.history_enabled:
            self._open_history()
        self.refresh_engine_status()
        log.info("TextSnap started (data dir %s)", paths.data_dir())

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        log.info("Shutting down")
        if self.session is not None:
            self.session.cancel()
        self.trigger.shutdown()
        self.jobs.cancel_all()
        self.jobs.wait(4000)
        self.pipeline.shutdown()
        for p in self._retired_pipelines:
            p.shutdown()
        self._retired_pipelines.clear()
        self.history.close()
        self.toast.hide_now()
        # Toast actions and result-window lambdas capture this controller; held by Qt
        # connections, those cycles are invisible to Python's GC. Break them here so the
        # windows are released deterministically instead of from inside a child's destructor.
        self.toast.clear_actions()
        if self.result_window is not None:
            self.result_window.close()
            self.result_window.deleteLater()
            self.result_window = None
        self.forget_capture()

    def refresh_engine_status(self) -> None:
        engine = self.engine

        def work(cancel, progress):
            return engine.status(refresh=True)

        job = self.jobs.submit(work)
        self._jobs[job] = _JobContext("engine-status")

    def _show_busy_toast(self) -> None:
        self._busy_toast_shown = True
        self.toast.show_message("busy", "Reading text\u2026", "This capture is taking a little longer.", seconds=20)

    def _end_busy(self) -> None:
        self._busy_toast.stop()
        if self._busy_toast_shown:
            self._busy_toast_shown = False
            self.toast.hide_now()
        self.busy_changed.emit(False)

    def _is_current(self, job_id: int, ctx: _JobContext) -> bool:
        return job_id == (self._pdf_job if ctx.source == "pdf" else self._current_job)

    def _retire_idle_pipelines(self) -> None:
        if self._retired_pipelines and self.jobs.active == 0:
            for p in self._retired_pipelines:
                p.shutdown()
            self._retired_pipelines.clear()

    def _warm_up(self) -> None:
        """Load the engine and the current models once so the first capture is fast."""
        engine, s = self.engine, self.settings
        langs = ["heb", "eng"] if s.ocr_language in ("heb+eng", "auto") else [s.ocr_language]
        image = np.full((40, 120), 255, np.uint8)
        image[15:25, 10:110] = 0

        def work(cancel, progress):
            return engine.recognize(image, langs, 7, s.ocr_model, 30, cancel=cancel)

        job = self.jobs.submit(work)
        self._jobs[job] = _JobContext("warm-up")

    def run_self_check(self) -> None:
        """Recognise built-in sample images with the current engine (Languages page)."""
        from textsnap.app.selftest import run_ocr_checks, sample_images
        images = sample_images()
        pipeline, model = self.pipeline, self.settings.ocr_model

        def work(cancel, progress):
            return run_ocr_checks(pipeline, images, model)

        job = self.jobs.submit(work)
        self._jobs[job] = _JobContext("self-check")

    @property
    def startup(self):
        if self._startup is None:
            from textsnap.winsys.startup import StartupManager
            self._startup = StartupManager(paths.executable_command())
        return self._startup

    # ------------------------------------------------------------------ settings
    def update_settings(self, **changes) -> Settings:
        data = dataclasses.asdict(self.settings)
        data.update(changes)
        new, problems = validate(data)
        for p in problems:
            log.warning("Rejected setting change: %s", p)
        old = self.settings
        self.settings = new
        try:
            self.store.save(new)
        except OSError as exc:
            log.error("Settings could not be saved: %s", exc)
        changed = {k for k in changes if getattr(old, k) != getattr(new, k)}
        if changed & TRIGGER_KEYS:
            self.apply_trigger()
        if "tesseract_dir" in changed:
            self._retired_pipelines.append(self.pipeline)  # in-flight jobs may still use it
            self._retire_idle_pipelines()
            self.engine = TesseractEngine(paths.tesseract_dir(new.tesseract_dir))
            self.pipeline = OcrPipeline(self.engine)
            self.refresh_engine_status()
        if "history_enabled" in changed:
            if new.history_enabled:
                self._open_history()
            else:
                self.history.close()
            self.history_changed.emit()
        if "history_retention_days" in changed and self.history.is_open:
            self._purge_history()
        if "log_level" in changed:
            logs.set_level(new.log_level)
        self.settings_changed.emit(new)
        return new

    def reset_settings(self) -> None:
        defaults = Settings()
        self.update_settings(**{f.name: getattr(defaults, f.name) for f in dataclasses.fields(Settings)
                                if f.name not in ("first_run_done",)})

    def apply_trigger(self) -> None:
        s = self.settings
        self.trigger.apply(s.trigger_enabled, s.trigger_keys, s.hold_ms, s.cancel_on_other_input,
                           s.accept_injected_keys, s.hold_back_trigger_key)

    def ocr_options(self, language: str | None = None, quality: str | None = None) -> OcrOptions:
        s = self.settings
        return OcrOptions(language=language or s.ocr_language, quality=quality or s.ocr_quality, model=s.ocr_model,
                          layout=s.ocr_layout, preprocess=s.preprocess, timeout_s=s.ocr_timeout_s,
                          strip_bidi=s.strip_bidi_marks, preserve_line_breaks=s.preserve_line_breaks,
                          fix_mixed_script=s.fix_mixed_script)

    # ------------------------------------------------------------------ trigger
    def _on_trigger(self) -> None:
        if self.test_mode:
            self.trigger_test_event.emit("activated", {})
            return
        self.start_capture(source="trigger")

    def _on_detector_event(self, name: str, info: dict) -> None:
        if self.test_mode:
            self.trigger_test_event.emit(name, info)

    def begin_trigger_test(self, seconds: int = 20) -> None:
        self.test_mode = True
        self._test_timer.start(seconds * 1000)

    def end_trigger_test(self) -> None:
        if self.test_mode:
            self.test_mode = False
            self._test_timer.stop()
            self.trigger_test_event.emit("test_ended", {})

    def _on_escape(self) -> None:
        if self.session is not None:
            self.session.cancel()

    # ------------------------------------------------------------------ capture
    @property
    def capture_active(self) -> bool:
        return self.session is not None or self._starting

    def start_capture(self, mode: str | None = None, source: str = "trigger") -> bool:
        """Begin a screen capture. Returns False if one is already running."""
        if self.capture_active:
            return False
        if self.engine_status is not None and not self.engine_status.ok:
            self._toast("error", "OCR engine unavailable", self.engine_status.error,
                        actions=[("Open settings", lambda: self.show_dashboard_requested.emit("languages"))])
            return False
        self._starting = True
        from textsnap.winsys.focus import foreign_foreground_window
        self._prev_foreground = foreign_foreground_window()
        self.toast.hide_now()
        delay = 0
        if source in ("dashboard", "tray"):
            # let our own window or the tray menu disappear from the screen first
            for w in QApplication.topLevelWidgets():
                if w.isVisible() and w.objectName() == "appRoot":
                    w.hide()
                    delay = 260
            delay = max(delay, 160 if source == "tray" else 0)
        QTimer.singleShot(delay, lambda: self._begin_capture(mode or self.settings.capture_mode))
        return True

    def _begin_capture(self, mode: str) -> None:
        try:
            snapshot = self._snapshotter()
        except CaptureError as exc:
            self._starting = False
            self._toast("error", "Screen capture failed", str(exc))
            return
        except Exception:
            self._starting = False
            log.exception("Screen capture failed")
            self._toast("error", "Screen capture failed", "An unexpected error occurred. See the log for details.")
            return
        if mode == "desktop":
            self._starting = False
            self._on_selected(snapshot, snapshot.bounds, "desktop")
            return
        if mode == "active":
            rect = self._active_window_rect(snapshot)
            if rect is not None:
                self._starting = False
                self._on_selected(snapshot, rect, "active")
                return
            mode = "window"  # no usable foreground window: let the user pick one
        from textsnap.ui.overlay import SelectionSession
        s = self.settings
        session = SelectionSession(snapshot, mode, magnifier=s.show_magnifier, crosshair=s.show_crosshair,
                                   dimensions=s.show_dimensions, dim_percent=s.overlay_dim_percent,
                                   min_px=s.min_selection_px, last_region=self._last_region)
        session.selected.connect(lambda rect, m: self._on_selected(snapshot, rect, m))
        session.cancelled.connect(lambda: self._on_cancelled(snapshot))
        self.session = session
        self._starting = False
        self.trigger.set_watch_escape(True)
        session.start()

    def _active_window_rect(self, snapshot: DesktopSnapshot) -> Rect | None:
        """Frame bounds of the window that had focus when the capture started."""
        if not self._prev_foreground:
            return None
        from textsnap.capture.windows import window_rect
        rect = window_rect(self._prev_foreground)
        if rect is None:
            return None
        rect = rect.intersected(snapshot.bounds)
        return None if rect.empty or rect.w < 8 or rect.h < 8 else rect

    def _end_session(self) -> None:
        self.session = None
        self.trigger.set_watch_escape(False)

    def _on_cancelled(self, snapshot: DesktopSnapshot) -> None:
        self._end_session()
        snapshot.release()
        self._restore_focus()
        log.info("Capture cancelled")

    def _on_selected(self, snapshot: DesktopSnapshot, rect: Rect, mode: str) -> None:
        self._end_session()
        try:
            crop = snapshot.crop(rect)
            rgb = qimage_to_rgb(crop)
        except (CaptureError, ValueError) as exc:
            snapshot.release()
            self._restore_focus()
            self._toast("error", "Capture failed", str(exc))
            return
        snapshot.release()
        if mode != "repeat":
            self._last_region = rect
        self._restore_focus()
        if self.settings.save_captures:
            self._save_capture(crop)
        log.info("Captured %dx%d px (%s)", rect.w, rect.h, mode)
        self.run_ocr(rgb, _JobContext(mode, rect=rect))

    def capture_full_desktop(self, source: str = "tray") -> None:
        self.start_capture("desktop", source)

    def repeat_last_region(self) -> None:
        if self._last_region is None:
            self._toast("info", "Nothing to repeat yet", "Make a selection first; TextSnap remembers its position.")
            return
        if self.capture_active:
            return
        self._prev_foreground = 0
        try:
            snapshot = self._snapshotter(with_windows=False)
        except CaptureError as exc:
            self._toast("error", "Screen capture failed", str(exc))
            return
        if snapshot.bounds.intersected(self._last_region).empty:
            snapshot.release()
            self._toast("warning", "Previous area is off-screen", "The display layout has changed.")
            return
        self._on_selected(snapshot, self._last_region, "repeat")

    def _restore_focus(self) -> None:
        hwnd, self._prev_foreground = self._prev_foreground, 0
        if hwnd and self.settings.restore_focus:
            from textsnap.winsys.focus import restore_foreground
            QTimer.singleShot(0, lambda: restore_foreground(hwnd))

    def _save_capture(self, image: QImage) -> None:
        folder = Path(self.settings.save_captures_dir) if self.settings.save_captures_dir else None
        if folder is None:
            self._toast("warning", "Capture not saved", "Choose a folder for saved captures in Privacy & storage.")
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
            name = folder / time.strftime("TextSnap-%Y%m%d-%H%M%S.png")
            n = 1
            while name.exists():
                name = folder / time.strftime(f"TextSnap-%Y%m%d-%H%M%S-{n}.png")
                n += 1
            if not image.save(str(name), "PNG"):
                raise OSError("the image could not be written")
            log.info("Capture image saved (user setting)")
        except OSError as exc:
            self._toast("error", "Capture image not saved", str(exc))

    # ------------------------------------------------------------------ other sources
    def ocr_clipboard_image(self) -> None:
        clip = QGuiApplication.clipboard()
        mime = clip.mimeData()
        image = clip.image()
        if not image.isNull():
            self.run_ocr(qimage_to_rgb(image), _JobContext("clipboard"))
            return
        if mime is not None and mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith(IMAGE_SUFFIXES):
                    self.ocr_image_file(url.toLocalFile())
                    return
        self._toast("info", "No image on the clipboard", "Copy an image (or an image file) first, then try again.")

    def ocr_image_file(self, path: str | None = None, parent: QWidget | None = None) -> None:
        if path is None:
            patterns = " ".join(f"*{s}" for s in IMAGE_SUFFIXES)
            path, _ = QFileDialog.getOpenFileName(parent, "Choose an image", str(Path.home() / "Pictures"),
                                                  f"Images ({patterns});;All files (*.*)")
            if not path:
                return
        try:
            rgb = load_image(path)
        except DocumentError as exc:
            self._toast("error", "Image could not be read", str(exc))
            return
        self.run_ocr(rgb, _JobContext("file", file_name=Path(path).name, open_window=True))

    def ocr_pdf(self, path: str, pages: list[int], use_embedded: bool, dpi: int = 300) -> int:
        options = self.ocr_options()
        pipeline = self.pipeline

        def work(cancel, progress):
            doc = PdfDocument(path)
            parts: list[str] = []
            confidences: list[float] = []
            started = time.perf_counter()
            try:
                for i, index in enumerate(pages):
                    if cancel.is_set():
                        raise OcrCancelled("cancelled")
                    progress(i, len(pages))
                    text = doc.embedded_text(index).strip() if use_embedded else ""
                    if not text:
                        result = pipeline.recognize(doc.render(index, dpi), options, cancel)
                        text = result.text
                        if result.confidence is not None:
                            confidences.append(result.confidence)
                    parts.append(f"--- Page {index + 1} ---\n{text}" if len(pages) > 1 else text)
                progress(len(pages), len(pages))
            finally:
                doc.close()
            text = "\n\n".join(parts)
            from textsnap.ocr.text import text_direction
            conf = sum(confidences) / len(confidences) if confidences else None
            return OcrResult(text, conf, options.language, options.quality, (time.perf_counter() - started) * 1000,
                             len(text.split()), text_direction(text),
                             notes=[f"{len(parts)} of {len(pages)} page(s) processed"]), []

        if self._pdf_job:
            self.jobs.cancel(self._pdf_job)
        job = self.jobs.submit(work)
        self._jobs[job] = _JobContext("pdf", file_name=Path(path).name, open_window=True, can_rerun=False)
        self._pdf_job = job
        self.busy_changed.emit(True)
        return job

    def cancel_job(self, job_id: int) -> None:
        self.jobs.cancel(job_id)

    # ------------------------------------------------------------------ OCR
    def run_ocr(self, rgb: np.ndarray, ctx: _JobContext, language: str | None = None,
                quality: str | None = None) -> int:
        if ctx.can_rerun:
            self._last_image = rgb
            self._last_context = ctx
            self._purge_timer.start(KEEP_CAPTURE_MS)
        options = self.ocr_options(language, quality)
        detect_qr = self.settings.detect_qr
        pipeline = self.pipeline

        def work(cancel, progress):
            result = pipeline.recognize(rgb, options, cancel)
            qr = decode_qr(rgb) if detect_qr else []
            return result, qr

        job = self.jobs.submit(work)
        self._jobs[job] = ctx
        if self._current_job in self._jobs and self._current_job != job:
            self.jobs.cancel(self._current_job)  # superseded
        self._current_job = job
        self.busy_changed.emit(True)
        if not ctx.rerun:
            self._busy_toast.start(1200)
        return job

    def rerun(self, language: str, quality: str) -> None:
        if self._last_image is None or self._last_context is None:
            if self.result_window is not None:
                self.result_window.copy_feedback(False, "The original capture is no longer in memory.")
            return
        ctx = dataclasses.replace(self._last_context, rerun=True, started=time.monotonic())
        self.run_ocr(self._last_image, ctx, language, quality)

    def forget_capture(self) -> None:
        """Drop the last captured pixels from memory."""
        self._last_image = None
        self._last_context = None

    def _job_progress(self, job_id: int, done: int, total: int) -> None:
        ctx = self._jobs.get(job_id)
        if ctx is not None and ctx.source == "pdf":
            self.pdf_progress.emit(done, total)

    def _job_failed(self, job_id: int, message: str) -> None:
        ctx = self._jobs.pop(job_id, None)
        if ctx is None:
            return
        if ctx.source == "engine-status":
            self.engine_status = EngineStatus(False, self.engine.folder, error=message)
            self.engine_status_changed.emit(self.engine_status)
            return
        if ctx.source == "self-check":
            self.self_check_done.emit(message)
            return
        if ctx.source == "warm-up":
            log.info("Engine warm-up failed: %s", message)
            return
        self._retire_idle_pipelines()
        if not self._is_current(job_id, ctx):
            return
        if ctx.source == "pdf":
            self._pdf_job = 0
        self._end_busy()
        if message == "cancelled":
            self.toast.hide_now()
            return
        log.warning("Recognition failed: %s", message)
        record = CaptureResult(job_id, ctx.source, error=message, rect=ctx.rect, file_name=ctx.file_name,
                               can_rerun=ctx.can_rerun)
        self.last_record = record
        self._set_last_status(f"Last capture failed ({ctx.source})")
        if ctx.rerun or ctx.open_window:
            self.show_result(record)
        else:
            self._toast("error", "Text recognition failed", message,
                        actions=[("Details", lambda: self.show_result(record))])

    def _job_finished(self, job_id: int, payload: object) -> None:
        ctx = self._jobs.pop(job_id, None)
        if ctx is None:
            return
        if ctx.source == "engine-status":
            self.engine_status = payload  # type: ignore[assignment]
            if not self.engine_status.ok:
                log.error("OCR engine problem: %s", self.engine_status.error)
            else:
                self._warm_up()
            self.engine_status_changed.emit(self.engine_status)
            return
        if ctx.source == "warm-up":
            return
        if ctx.source == "self-check":
            self.self_check_done.emit(payload)
            return
        self._retire_idle_pipelines()
        if not self._is_current(job_id, ctx):
            return  # superseded by a newer capture
        if ctx.source == "pdf":
            self._pdf_job = 0
        self._end_busy()
        result, qr = payload  # type: ignore[misc]
        record = CaptureResult(job_id, ctx.source, result=result, qr=list(qr), rect=ctx.rect,
                               file_name=ctx.file_name, can_rerun=ctx.can_rerun)
        if ctx.rerun:
            self.last_record = record
            if self.result_window is not None:
                self.result_window.show_record(record)
            return
        text = result.text
        if text and self.settings.auto_copy:
            from textsnap.ocr.text import clean_text
            to_copy = clean_text(text) if self.settings.copy_cleaned else text
            res = self.clipboard.set_text(to_copy, self.settings.exclude_from_clipboard_history)
            record.copied, record.copy_error = res.ok, res.error
        if text and self.settings.history_enabled:
            self._add_history(text, result.language, ctx.source)
        self.last_record = record
        when = time.strftime("%H:%M")
        if text:
            verb = "Copied" if record.copied else "Recognised"
            self._set_last_status(f"{verb} {len(text)} characters from {record.source_label.lower()} at {when}")
        else:
            self._set_last_status(f"No text found in the last capture ({when})")
        self.result_ready.emit(record)
        window_shown = ctx.open_window or self.settings.open_result_window
        if window_shown:
            self.show_result(record, activate=True)
        elif self.settings.show_toast or not record.copied:
            self._toast_for(record)
        if record.copied and self.settings.auto_paste and ctx.source in SCREEN_SOURCES and not window_shown:
            QTimer.singleShot(150, self._auto_paste)

    def _toast_for(self, record: CaptureResult) -> None:
        res = record.result
        assert res is not None
        view = ("View", lambda: self.show_result(record))
        qr_actions = [("QR code", lambda: self.show_result(record))] if record.qr else []
        if res.empty:
            body = (res.notes[0] if res.notes else "Try a larger area, or the Thorough mode.")
            if record.qr:
                body = "But a QR code was found."
            actions = qr_actions or []
            if record.can_rerun and res.quality != "thorough":
                actions.append(("Try thorough", lambda: self._thorough_retry()))
            self._toast("warning", "No text found", body, actions=actions)
            return
        info = f"{len(res.text)} characters · {LANGUAGE_LABELS.get(res.language, res.language)}"
        if record.copied:
            self._toast("success", "Text copied", f"Paste with Ctrl+V · {info}", actions=qr_actions + [view],
                        near=record.rect)
        elif record.copy_error:
            self._toast("error", "Couldn't copy to the clipboard", record.copy_error, actions=[view])
        else:
            self._toast("info", "Text recognised", info,
                        actions=[("Copy", lambda: self.copy_text(res.text)), view])

    def _thorough_retry(self) -> None:
        if self._last_image is None or self._last_context is None:
            return
        ctx = dataclasses.replace(self._last_context, rerun=False, open_window=False, started=time.monotonic())
        self.run_ocr(self._last_image, ctx, quality="thorough")

    def _auto_paste(self) -> None:
        from textsnap.winsys.sendinput import send_paste
        if not send_paste():
            log.info("Automatic paste skipped (modifier keys still held)")

    # ------------------------------------------------------------------ results UI
    def ensure_result_window(self):
        if self.result_window is None:
            from textsnap.ui.result_window import ResultWindow
            w = ResultWindow(lambda: self.settings)
            w.copy_requested.connect(self.copy_text)
            w.rerun_requested.connect(self.rerun)
            w.snippet_requested.connect(self.save_snippet)
            w.search_requested.connect(self.search_web)
            w.save_dir_changed.connect(lambda d: self.update_settings(last_save_dir=d))
            w.cleared.connect(self.clear_result)
            self.busy_changed.connect(w.busy)
            self.result_window = w
        return self.result_window

    def show_result(self, record: CaptureResult | None = None, activate: bool = True) -> None:
        record = record or self.last_record
        w = self.ensure_result_window()
        if record is None:
            w.show()
            w.raise_()
            w.activateWindow()
            return
        w.show_record(record, activate=activate)

    def clear_result(self) -> None:
        self.last_record = None
        self.forget_capture()
        self._set_last_status("Result cleared")

    def copy_text(self, text: str) -> bool:
        res = self.clipboard.set_text(text, self.settings.exclude_from_clipboard_history)
        if self.result_window is not None and self.result_window.isVisible():
            self.result_window.copy_feedback(res.ok, "Copied to clipboard" if res.ok else res.error)
        elif not res.ok:
            self._toast("error", "Couldn't copy to the clipboard", res.error)
        return res.ok

    def search_web(self, text: str) -> None:
        template = safe_search_url(self.settings.search_url)  # never hand file:/custom schemes to the opener
        QDesktopServices.openUrl(QUrl(template.replace("{query}", quote_plus(text[:300]))))

    def save_snippet(self, text: str, title: str) -> None:
        from textsnap.ui import dialogs
        if not self.settings.history_enabled:
            if not dialogs.confirm(
                    self.result_window, "Turn on history to save snippets?",
                    "Snippets are kept in TextSnap's local history, which is currently off. Recognised text will "
                    "then be stored on this computer until you delete it.", "Turn on history"):
                return
            self.update_settings(history_enabled=True)
        try:
            self.history.add(text, "", "snippet", pinned=True, title=title)
        except HistoryError as exc:
            dialogs.inform(self.result_window, "Snippet not saved", str(exc), "error")
            return
        self.history_changed.emit()
        if self.result_window is not None:
            self.result_window.copy_feedback(True, "Saved as a pinned snippet")

    # ------------------------------------------------------------------ history
    def _open_history(self) -> None:
        try:
            self.history.open()
            self._purge_history()
        except HistoryError as exc:
            log.error("History unavailable: %s", exc)
            self._toast("error", "History unavailable", str(exc))

    def _purge_history(self) -> None:
        try:
            removed = self.history.purge_older_than(self.settings.history_retention_days)
            if removed:
                log.info("Removed %d expired history entries", removed)
        except HistoryError as exc:
            log.error("History purge failed: %s", exc)

    def _add_history(self, text: str, language: str, source: str) -> None:
        try:
            self.history.add(text, language, source)
            self.history_changed.emit()
        except HistoryError as exc:
            log.error("History write failed: %s", exc)

    def disable_history(self, delete_entries: bool) -> None:
        self.update_settings(history_enabled=False)
        if delete_entries:
            try:
                self.history.destroy()
            except HistoryError as exc:
                self._toast("error", "History not deleted", str(exc))
        self.history_changed.emit()

    # ------------------------------------------------------------------ helpers
    def _toast(self, kind: str, title: str, body: str = "", actions=None, near: Rect | None = None) -> None:
        rect = None
        if near is not None:
            # Show the toast on the monitor where the capture happened.
            from textsnap.capture.geometry import monitor_at
            from textsnap.capture.screen import current_monitors
            try:
                m = monitor_at(current_monitors(), near.x + near.w // 2, near.y + near.h // 2)
            except Exception:
                m = None
            if m is not None:
                rect = QRect(m.logical.x, m.logical.y, m.logical.w, m.logical.h)
        self.toast.show_message(kind, title, body, self.settings.toast_seconds if kind == "success" else
                                max(5.0, self.settings.toast_seconds), actions, rect)

    def _set_last_status(self, status: str) -> None:
        self.last_status = status
        self.last_status_changed.emit(status)
