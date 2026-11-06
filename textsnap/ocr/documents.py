"""Loading user-selected images and PDFs. Files are opened read-only and
never modified; pixels stay in memory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_IMAGE_PIXELS = 80_000_000
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp")
PDF_RENDER_DPI = 300


class DocumentError(Exception):
    pass


def _check_size(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise DocumentError(f"cannot read the file: {exc.strerror or exc}") from exc
    if size > MAX_FILE_BYTES:
        raise DocumentError(f"the file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")


def load_image(path: str | os.PathLike[str], frame: int = 0) -> np.ndarray:
    """Load one frame of an image file as RGB uint8."""
    p = Path(path)
    _check_size(p)
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(p) as img:
            if frame:
                img.seek(frame)
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                background = Image.new("RGBA", img.size, (255, 255, 255, 255))
                img = Image.alpha_composite(background, img)
            return np.asarray(img.convert("RGB")).copy()
    except Image.DecompressionBombError as exc:
        raise DocumentError("the image is too large to process safely") from exc
    except (OSError, ValueError, EOFError) as exc:
        raise DocumentError(f"the file is not a readable image ({type(exc).__name__})") from exc


def image_frame_count(path: str | os.PathLike[str]) -> int:
    try:
        with Image.open(path) as img:
            return int(getattr(img, "n_frames", 1))
    except (OSError, ValueError):
        return 1


@dataclass
class PdfInfo:
    pages: int


def parse_page_range(spec: str, page_count: int) -> list[int]:
    """'1-3, 5' -> [0, 1, 2, 4] (zero-based). Empty means all pages."""
    spec = spec.strip()
    if not spec:
        return list(range(page_count))
    pages: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            start = int(a) if a else 1
            end = int(b) if b else page_count
        else:
            start = end = int(part)
        if start < 1 or end > page_count or start > end:
            raise ValueError(f"page range '{part}' is outside 1-{page_count}")
        pages.extend(p - 1 for p in range(start, end + 1) if p - 1 not in pages)
    if not pages:
        raise ValueError("no pages selected")
    return pages


class PdfDocument:
    def __init__(self, path: str | os.PathLike[str]):
        p = Path(path)
        _check_size(p)
        try:
            import pypdfium2 as pdfium
            self._doc = pdfium.PdfDocument(str(p))
        except Exception as exc:
            raise DocumentError(f"the PDF could not be opened ({type(exc).__name__}); "
                                "it may be damaged or password protected") from exc

    def __len__(self) -> int:
        return len(self._doc)

    def embedded_text(self, index: int) -> str:
        page = self._doc[index]
        try:
            textpage = page.get_textpage()
            try:
                return textpage.get_text_bounded() or ""
            finally:
                textpage.close()
        finally:
            page.close()

    def render(self, index: int, dpi: int = PDF_RENDER_DPI) -> np.ndarray:
        page = self._doc[index]
        try:
            w, h = page.get_size()
            scale = dpi / 72.0
            if w * h * scale * scale > MAX_IMAGE_PIXELS:
                scale = (MAX_IMAGE_PIXELS / (w * h)) ** 0.5
            bitmap = page.render(scale=scale)
            try:
                return np.asarray(bitmap.to_pil().convert("RGB")).copy()
            finally:
                bitmap.close()
        finally:
            page.close()

    def close(self) -> None:
        self._doc.close()
