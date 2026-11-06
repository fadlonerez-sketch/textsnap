"""Shared fixtures.

* Every test gets its own temporary TextSnap data directory, so the user's
  real settings, history and logs are never read or written.
* Qt runs on the offscreen platform unless desktop tests are requested
  (TEXTSNAP_DESKTOP_TESTS=1), which need real windows and input.
* OCR tests use the real bundled Tesseract. If it is missing the tests
  fail loudly; they are never replaced by a stub.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DESKTOP = os.environ.get("TEXTSNAP_DESKTOP_TESTS") == "1"
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if DESKTOP else "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from textsnap.storage import paths  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "desktop: drives the real desktop (set TEXTSNAP_DESKTOP_TESTS=1)")
    config.addinivalue_line("markers", "ocr: runs the real Tesseract engine")


def pytest_collection_modifyitems(config, items):
    if DESKTOP:
        return
    skip = pytest.mark.skip(reason="desktop test: set TEXTSNAP_DESKTOP_TESTS=1 to run")
    for item in items:
        if "desktop" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    data = tmp_path / "textsnap-data"
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(data))
    paths.set_data_dir(None)
    yield data
    paths.set_data_dir(None)


@pytest.fixture(scope="session")
def engine():
    from textsnap.ocr.engine import TesseractEngine

    eng = TesseractEngine(paths.bundled_tesseract_dir())
    status = eng.status()
    if not status.ok:
        pytest.fail(f"Bundled Tesseract unavailable: {status.error}")
    for model in ("best", "fast"):
        missing = {"heb", "eng"} - set(status.languages.get(model, []))
        if missing:
            pytest.fail(f"Bundled {model} models missing languages: {sorted(missing)}")
    return eng


@pytest.fixture(scope="session")
def pipeline(engine):
    from textsnap.ocr.pipeline import OcrPipeline

    p = OcrPipeline(engine)
    yield p
    p.shutdown()


@pytest.fixture
def render(qapp):
    from textsnap.ocr import samples

    samples.ensure_fonts()
    return samples.render_lines
