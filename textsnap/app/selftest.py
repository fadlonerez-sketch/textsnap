"""Self-test that exercises the real bundled OCR resources.

``run_ocr_checks`` recognises synthetic Hebrew, English and mixed images
with the actual engine and both model sets and grades them by character
accuracy. ``run_full`` (``TextSnap.exe --self-test``) adds resource
discovery, the overlay, the clipboard round trip and the keyboard hook, and
writes a JSON report. It uses an isolated data directory and synthetic
content only.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

log = logging.getLogger(__name__)

PASS_ACCURACY = 0.95


def _cer(expected: str, actual: str) -> float:
    a, b = " ".join(expected.split()), " ".join(actual.split())
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(1, len(a))


def sample_images():
    """Render on the GUI thread (QPainter + fonts)."""
    from textsnap.ocr import samples
    return [("English", samples.ENGLISH, samples.render_lines(samples.ENGLISH, px=15)),
            ("Hebrew", samples.HEBREW, samples.render_lines(samples.HEBREW, px=16)),
            ("Hebrew + English", samples.MIXED, samples.render_lines(samples.MIXED, px=15))]


def run_ocr_checks(pipeline, images, model: str = "best") -> list[dict]:
    from textsnap.ocr.pipeline import OcrOptions
    results = []
    for name, lines, rgb in images:
        expected = "\n".join(lines)
        r = pipeline.recognize(rgb, OcrOptions(language="heb+eng", model=model))
        accuracy = max(0.0, 1.0 - _cer(expected, r.text))
        results.append({"name": name, "model": model, "accuracy": accuracy, "passed": accuracy >= PASS_ACCURACY,
                        "ms": r.duration_ms, "chars": len(r.text)})
    return results


def run_full(report_path: Path, ui: bool = True, clipboard: bool = False, hook: bool = True) -> int:
    """Packaged-build self-test. Returns the process exit code (0 = all passed)."""
    from PySide6.QtWidgets import QApplication

    from textsnap.storage import paths

    report: dict = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "frozen": paths.is_frozen(),
                    "executable": sys.executable, "checks": []}

    def check(name: str, fn):
        t = time.perf_counter()
        entry = {"name": name}
        try:
            detail = fn()
            entry.update(ok=True, detail=detail)
        except Exception as exc:
            entry.update(ok=False, error=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc(limit=4))
        entry["ms"] = round((time.perf_counter() - t) * 1000)
        report["checks"].append(entry)
        return entry

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from textsnap.ocr.engine import TesseractEngine
    from textsnap.ocr.pipeline import OcrPipeline

    engine = TesseractEngine(paths.bundled_tesseract_dir())

    def resources():
        root = paths.resource_root()
        needed = [paths.bundled_tesseract_dir() / "tesseract.exe", paths.assets_dir() / "textsnap.ico",
                  root / "THIRD_PARTY_NOTICES.md"]
        for model in ("best", "fast"):
            for lang in ("heb", "eng"):
                needed.append(paths.bundled_tesseract_dir() / "tessdata" / model / f"{lang}.traineddata")
        missing = [str(p) for p in needed if not p.exists()]
        if missing:
            raise FileNotFoundError(", ".join(missing))
        return {"resource_root": str(root), "files_checked": len(needed)}

    check("bundled resources present", resources)

    def engine_status():
        st = engine.status(refresh=True)
        if not st.ok:
            raise RuntimeError(st.error)
        for model in ("best", "fast"):
            if not {"heb", "eng"} <= set(st.languages.get(model, [])):
                raise RuntimeError(f"{model} models incomplete: {st.languages.get(model)}")
        return {"version": st.version, "folder": str(st.folder), "languages": st.languages}

    check("OCR engine starts and lists Hebrew + English", engine_status)

    pipeline = OcrPipeline(engine)
    images = sample_images()
    for model in ("best", "fast"):
        def ocr(model=model):
            results = run_ocr_checks(pipeline, images, model)
            failed = [r for r in results if not r["passed"]]
            if failed:
                raise AssertionError(f"low accuracy: {failed}")
            return results
        check(f"recognise synthetic Hebrew/English/mixed ({model} models)", ocr)
    pipeline.shutdown()

    if clipboard:
        def clip():
            from textsnap.clipboard.clipboard import ClipboardService
            from PySide6.QtWidgets import QWidget
            owner = QWidget()
            svc = ClipboardService(owner=lambda: int(owner.winId()))
            previous = svc.get_text()
            sample = "TextSnap self-test שלום 123"
            res = svc.set_text(sample)
            if not res.ok:
                raise RuntimeError(res.error)
            back = svc.get_text()
            if previous is not None:
                svc.set_text(previous)  # put the user's clipboard text back
            if back != sample:
                raise AssertionError("clipboard read-back mismatch")
            return {"attempts": res.attempts, "restored_previous_text": previous is not None}
        check("clipboard Unicode round trip", clip)

    if ui:
        def overlay():
            from PySide6.QtCore import QEventLoop, QTimer
            from PySide6.QtGui import QColor, QImage
            from textsnap.capture.screen import DesktopSnapshot, current_monitors
            from textsnap.capture.geometry import virtual_bounds
            from textsnap.ui.overlay import SelectionSession
            monitors = current_monitors()
            bounds = virtual_bounds(monitors)
            img = QImage(bounds.w, bounds.h, QImage.Format.Format_RGB32)
            img.fill(QColor(40, 90, 160))  # synthetic: the real desktop is not captured
            snap = DesktopSnapshot(monitors, bounds, img)
            session = SelectionSession(snap, activate=False)
            session.start()
            shown = [w.isVisible() for w in session.windows]
            loop = QEventLoop()
            QTimer.singleShot(400, loop.quit)
            loop.exec()
            session.cancel()
            app.processEvents()
            if not shown or not all(shown):
                raise RuntimeError("overlay windows did not appear")
            return {"monitors": len(monitors), "overlay_windows": len(shown)}
        check("selection overlay opens and closes", overlay)

    if hook:
        def keyboard_hook():
            from textsnap.keyboard.detector import TriggerConfig
            from textsnap.keyboard.hook import KeyboardHook
            from textsnap.keyboard.keys import trigger_vks
            h = KeyboardHook(lambda: None)
            h.start(TriggerConfig(trigger_vks(["F24"]), 500))
            installed = h.hooks_installed
            h.stop()
            if not installed:
                raise RuntimeError("hook not installed")
            if h.hooks_installed:
                raise RuntimeError("hook not removed on stop")
            return {"installed_and_removed": True}
        check("keyboard hook installs and uninstalls", keyboard_hook)

    def spacebar_trigger():
        """Default trigger and the hold-back logic (no keys are sent: the injector only records)."""
        from textsnap.keyboard.detector import LongPressDetector, TriggerConfig
        from textsnap.keyboard.intercept import KeyInterceptor
        from textsnap.keyboard.keys import VK_SPACE, trigger_vks
        from textsnap.storage.settings import Settings
        if Settings().trigger_keys != ["Space"] or Settings().hold_ms != 500:
            raise AssertionError(f"default trigger is {Settings().trigger_keys} {Settings().hold_ms} ms")
        clock = [0.0]
        timers: dict[int, float] = {}
        sent: list = []
        fired = []

        class Sched:
            def start(self, ms):
                timers[len(timers) + 1] = clock[0] + ms / 1000
                return len(timers)

            def cancel(self, handle):
                timers.pop(handle, None)

        icp = KeyInterceptor(lambda events: sent.extend(events) or True, lambda keys: False, lambda: clock[0])
        det = LongPressDetector(Sched(), lambda: (icp.on_activated(), fired.append(1)), clock=lambda: clock[0],
                                is_key_down=icp.holding)
        icp.attach(det)
        det.configure(TriggerConfig(trigger_vks(["Space"]), 500))

        def advance(s):
            clock[0] += s
            for h, due in list(timers.items()):
                if due <= clock[0]:
                    timers.pop(h)
                    det.timer_fired(h)

        blocked_tap = icp.on_key(VK_SPACE, 0x39, False, True)
        advance(0.08)
        icp.on_key(VK_SPACE, 0x39, False, False)
        tap_ok = blocked_tap and len(sent) == 2 and not fired
        sent.clear()
        icp.on_key(VK_SPACE, 0x39, False, True)
        advance(0.6)
        icp.on_key(VK_SPACE, 0x39, False, False)
        hold_ok = fired == [1] and not sent
        icp.on_key(VK_SPACE, 0x39, False, True)
        roll_blocked = icp.on_key(0x42, 0x30, False, True)
        roll_ok = roll_blocked and [getattr(e, "vk", None) for e in sent] == [VK_SPACE, 0x42]
        if not (tap_ok and hold_ok and roll_ok):
            raise AssertionError(f"tap={tap_ok} hold={hold_ok} rollover={roll_ok}")
        return {"default": "Spacebar, 500 ms", "tap_replays_one_space": True, "hold_activates_once": True,
                "rollover_keeps_order": True}

    check("Spacebar trigger logic (default, tap, hold, roll-over)", spacebar_trigger)

    report["passed"] = all(c["ok"] for c in report["checks"])
    report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if report["passed"] else 1


def isolated_env() -> None:
    """Point the data directory at a temporary folder for the self-test."""
    import tempfile
    from textsnap.storage import paths
    if not os.environ.get(paths.ENV_DATA_DIR):
        paths.set_data_dir(Path(tempfile.mkdtemp(prefix="textsnap-selftest-")))
