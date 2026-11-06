"""QImage <-> numpy conversion (always copies; the result owns its memory)."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage


def qimage_to_rgb(image: QImage) -> np.ndarray:
    if image.isNull():
        raise ValueError("empty image")
    img = image.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=bpl * h).reshape(h, bpl)
    return buf[:, : w * 3].reshape(h, w, 3).copy()


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    if rgb.ndim == 2:
        rgb = np.repeat(rgb[..., None], 3, axis=2)
    rgb = np.ascontiguousarray(rgb[..., :3], dtype=np.uint8)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
