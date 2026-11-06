"""Image preparation for screen-text OCR.

Screen captures differ from scans: text is small (9-16 px), anti-aliased,
often light-on-dark or colored, and selections tend to clip UI borders.
The default ("auto") path converts to grayscale, makes text dark on a light
background, strips selection-edge lines and empty margins, rescales so text
lines are roughly 24 px tall (Tesseract's comfort zone), stretches contrast
and pads the image. Grayscale is kept (no forced thresholding) because
Tesseract's LSTM models read anti-aliased glyphs better than a hard binary
image; binarisation and deskewing are extra variants in thorough mode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

TARGET_LINE_PX = 24.0
PAD_PX = 12


@dataclass
class Prepared:
    image: np.ndarray  # uint8 grayscale, dark text on light background
    name: str
    scale: float = 1.0
    inverted: bool = False
    line_height: float | None = None
    line_count: int = 0
    notes: list[str] = field(default_factory=list)


def to_gray(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim == 2:
        return rgb.astype(np.uint8, copy=False)
    f = rgb[..., :3].astype(np.float32)
    gray = f[..., 0] * 0.299 + f[..., 1] * 0.587 + f[..., 2] * 0.114
    return np.clip(gray + 0.5, 0, 255).astype(np.uint8)


def otsu_threshold(gray: np.ndarray) -> int:
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 128
    levels = np.arange(256, dtype=np.float64)
    w0 = np.cumsum(hist)
    w1 = total - w0
    m0 = np.cumsum(hist * levels)
    mt = m0[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mt * w0 / total - m0) ** 2 / (w0 * w1 / total)
    between[~np.isfinite(between)] = 0
    return int(np.argmax(between))


def contrast_pixels(gray: np.ndarray, delta: int = 40) -> int:
    median = int(np.median(gray))
    return int(np.count_nonzero(np.abs(gray.astype(np.int16) - median) > delta))


def is_blank(gray: np.ndarray) -> bool:
    """True when the area has (almost) nothing that could be text."""
    if gray.size == 0:
        return True
    return contrast_pixels(gray) < max(12, gray.size // 20000)


def background_is_dark(gray: np.ndarray) -> bool:
    """Text is the minority class, so the majority side of Otsu is background."""
    t = otsu_threshold(gray)
    return float(np.mean(gray <= t)) > 0.5


def ink_mask(gray: np.ndarray) -> np.ndarray:
    """Dark-on-light image -> boolean mask of ink pixels."""
    return gray <= otsu_threshold(gray)


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    padded = np.concatenate(([False], flags, [False]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    return [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2])]


def text_line_runs(gray: np.ndarray) -> list[tuple[int, int]]:
    ink = ink_mask(gray)
    min_ink = max(1, int(gray.shape[1] * 0.002))
    rows = ink.sum(axis=1) >= min_ink
    return [r for r in _runs(rows) if r[1] - r[0] >= 3]


def estimate_line_height(gray: np.ndarray) -> tuple[float | None, int]:
    runs = text_line_runs(gray)
    if not runs:
        return None, 0
    heights = sorted(b - a for a, b in runs)
    return float(heights[len(heights) // 2]), len(runs)


def choose_scale(line_height: float | None, target: float = TARGET_LINE_PX) -> float:
    if not line_height:
        return 1.0
    if line_height > 150:
        return max(0.25, 75.0 / line_height)
    s = target / line_height
    if s < 1.3:
        return 1.0
    return min(4.0, round(s * 2) / 2)


def remove_edge_lines(gray: np.ndarray) -> np.ndarray:
    """Drop thin, solid lines hugging the selection edges (window borders, rules)."""
    g = gray
    for _ in range(3):
        if g.shape[0] < 8 or g.shape[1] < 8:
            break
        t = otsu_threshold(g)
        ink = g <= t
        changed = False
        for side in ("top", "bottom", "left", "right"):
            line = {"top": ink[0], "bottom": ink[-1], "left": ink[:, 0], "right": ink[:, -1]}[side]
            if line.mean() > 0.7:
                g = {"top": g[1:], "bottom": g[:-1], "left": g[:, 1:], "right": g[:, :-1]}[side]
                ink = {"top": ink[1:], "bottom": ink[:-1], "left": ink[:, 1:], "right": ink[:, :-1]}[side]
                changed = True
        if not changed:
            break
    return g


def trim_margins(gray: np.ndarray, margin: int = 4) -> np.ndarray:
    """Crop empty background margins (keeps a small margin)."""
    bg = int(np.median(gray))
    mask = np.abs(gray.astype(np.int16) - bg) > 30
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return gray
    y0, y1 = max(0, rows[0] - margin), min(gray.shape[0], rows[-1] + 1 + margin)
    x0, x1 = max(0, cols[0] - margin), min(gray.shape[1], cols[-1] + 1 + margin)
    return gray[y0:y1, x0:x1]


def resize(gray: np.ndarray, scale: float) -> np.ndarray:
    if abs(scale - 1.0) < 1e-3:
        return gray
    h, w = gray.shape
    size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    method = Image.Resampling.BICUBIC if scale > 1 else Image.Resampling.LANCZOS
    return np.asarray(Image.fromarray(gray).resize(size, method))


def stretch_contrast(gray: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(gray, [0.5, 99.5])
    if hi - lo < 40:
        return gray
    out = (gray.astype(np.float32) - lo) * (255.0 / (hi - lo))
    return np.clip(out, 0, 255).astype(np.uint8)


def pad(gray: np.ndarray, px: int = PAD_PX, value: int = 255) -> np.ndarray:
    return np.pad(gray, px, mode="constant", constant_values=value)


def sauvola(gray: np.ndarray, window: int = 31, k: float = 0.2) -> np.ndarray:
    """Local adaptive thresholding (helps with uneven backgrounds and colors)."""
    g = gray.astype(np.float64)
    r = window // 2
    p = np.pad(g, r + 1, mode="edge")
    s1 = p.cumsum(0).cumsum(1)
    s2 = (p * p).cumsum(0).cumsum(1)
    h, w = g.shape
    y0, x0, y1, x1 = 0, 0, window, window

    def box(s: np.ndarray) -> np.ndarray:
        return s[y1:y1 + h, x1:x1 + w] - s[y0:y0 + h, x1:x1 + w] - s[y1:y1 + h, x0:x0 + w] + s[y0:y0 + h, x0:x0 + w]

    n = float(window * window)
    mean = box(s1) / n
    var = np.maximum(box(s2) / n - mean * mean, 0)
    thr = mean * (1 + k * (np.sqrt(var) / 128.0 - 1))
    return np.where(g > thr, 255, 0).astype(np.uint8)


def deskew_angle(gray: np.ndarray, max_deg: float = 6.0) -> float:
    """Estimate text skew from the sharpness of the horizontal projection.

    Returns the skew in degrees; ``rotate(gray, -angle)`` straightens it.
    """
    ys, xs = np.nonzero(ink_mask(gray))
    if ys.size < 200:
        return 0.0
    if ys.size > 40000:
        idx = np.random.default_rng(0).choice(ys.size, 40000, replace=False)
        ys, xs = ys[idx], xs[idx]
    ys = ys.astype(np.float64)
    xs = xs.astype(np.float64)

    def score(deg: float) -> float:
        a = math.radians(deg)
        proj = ys * math.cos(a) - xs * math.sin(a)
        hist = np.bincount((proj - proj.min()).astype(np.int64))
        return float(np.sum(hist.astype(np.float64) ** 2))

    coarse = np.arange(-max_deg, max_deg + 0.01, 0.5)
    best = max(coarse, key=score)
    fine = np.arange(best - 0.5, best + 0.51, 0.1)
    best = max(fine, key=score)
    return float(best) if abs(best) >= 0.4 else 0.0


def rotate(gray: np.ndarray, degrees: float) -> np.ndarray:
    img = Image.fromarray(gray).rotate(-degrees, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)
    return np.asarray(img)


def best_channel(rgb: np.ndarray) -> np.ndarray | None:
    """The single color channel with the strongest text/background separation.

    Colored text can vanish in a luminance conversion (e.g. red on green);
    one of the raw channels usually separates it better.
    """
    if rgb.ndim != 3:
        return None
    candidates = [to_gray(rgb)] + [rgb[..., i].copy() for i in range(3)]

    def separation(g: np.ndarray) -> float:
        t = otsu_threshold(g)
        lo, hi = g[g <= t], g[g > t]
        return float(hi.mean() - lo.mean()) if lo.size and hi.size else 0.0

    scores = [separation(c) for c in candidates]
    best = int(np.argmax(scores))
    return candidates[best] if best != 0 and scores[best] > scores[0] * 1.15 else None


def _normalise(gray: np.ndarray, strength: str, notes: list[str]) -> tuple[np.ndarray, bool]:
    inverted = False
    if strength != "off" and background_is_dark(gray):
        gray = 255 - gray
        inverted = True
        notes.append("inverted light-on-dark text")
    if strength == "auto":
        gray = remove_edge_lines(gray)
        gray = trim_margins(gray)
    return gray, inverted


def prepare(rgb: np.ndarray, strength: str = "auto", scale: float | None = None,
            name: str = "standard", gray: np.ndarray | None = None) -> Prepared:
    """Main preparation path. ``strength`` is ``auto``, ``light`` or ``off``."""
    notes: list[str] = []
    g = to_gray(rgb) if gray is None else gray
    g, inverted = _normalise(g, strength, notes)
    line_h, lines = estimate_line_height(g)
    if scale is None:
        if strength == "off":
            scale = 1.0
        elif strength == "light":
            scale = choose_scale(line_h, target=24.0) if line_h and line_h < 16 else 1.0
        else:
            scale = choose_scale(line_h)
    g = resize(g, scale)
    if strength == "auto":
        g = stretch_contrast(g)
    g = pad(g)
    return Prepared(g, name, scale, inverted, line_h, lines, notes)


def thorough_variants(rgb: np.ndarray, strength: str = "auto") -> list[Prepared]:
    """Alternative preparations for difficult captures (best result wins)."""
    base = prepare(rgb, strength, name="standard")
    variants = [base]
    alt = 1.0 if base.scale >= 2 else 2.0 if base.scale < 1.5 else 3.0
    variants.append(prepare(rgb, strength, scale=alt * (base.scale if base.scale < 1 else 1),
                            name=f"scale {alt:g}x"))
    variants.append(Prepared(pad(sauvola(base.image[PAD_PX:-PAD_PX, PAD_PX:-PAD_PX])), "adaptive threshold",
                             base.scale, base.inverted, base.line_height, base.line_count))
    channel = best_channel(rgb)
    if channel is not None:
        variants.append(prepare(rgb, strength, scale=base.scale, name="color channel", gray=channel))
    angle = deskew_angle(base.image)
    if angle:
        variants.append(Prepared(rotate(base.image, -angle), f"deskewed {angle:.1f} deg",
                                 base.scale, base.inverted, base.line_height, base.line_count))
    return variants
