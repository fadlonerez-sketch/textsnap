"""Diagnostics logging.

Logs contain events, timings, sizes and error types only. Recognised text,
clipboard contents, key presses, file contents and images are never logged;
modules log lengths and counts instead.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_handler: logging.Handler | None = None


def setup(level: str, log_dir: Path, console: bool = False) -> Path:
    global _handler
    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "textsnap.log"
    if _handler is not None:
        root.removeHandler(_handler)
        _handler.close()
    _handler = logging.handlers.RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
    _handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(_handler)
    if console and sys.stderr is not None and not any(isinstance(h, logging.StreamHandler)
                                                      and not isinstance(h, logging.FileHandler)
                                                      for h in root.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(stream)
    return path


def set_level(level: str) -> None:
    logging.getLogger().setLevel(getattr(logging, level, logging.INFO))


def shutdown() -> None:
    global _handler
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler.close()
        _handler = None
