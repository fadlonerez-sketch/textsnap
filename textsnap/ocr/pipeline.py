"""OCR pipeline: validation, preparation, recognition strategy, post-processing.

Languages
---------
* ``heb+eng`` - combined Hebrew and English models (the default).
* ``heb`` / ``eng`` - a single model.
* ``auto`` - best effort, implemented as: recognise with heb+eng, count
  Hebrew and Latin letters in the result, and if only one script appears,
  re-run with that script's model alone and keep whichever result scores
  higher. It is labelled best-effort because it can only choose between
  these models; it does not identify arbitrary languages.

Mixed-script fix
----------------
With the combined model, short Hebrew words next to English ones (e.g.
"עם Microsoft") are sometimes read as Latin garbage ("oy"). When a Hebrew
line contains a short Latin token that is not a known short English word,
a Hebrew-only pass is run on the same image, the word boxes are aligned,
and a confident Hebrew reading replaces the token; the line is then
re-ordered from word positions. Nothing is invented: every replacement is
an actual reading of those pixels by the Hebrew model.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from textsnap.capture.geometry import Rect
from textsnap.ocr import preprocess as pp
from textsnap.ocr import text as tx
from textsnap.ocr.engine import OcrCancelled, OcrError, RawOcr, TesseractEngine, Word

log = logging.getLogger(__name__)

MAX_WORD_REREADS = 4
MAX_PIXELS = 40_000_000  # inputs larger than this are downscaled first
MAX_SIDE = 12_000
LAYOUT_PSM = {"block": 6, "line": 7, "sparse": 11, "columns": 3}

# Short words that are legitimately English inside Hebrew text.
SHORT_ENGLISH = frozenset("""
a i am an as at be by do go he hi if in is it me my no of oh ok on or so to up us we
all and any are ask big boy but can day did end few for get got had has her him his
how its let man may new nor not now off old one our out own put say see she the too
two use was way who why yes yet you
ai api app bug cd cv dj dm dvd hr id io it mb gb kb tb ml pc pm am pr qa sms tv ui ux uk usa usb vs www
""".split())


# "API-0" / "Smith-9": a Latin word followed by a hyphen and 1-2 stray characters,
# typically a Hebrew prefix letter ("ה-API", "ל-John") read by the Latin model.
PREFIX_LATIN = re.compile(r"^(?P<latin>[A-Za-z0-9][A-Za-z0-9.@/:+#&_']*)-(?P<junk>\S{1,2})$")
HEBREW_GARBAGE = re.compile(r"^(?P<prefix>[בהוכלמש]{1,3})-(?P<body>\S+)$")
HEBREW_PREFIX = re.compile(r"^(?P<prefix>[בהוכלמש]{1,3})-")


@dataclass
class OcrOptions:
    language: str = "heb+eng"
    quality: str = "fast"  # or "thorough"
    model: str = "best"
    layout: str = "auto"
    preprocess: str = "auto"
    timeout_s: float = 20.0
    strip_bidi: bool = True
    preserve_line_breaks: bool = True
    fix_mixed_script: bool = True


@dataclass
class OcrResult:
    text: str
    confidence: float | None
    language: str
    quality: str
    duration_ms: float
    word_count: int
    direction: str
    variant: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.text.strip()


def _langs(code: str) -> list[str]:
    return code.split("+")


def score(raw: RawOcr) -> float:
    """Length-weighted mean word confidence (-1 when nothing was read)."""
    conf = raw.mean_conf
    return -1.0 if conf is None else conf


class OcrPipeline:
    def __init__(self, engine: TesseractEngine, max_workers: int = 3):
        self.engine = engine
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ocr-pass")

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    def recognize(self, rgb: np.ndarray, options: OcrOptions,
                  cancel: threading.Event | None = None) -> OcrResult:
        started = time.perf_counter()
        rgb = self._validate(rgb)
        langs_code = "heb+eng" if options.language == "auto" else options.language
        self.engine.ensure(_langs(langs_code), options.model)
        if options.language == "auto":
            self.engine.ensure(["heb", "eng"], options.model)

        gray = pp.to_gray(rgb)
        if pp.is_blank(gray):
            return OcrResult("", None, options.language, options.quality,
                             (time.perf_counter() - started) * 1000, 0, "none",
                             notes=["The selected area looks blank."])

        if options.quality == "thorough":
            variants = pp.thorough_variants(rgb, options.preprocess)
        else:
            variants = [pp.prepare(rgb, options.preprocess)]

        best_raw, best_variant, used = self._best_of(variants, langs_code, options, cancel)

        notes = list(best_variant.notes)
        if options.language == "auto":
            best_raw, used = self._auto_refine(best_raw, best_variant, options, cancel, notes)

        words = best_raw.words
        if options.fix_mixed_script and "heb" in used and "eng" in used:
            words = self._fix_mixed_script(words, best_variant, options, cancel, notes)
        words = tx.reorder_mixed_lines(words)

        if cancel is not None and cancel.is_set():
            raise OcrCancelled("cancelled")
        text = tx.assemble(words, options.preserve_line_breaks, options.strip_bidi)
        result = OcrResult(
            text=text,
            confidence=RawOcr(words, 0, used, best_raw.psm).mean_conf,
            language=used,
            quality=options.quality,
            duration_ms=(time.perf_counter() - started) * 1000,
            word_count=len(words),
            direction=tx.text_direction(text),
            variant=best_variant.name,
            notes=notes,
        )
        log.info("OCR finished: %d chars, %d words, conf %s, %s, %s, %.0f ms",
                 len(text), len(words), f"{result.confidence:.0f}" if result.confidence is not None else "-",
                 used, best_variant.name, result.duration_ms)
        return result

    # ------------------------------------------------------------------
    def _validate(self, rgb: np.ndarray) -> np.ndarray:
        if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim not in (2, 3):
            raise OcrError("unsupported image data")
        if rgb.ndim == 3 and rgb.shape[2] not in (3, 4):
            raise OcrError("unsupported image channels")
        if rgb.ndim == 3 and rgb.shape[2] == 4:
            rgb = rgb[..., :3]
        h, w = rgb.shape[:2]
        if h < 3 or w < 3:
            raise OcrError("the selection is too small to contain text")
        if h * w > MAX_PIXELS or max(h, w) > MAX_SIDE:
            factor = min((MAX_PIXELS / (h * w)) ** 0.5, MAX_SIDE / max(h, w))
            gray = pp.resize(pp.to_gray(rgb), factor)
            log.info("Large image downscaled by %.2f before OCR", factor)
            return gray
        return rgb

    def _psm(self, prepared: pp.Prepared, layout: str) -> int:
        if layout in LAYOUT_PSM:
            return LAYOUT_PSM[layout]
        return 7 if prepared.line_count == 1 else 6

    def _run(self, prepared: pp.Prepared, langs: str, options: OcrOptions,
             cancel: threading.Event | None, psm: int | None = None) -> RawOcr:
        return self.engine.recognize(prepared.image, _langs(langs), psm or self._psm(prepared, options.layout),
                                     options.model, options.timeout_s, cancel=cancel)

    def _best_of(self, variants: list[pp.Prepared], langs: str, options: OcrOptions,
                 cancel: threading.Event | None) -> tuple[RawOcr, pp.Prepared, str]:
        if len(variants) == 1:
            return self._run(variants[0], langs, options, cancel), variants[0], langs
        futures = [self._pool.submit(self._run, v, langs, options, cancel) for v in variants]
        results: list[tuple[RawOcr, pp.Prepared]] = []
        errors: list[Exception] = []
        for fut, v in zip(futures, variants):
            try:
                results.append((fut.result(), v))
            except OcrCancelled:
                raise
            except OcrError as exc:
                errors.append(exc)
        if not results:
            raise errors[0] if errors else OcrError("recognition failed")
        most_chars = max(r.char_count for r, _ in results) or 1

        def total(item: tuple[RawOcr, pp.Prepared]) -> float:
            raw = item[0]
            coverage = min(1.0, raw.char_count / most_chars) ** 0.5
            return score(raw) * coverage

        raw, variant = max(results, key=total)
        return raw, variant, langs

    def _auto_refine(self, raw: RawOcr, variant: pp.Prepared, options: OcrOptions,
                     cancel: threading.Event | None, notes: list[str]) -> tuple[RawOcr, str]:
        text = " ".join(w.text for w in raw.words)
        heb, lat = tx.script_counts(text)
        single = "eng" if heb == 0 and lat > 0 else "heb" if lat == 0 and heb > 0 else None
        if single is None:
            notes.append("auto: both scripts found, kept Hebrew + English")
            return raw, "heb+eng"
        alt = self._run(variant, single, options, cancel)
        if score(alt) >= score(raw) and alt.char_count >= raw.char_count * 0.8:
            notes.append(f"auto: only {'Latin' if single == 'eng' else 'Hebrew'} script found, "
                         f"used the {single} model alone")
            return alt, single
        notes.append("auto: kept Hebrew + English (scored higher)")
        return raw, "heb+eng"

    # ------------------------------------------------------------------
    @staticmethod
    def _core(text: str) -> str:
        return "".join(c for c in tx.strip_bidi_controls(text) if c.isalpha())

    @classmethod
    def suspicious(cls, word: Word) -> bool:
        """A Latin token inside a Hebrew line that may be a misread Hebrew word."""
        text = tx.strip_bidi_controls(word.text)
        if PREFIX_LATIN.match(text):
            return True
        core = cls._core(text)
        if not core or not all(tx.is_latin_letter(c) for c in core):
            return False
        if len(core) <= 3 and core.lower() not in SHORT_ENGLISH:
            return True
        return word.conf < 80

    @classmethod
    def _resolve(cls, w: Word, h: Word) -> list[Word] | None:
        """Corrected word(s) for Latin token ``w`` given the Hebrew-only reading ``h``."""
        latin_text = tx.strip_bidi_controls(w.text)
        heb_text = tx.strip_bidi_controls(h.text)
        m = PREFIX_LATIN.match(latin_text)
        p = HEBREW_PREFIX.match(heb_text)
        if m and p:
            # "ה-API" read as "API-0": keep the Latin word, take the prefix from
            # the Hebrew reading.
            return cls._split_prefix(w, m.group("latin"), p.group("prefix"), h.conf)
        core = cls._core(heb_text)
        if len(core) < 2 or not all(tx.is_hebrew_char(c) for c in core):
            return None
        if any(c.isascii() and (c.isdigit() or c.isalpha()) for c in heb_text):
            return None  # Hebrew letters mixed with digits/Latin: the Hebrew model misread Latin text
        short_unknown = len(cls._core(latin_text)) <= 3 and cls._core(latin_text).lower() not in SHORT_ENGLISH
        if (short_unknown and h.conf >= 60) or (h.conf >= 80 and h.conf >= w.conf + 15):
            return [Word(h.text, h.conf, w.left, w.top, w.width, w.height, w.block, w.par, w.line, w.num)]
        return None

    @staticmethod
    def suspicious_hebrew(word: Word) -> bool:
        """A Hebrew-prefixed token whose body is Latin text misread as Hebrew ("ה-ו0א")."""
        m = HEBREW_GARBAGE.match(tx.strip_bidi_controls(word.text))
        if not m:
            return False
        body = m.group("body")
        return any(tx.is_hebrew_char(c) for c in body) and any(c.isascii() and (c.isdigit() or c in "/!()[]{}|\\")
                                                              for c in body)

    @staticmethod
    def _split_prefix(w: Word, latin_text: str, prefix: str, conf: float) -> list[Word]:
        """Hebrew prefix + Latin word as two words: the Latin part on the left of
        the box, the prefix on the right (where it sits in an RTL line)."""
        split = w.left + int(w.width * 0.85)
        latin = Word(latin_text, w.conf, w.left, w.top, split - w.left, w.height, w.block, w.par, w.line, w.num)
        pre = Word(prefix + "-", conf, split, w.top, w.right - split, w.height, w.block, w.par, w.line, w.num)
        return [latin, pre]

    @classmethod
    def _resolve_english(cls, w: Word, e: Word) -> list[Word] | None:
        """Hebrew garbage ``w`` re-read by the English model as ``e``."""
        p = HEBREW_GARBAGE.match(tx.strip_bidi_controls(w.text))
        m = PREFIX_LATIN.match(tx.strip_bidi_controls(e.text))
        if p and m and len(cls._core(m.group("latin"))) >= 2:
            return cls._split_prefix(w, m.group("latin"), p.group("prefix"), w.conf)
        return None

    def _fix_mixed_script(self, words: list[Word], variant: pp.Prepared, options: OcrOptions,
                          cancel: threading.Event | None, notes: list[str]) -> list[Word]:
        heb_targets: list[Word] = []
        eng_targets: list[Word] = []
        for line in tx.group_lines(words):
            heb, _ = tx.script_counts(" ".join(w.text for w in line.words))
            if heb >= 2:
                heb_targets.extend(w for w in line.words if self.suspicious(w))
                eng_targets.extend(w for w in line.words if self.suspicious_hebrew(w))
        if not heb_targets and not eng_targets:
            return words
        passes = {lang: self._pool.submit(self._run, variant, lang, options, cancel)
                  for lang, targets in (("heb", heb_targets), ("eng", eng_targets)) if targets}
        readings: dict[str, list[Word]] = {}
        for lang, fut in passes.items():
            try:
                readings[lang] = fut.result().words
            except OcrCancelled:
                raise
            except OcrError as exc:
                log.info("Mixed-script check (%s) skipped: %s", lang, exc)
        replaced: dict[int, list[Word]] = {}
        unresolved: list[tuple[str, Word]] = []
        for lang, targets, resolve in (("heb", heb_targets, self._resolve), ("eng", eng_targets, self._resolve_english)):
            for w in targets:
                other = self._aligned(w, readings.get(lang, []))
                fixed = resolve(w, other) if other is not None else None
                if fixed:
                    replaced[id(w)] = fixed
                else:
                    unresolved.append((lang, w))
        # Second chance: re-read the word's own crop (the other model may have
        # merged it with a neighbour, so the boxes did not line up).
        crops = {id(w): self._pool.submit(self._read_word, variant.image, w, lang, options, cancel)
                 for lang, w in unresolved[:MAX_WORD_REREADS]}
        for lang, w in unresolved[:MAX_WORD_REREADS]:
            try:
                other = crops[id(w)].result()
            except OcrCancelled:
                raise
            except OcrError:
                continue
            resolve = self._resolve if lang == "heb" else self._resolve_english
            fixed = resolve(w, other) if other is not None else None
            if fixed:
                replaced[id(w)] = fixed
        if not replaced:
            return words
        notes.append(f"mixed-script check corrected {len(replaced)} word(s)")
        return [part for w in words for part in replaced.get(id(w), [w])]

    def _read_word(self, image: np.ndarray, w: Word, lang: str, options: OcrOptions,
                   cancel: threading.Event | None) -> Word | None:
        """OCR one word's box on its own; the result is mapped back to ``w``'s box.

        psm 7 (single line) is used: psm 8 tends to pick up neighbour fragments.
        """
        m = max(2, w.height // 6)
        crop = image[max(0, w.top - m): w.bottom + m, max(0, w.left - m): w.right + m]
        if crop.size == 0:
            return None
        raw = self.engine.recognize(pp.pad(crop), [lang], 7, options.model, options.timeout_s, cancel=cancel)
        lettered = [x for x in raw.words if self._core(x.text)]
        if len(lettered) != 1:
            return None
        r = lettered[0]
        return Word(r.text, r.conf, w.left, w.top, w.width, w.height, w.block, w.par, w.line, w.num)

    @staticmethod
    def _aligned(w: Word, candidates: list[Word]) -> Word | None:
        box = Rect(w.left, w.top, w.width, w.height)
        best = max(candidates, key=lambda c: box.iou(Rect(c.left, c.top, c.width, c.height)), default=None)
        if best is None or box.iou(Rect(best.left, best.top, best.width, best.height)) < 0.4:
            return None
        return best
