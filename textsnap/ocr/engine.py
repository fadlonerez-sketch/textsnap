"""Tesseract OCR engine wrapper.

Tesseract runs as a child process (no shell) for every recognition: crashes
or hangs are isolated from the UI and a timeout can kill it. The image is
streamed through stdin as PGM and the result comes back as TSV on stdout,
so neither the pixels nor the text ever touch the disk.

Two model sets are bundled: ``best`` (tessdata_best, most accurate, the
default) and ``fast`` (tessdata_fast).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
LANGUAGE_NAMES = {"heb": "Hebrew", "eng": "English"}
MODELS = ("best", "fast")


class OcrError(Exception):
    """Base class for recognition failures that should be shown to the user."""


class EngineUnavailableError(OcrError):
    pass


class MissingLanguageError(OcrError):
    def __init__(self, missing: list[str], model: str, folder: Path):
        names = ", ".join(f"{LANGUAGE_NAMES.get(m, m)} ({m}.traineddata)" for m in missing)
        super().__init__(f"Language data not found: {names} in {folder}. "
                         "Reinstall TextSnap or point Settings > Languages to a Tesseract "
                         "folder that contains these files.")
        self.missing = missing
        self.model = model


class OcrTimeoutError(OcrError):
    pass


class OcrCancelled(OcrError):
    pass


@dataclass
class Word:
    text: str
    conf: float
    left: int
    top: int
    width: int
    height: int
    block: int
    par: int
    line: int
    num: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass
class RawOcr:
    words: list[Word]
    duration_ms: float
    languages: str
    psm: int

    @property
    def mean_conf(self) -> float | None:
        scored = [(w.conf, len(w.text)) for w in self.words if w.conf >= 0 and w.text.strip()]
        total = sum(n for _c, n in scored)
        return sum(c * n for c, n in scored) / total if total else None

    @property
    def char_count(self) -> int:
        return sum(len(w.text.strip()) for w in self.words)


@dataclass
class EngineStatus:
    ok: bool
    folder: Path
    version: str = ""
    languages: dict[str, list[str]] = field(default_factory=dict)  # model -> languages
    error: str = ""

    def has(self, langs: list[str], model: str) -> bool:
        return all(lang in self.languages.get(model, []) for lang in langs)

    def summary(self) -> str:
        if not self.ok:
            return self.error or "OCR engine unavailable"
        langs = sorted(set(self.languages.get("best", [])) | set(self.languages.get("fast", [])))
        names = ", ".join(LANGUAGE_NAMES.get(lang, lang) for lang in langs)
        return f"Tesseract {self.version} - {names or 'no languages'}"


def encode_pnm(image: np.ndarray) -> bytes:
    """Encode a uint8 grayscale (PGM) or RGB (PPM) array in binary PNM form."""
    if image.dtype != np.uint8:
        raise ValueError("image must be uint8")
    if image.ndim == 2:
        h, w = image.shape
        return b"P5\n%d %d\n255\n" % (w, h) + np.ascontiguousarray(image).tobytes()
    if image.ndim == 3 and image.shape[2] == 3:
        h, w, _ = image.shape
        return b"P6\n%d %d\n255\n" % (w, h) + np.ascontiguousarray(image).tobytes()
    raise ValueError("unsupported image shape")


def parse_tsv(tsv: str) -> list[Word]:
    words: list[Word] = []
    for line in tsv.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        text = "\t".join(parts[11:])
        if not text.strip():
            continue
        try:
            words.append(Word(text=text, conf=float(parts[10]), left=int(parts[6]), top=int(parts[7]),
                              width=int(parts[8]), height=int(parts[9]), block=int(parts[2]),
                              par=int(parts[3]), line=int(parts[4]), num=int(parts[5])))
        except ValueError:
            continue
    return words


class TesseractEngine:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._status: EngineStatus | None = None
        self._lock = threading.Lock()

    @property
    def exe(self) -> Path:
        return self.folder / "tesseract.exe"

    def tessdata(self, model: str) -> Path:
        nested = self.folder / "tessdata" / model
        return nested if nested.is_dir() else self.folder / "tessdata"

    def status(self, refresh: bool = False) -> EngineStatus:
        with self._lock:
            if self._status is None or refresh:
                self._status = self._probe()
            return self._status

    def _probe(self) -> EngineStatus:
        if not self.exe.is_file():
            return EngineStatus(False, self.folder, error=f"tesseract.exe not found in {self.folder}")
        try:
            out = subprocess.run([str(self.exe), "--version"], capture_output=True, timeout=15,
                                 creationflags=CREATE_NO_WINDOW, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return EngineStatus(False, self.folder, error=f"Tesseract could not be started: {exc}")
        text = (out.stdout + out.stderr).decode("utf-8", "replace")
        m = re.search(r"tesseract v?(\d+\.\d+\.\d+)", text)
        if out.returncode != 0 or not m:
            return EngineStatus(False, self.folder, error="Tesseract did not report a version "
                                f"(exit code {out.returncode})")
        languages = {}
        for model in MODELS:
            folder = self.tessdata(model)
            languages[model] = sorted(p.stem for p in folder.glob("*.traineddata")
                                      if p.stat().st_size > 1024) if folder.is_dir() else []
        if not any(languages.values()):
            return EngineStatus(False, self.folder, m.group(1), languages,
                                error=f"no language data found under {self.folder / 'tessdata'}")
        return EngineStatus(True, self.folder, m.group(1), languages)

    def ensure(self, langs: list[str], model: str) -> None:
        status = self.status()
        if not status.ok:
            raise EngineUnavailableError(status.error)
        missing = [lang for lang in langs if lang not in status.languages.get(model, [])]
        if missing:
            raise MissingLanguageError(missing, model, self.tessdata(model))

    def recognize(
        self,
        image: np.ndarray,
        langs: list[str],
        psm: int = 6,
        model: str = "best",
        timeout_s: float = 20.0,
        dpi: int = 300,
        cancel: threading.Event | None = None,
    ) -> RawOcr:
        """Run one recognition pass. ``image`` is uint8 grayscale or RGB."""
        self.ensure(langs, model)
        if image.size == 0 or min(image.shape[:2]) < 3:
            raise OcrError("the image is too small to recognise")
        if cancel is not None and cancel.is_set():
            raise OcrCancelled("cancelled")
        cmd = [str(self.exe), "stdin", "stdout", "-l", "+".join(langs), "--psm", str(psm),
               "--dpi", str(dpi), "--tessdata-dir", str(self.tessdata(model)),
               "-c", "tessedit_create_tsv=1"]  # no config file needed in the tessdata folder
        env = dict(os.environ, OMP_THREAD_LIMIT="1")
        started = time.perf_counter()
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=CREATE_NO_WINDOW, env=env, cwd=str(self.folder))
        except OSError as exc:
            raise EngineUnavailableError(f"Tesseract could not be started: {exc}") from exc
        payload = encode_pnm(image)
        try:
            out, err = self._communicate(proc, payload, timeout_s, cancel)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(5)
        elapsed = (time.perf_counter() - started) * 1000
        if proc.returncode != 0:
            detail = err.decode("utf-8", "replace").strip().splitlines()
            raise OcrError(f"Tesseract failed (exit code {proc.returncode})"
                           + (f": {detail[-1][:200]}" if detail else ""))
        tsv = out.decode("utf-8", "replace")
        if not tsv.startswith("level\t"):
            raise OcrError("Tesseract returned no recognition data")
        return RawOcr(parse_tsv(tsv), elapsed, "+".join(langs), psm)

    @staticmethod
    def _communicate(proc: subprocess.Popen, payload: bytes, timeout_s: float,
                     cancel: threading.Event | None) -> tuple[bytes, bytes]:
        deadline = time.monotonic() + timeout_s
        result: dict[str, tuple[bytes, bytes]] = {}

        def run() -> None:
            try:
                result["io"] = proc.communicate(payload)
            except (OSError, ValueError):
                result["io"] = (b"", b"")

        t = threading.Thread(target=run, daemon=True)
        t.start()
        while t.is_alive():
            t.join(0.05)
            if cancel is not None and cancel.is_set():
                proc.kill()
                t.join(2)
                raise OcrCancelled("cancelled")
            if time.monotonic() > deadline:
                proc.kill()
                t.join(2)
                raise OcrTimeoutError(f"OCR took longer than {timeout_s:.0f} s and was stopped")
        return result.get("io", (b"", b""))
