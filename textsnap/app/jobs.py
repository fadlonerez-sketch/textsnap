"""Background jobs on a bounded QThreadPool.

Work functions run on pool threads and never touch widgets; results return
through queued signals and are handled on the GUI thread. Every job has a
cancel event, and the controller ignores results of superseded jobs.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from textsnap.ocr.engine import OcrCancelled, OcrError
from textsnap.ocr.documents import DocumentError

log = logging.getLogger(__name__)

Work = Callable[[threading.Event, Callable[[int, int], None]], Any]


class JobSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, int, int)


class _Runnable(QRunnable):
    def __init__(self, job_id: int, work: Work, signals: JobSignals, cancel: threading.Event):
        super().__init__()
        self.job_id, self.work, self.signals, self.cancel = job_id, work, signals, cancel
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            payload = self.work(self.cancel, lambda done, total: self.signals.progress.emit(self.job_id, done, total))
        except OcrCancelled:
            self.signals.failed.emit(self.job_id, "cancelled")
        except (OcrError, DocumentError) as exc:
            self.signals.failed.emit(self.job_id, str(exc))
        except Exception as exc:  # unexpected: log the type only (no user content)
            log.exception("Background job failed")
            self.signals.failed.emit(self.job_id, f"Unexpected error ({type(exc).__name__}). See the log for details.")
        else:
            self.signals.finished.emit(self.job_id, payload)


class JobRunner(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, int, int)

    def __init__(self, max_threads: int = 2, parent: QObject | None = None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max_threads)
        self._next = 0
        self._cancels: dict[int, threading.Event] = {}
        self._signals = JobSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._signals.progress.connect(self.progress)

    def submit(self, work: Work) -> int:
        self._next += 1
        job_id = self._next
        cancel = threading.Event()
        self._cancels[job_id] = cancel
        self.pool.start(_Runnable(job_id, work, self._signals, cancel))
        return job_id

    def cancel(self, job_id: int) -> None:
        event = self._cancels.get(job_id)
        if event is not None:
            event.set()

    def cancel_all(self) -> None:
        for event in self._cancels.values():
            event.set()

    @property
    def active(self) -> int:
        return len(self._cancels)

    def wait(self, ms: int = 5000) -> bool:
        return self.pool.waitForDone(ms)

    def _on_finished(self, job_id: int, payload: object) -> None:
        self._cancels.pop(job_id, None)
        self.finished.emit(job_id, payload)

    def _on_failed(self, job_id: int, message: str) -> None:
        self._cancels.pop(job_id, None)
        self.failed.emit(job_id, message)
