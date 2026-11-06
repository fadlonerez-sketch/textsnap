"""Render assets/textsnap.ico (+ a 256 px PNG) from the vector logo in ui/theme.py.

Each size is drawn separately (crisp small icons) and stored as PNG inside
the ICO container, which Windows Vista and later support.
"""

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv[:1])
from textsnap.ui.theme import paint_logo  # noqa: E402

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def png_bytes(size: int) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    paint_logo(size).save(buf, "PNG")
    return bytes(buf.data())


def main() -> None:
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    images = [(s, png_bytes(s)) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    (out / "textsnap.ico").write_bytes(header + entries + blobs)
    (out / "textsnap.png").write_bytes(dict(images)[256])
    print("wrote", out / "textsnap.ico")


if __name__ == "__main__":
    main()
