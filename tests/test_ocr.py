"""Recognition with the real bundled Tesseract on synthetic images.

OCR output can differ by a character between engine builds, so most checks
use a character error rate (CER) bound or required tokens rather than exact
equality; the bounds are tight enough that a broken pipeline fails.
"""

from __future__ import annotations

import shutil
import threading
import unicodedata

import numpy as np
import pytest

from textsnap.ocr import samples
from textsnap.ocr.engine import (
    EngineUnavailableError, MissingLanguageError, OcrCancelled, OcrError, OcrTimeoutError, TesseractEngine,
)
from textsnap.ocr.pipeline import OcrOptions, OcrPipeline

pytestmark = pytest.mark.ocr


def cer(expected: str, actual: str) -> float:
    a, b = " ".join(expected.split()), " ".join(actual.split())
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(1, len(a))


def ocr(pipeline, rgb, **kw):
    return pipeline.recognize(rgb, OcrOptions(**kw))


def test_engine_reports_version_and_languages(engine):
    st = engine.status()
    assert st.ok and st.version.startswith("5.")
    for model in ("best", "fast"):
        assert {"heb", "eng"} <= set(st.languages[model])
    assert "Hebrew" in st.summary() and "English" in st.summary()


def test_english(pipeline, render):
    r = ocr(pipeline, render(samples.ENGLISH, px=15))
    assert cer("\n".join(samples.ENGLISH), r.text) <= 0.02, r.text
    assert r.direction == "ltr" and r.confidence and r.confidence > 70


def test_digits_and_punctuation(pipeline, render):
    r = ocr(pipeline, render(["Invoice #4521 total: $1,299.50 (due 2026-11-03)", "Call +972-3-555-0199 now!"], px=16))
    for token in ["#4521", "$1,299.50", "(due", "2026-11-03)", "+972-3-555-0199", "now!"]:
        assert token in r.text, (token, r.text)


def test_hebrew(pipeline, render):
    r = ocr(pipeline, render(samples.HEBREW, px=16))
    assert cer("\n".join(samples.HEBREW), r.text) <= 0.03, r.text
    assert r.direction == "rtl"
    # logical order: the text starts with the first Hebrew word, not its reversal
    assert r.text.startswith("שלום")
    assert "120" in r.text


def test_hebrew_only_model(pipeline, render):
    r = ocr(pipeline, render(samples.HEBREW, px=16), language="heb")
    assert r.language == "heb"
    assert cer("\n".join(samples.HEBREW), r.text) <= 0.03, r.text


def test_mixed_hebrew_english(pipeline, render):
    r = ocr(pipeline, render(samples.MIXED, px=15))
    assert cer("\n".join(samples.MIXED), r.text) <= 0.03, r.text
    assert "Microsoft" in r.text and "report.pdf" in r.text
    assert "הפגישה עם Microsoft" in r.text  # short Hebrew word next to English survived


def test_mixed_script_fix_corrects_short_hebrew_word(pipeline, render):
    rgb = render(["הפגישה עם Microsoft תתקיים ביום שלישי"], px=15)
    plain = ocr(pipeline, rgb, fix_mixed_script=False)
    fixed = ocr(pipeline, rgb, fix_mixed_script=True)
    assert cer("הפגישה עם Microsoft תתקיים ביום שלישי", fixed.text) <= cer(
        "הפגישה עם Microsoft תתקיים ביום שלישי", plain.text)
    assert fixed.text.strip() == "הפגישה עם Microsoft תתקיים ביום שלישי"


def test_hebrew_prefix_with_english_word(pipeline, render):
    r = ocr(pipeline, render(["שלחתי מייל ל-John Smith לגבי ה-API החדש"], px=13))
    assert r.text.strip() == "שלחתי מייל ל-John Smith לגבי ה-API החדש", r.text


def test_multiple_lines_preserved(pipeline, render):
    lines = ["First line of text", "Second line here", "Third and final line"]
    r = ocr(pipeline, render(lines, px=15))
    assert r.text.count("\n") == 2, r.text
    assert cer("\n".join(lines), r.text) <= 0.02


def test_paragraph_break(pipeline, render):
    img = np.vstack([render(["Paragraph one is here."], px=15),
                     np.full((40, 400, 3), 255, np.uint8)[:, : render(["x"], px=15).shape[1]][:, :1].repeat(1, 1)
                     if False else np.full((40, render(["Paragraph one is here."], px=15).shape[1], 3), 255, np.uint8),
                     render(["Paragraph two follows."], px=15)])
    r = ocr(pipeline, img)
    assert "\n\n" in r.text, r.text


def test_unicode_output_is_nfc_and_clean(pipeline, render):
    r = ocr(pipeline, render(samples.MIXED, px=15))
    assert unicodedata.normalize("NFC", r.text) == r.text
    assert "\u200e" not in r.text and "\u200f" not in r.text  # bidi marks stripped by default
    raw = ocr(pipeline, render(samples.MIXED, px=15), strip_bidi=False)
    assert cer(r.text, raw.text.replace("\u200e", "").replace("\u200f", "")) < 0.01


