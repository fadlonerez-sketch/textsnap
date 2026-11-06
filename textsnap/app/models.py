"""Plain data passed between the controller and the UI."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from textsnap.capture.geometry import Rect
from textsnap.ocr.pipeline import OcrResult

SOURCE_LABELS = {
    "region": "Screen region", "window": "Window", "monitor": "Screen", "desktop": "All screens",
    "repeat": "Repeated region", "active": "Active window", "clipboard": "Clipboard image", "file": "Image file", "pdf": "PDF document",
}


@dataclass
class CaptureResult:
    id: int
    source: str
    result: OcrResult | None = None
    error: str = ""
    qr: list[str] = field(default_factory=list)
    copied: bool = False
    copy_error: str = ""
    rect: Rect | None = None
    file_name: str = ""
    can_rerun: bool = True
    created: float = field(default_factory=time.time)

    @property
    def text(self) -> str:
        return self.result.text if self.result else ""

    @property
    def source_label(self) -> str:
        label = SOURCE_LABELS.get(self.source, self.source)
        return f"{label}: {self.file_name}" if self.file_name else label
