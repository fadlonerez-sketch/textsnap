from __future__ import annotations

import threading

from textsnap.app.jobs import JobRunner
from textsnap.ocr.engine import OcrCancelled, OcrError


def test_result_delivered_on_gui_thread(qtbot):
    runner = JobRunner(2)
    main = threading.get_ident()
    seen = {}

    def on_finished(job_id, payload):
        seen["thread"] = threading.get_ident()
        seen["payload"] = payload

    runner.finished.connect(on_finished)
    with qtbot.waitSignal(runner.finished, timeout=3000):
        job = runner.submit(lambda cancel, progress: threading.get_ident())
    assert seen["thread"] == main and seen["payload"] != main  # worked off-thread, delivered on-thread
    assert job == 1 and runner.active == 0


def test_errors_are_mapped(qtbot):
    runner = JobRunner(2)

    def failing(exc):
        def work(cancel, progress):
            raise exc
        return work

    with qtbot.waitSignal(runner.failed, timeout=3000) as sig:
        runner.submit(failing(OcrError("engine said no")))
    assert sig.args[1] == "engine said no"
    with qtbot.waitSignal(runner.failed, timeout=3000) as sig:
        runner.submit(failing(OcrCancelled("x")))
    assert sig.args[1] == "cancelled"
    with qtbot.waitSignal(runner.failed, timeout=3000) as sig:
        runner.submit(failing(KeyError("secret recognised text")))
    assert "KeyError" in sig.args[1] and "secret" not in sig.args[1]


def test_cancel_sets_event_and_progress(qtbot):
    runner = JobRunner(1)
    started = threading.Event()
    progress_seen = []
    runner.progress.connect(lambda j, d, t: progress_seen.append((d, t)))

    def work(cancel, progress):
        progress(1, 3)
        started.set()
        assert cancel.wait(3)
        raise OcrCancelled("stopped")

    with qtbot.waitSignal(runner.failed, timeout=5000) as sig:
        job = runner.submit(work)
        assert started.wait(3)
        runner.cancel(job)
    assert sig.args == [job, "cancelled"]
    qtbot.waitUntil(lambda: progress_seen == [(1, 3)], timeout=2000)
    assert runner.wait(2000)