@pytest.mark.parametrize("theme", ["dark", "color"])
def test_dark_and_colored_text(pipeline, render, theme):
    fg, bg = {"dark": ((225, 225, 225), (30, 30, 36)), "color": ((190, 40, 40), (238, 244, 250))}[theme]
    r = ocr(pipeline, render(samples.ENGLISH, px=14, fg=fg, bg=bg))
    assert cer("\n".join(samples.ENGLISH), r.text) <= 0.03, r.text


def test_small_text_is_upscaled(pipeline, render):
    r = ocr(pipeline, render(samples.ENGLISH, px=10))
    assert cer("\n".join(samples.ENGLISH), r.text) <= 0.05, r.text


def test_thorough_mode(pipeline, render):
    r = ocr(pipeline, render(samples.HEBREW, px=13, fg=(230, 230, 230), bg=(30, 30, 35)), quality="thorough")
    assert r.quality == "thorough" and r.variant
    assert cer("\n".join(samples.HEBREW), r.text) <= 0.05, r.text


def test_fast_models(pipeline, render):
    r = ocr(pipeline, render(samples.MIXED, px=16), model="fast")
    assert "Microsoft" in r.text and "שלישי" in r.text


@pytest.mark.parametrize("lines,expected", [
    (samples.ENGLISH, "eng"), (samples.HEBREW, "heb"), (samples.MIXED, "heb+eng")])
def test_auto_language_selection(pipeline, render, lines, expected):
    r = ocr(pipeline, render(lines, px=16), language="auto")
    assert r.language == expected, (r.language, r.notes)
    assert cer("\n".join(lines), r.text) <= 0.04


def test_blank_image_returns_empty_result(pipeline):
    r = ocr(pipeline, np.full((80, 300, 3), 250, np.uint8))
    assert r.empty and r.notes


def test_nearly_blank_noise_is_not_invented(pipeline):
    rng = np.random.default_rng(1)
    img = np.clip(np.full((80, 300, 3), 200.0) + rng.normal(0, 2, (80, 300, 3)), 0, 255).astype(np.uint8)
    assert ocr(pipeline, img).empty


@pytest.mark.parametrize("bad", [np.zeros((2, 2, 3), np.uint8), np.zeros((50, 50), np.float32),
                                 np.zeros((50, 50, 5), np.uint8), "not an image"])
def test_invalid_input(pipeline, bad):
    with pytest.raises(OcrError):
        pipeline.recognize(bad, OcrOptions())


def test_missing_language_is_reported_not_silently_dropped(tmp_path, monkeypatch, render):
    from textsnap.storage.paths import bundled_tesseract_dir
    only_eng = tmp_path / "tessdata" / "best"
    only_eng.mkdir(parents=True)
    shutil.copy(bundled_tesseract_dir() / "tessdata" / "best" / "eng.traineddata", only_eng)
    eng = TesseractEngine(bundled_tesseract_dir())
    monkeypatch.setattr(eng, "tessdata", lambda model: only_eng)
    pipe = OcrPipeline(eng)
    with pytest.raises(MissingLanguageError) as info:
        pipe.recognize(render(samples.HEBREW), OcrOptions(language="heb+eng"))
    assert info.value.missing == ["heb"] and "Hebrew" in str(info.value)
    # English-only still works with the same engine
    assert "quick" in pipe.recognize(render(samples.ENGLISH), OcrOptions(language="eng")).text
    pipe.shutdown()


def test_engine_not_found(tmp_path):
    eng = TesseractEngine(tmp_path)
    assert not eng.status().ok
    with pytest.raises(EngineUnavailableError):
        OcrPipeline(eng).recognize(np.zeros((40, 40, 3), np.uint8) + 255, OcrOptions())


def test_timeout_kills_engine(engine, render):
    big = np.tile(render(samples.ENGLISH, px=14), (12, 3, 1))
    with pytest.raises(OcrTimeoutError):
        engine.recognize(big, ["heb", "eng"], 6, "best", timeout_s=0.05)


def test_cancel(engine, render):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(OcrCancelled):
        engine.recognize(render(samples.ENGLISH), ["eng"], 6, cancel=cancel)


def test_failure_does_not_poison_later_runs(pipeline, render):
    with pytest.raises(OcrError):
        pipeline.recognize(np.zeros((1, 1, 3), np.uint8), OcrOptions())
    assert "quick" in pipeline.recognize(render(samples.ENGLISH), OcrOptions()).text


def test_ocr_text_never_logged(pipeline, render, caplog):
    caplog.set_level("DEBUG")
    r = pipeline.recognize(render(["Confidential password Zebra42"], px=16), OcrOptions())
    assert "Zebra42" in r.text
    assert "Zebra42" not in caplog.text and "Confidential" not in caplog.text


def test_cancel_during_secondary_pass_is_not_a_success(engine, render):
    """A cancel arriving after the first pass must surface as OcrCancelled, never as a result."""
    pipe = OcrPipeline(engine)
    cancel = threading.Event()
    real = engine.recognize
    calls = []

    def recognize(*a, **kw):
        calls.append(1)
        out = real(*a, **kw)
        cancel.set()  # the user cancels while the next pass is about to run
        return out

    engine.recognize = recognize
    try:
        with pytest.raises(OcrCancelled):
            pipe.recognize(render(["הפגישה עם Microsoft תתקיים ביום שלישי"], px=15), OcrOptions(), cancel)
    finally:
        engine.recognize = real
        pipe.shutdown()
    assert calls
