"""Local QR-code detection (zxing-cpp). Detected values are only displayed;
nothing is opened automatically."""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


def decode_qr(rgb: np.ndarray) -> list[str]:
    try:
        import zxingcpp
    except ImportError:
        log.warning("QR detection unavailable: zxing-cpp is not installed")
        return []
    try:
        formats = (zxingcpp.BarcodeFormat.QRCode, zxingcpp.BarcodeFormat.MicroQRCode)
        results = zxingcpp.read_barcodes(np.ascontiguousarray(rgb), formats=formats)
    except Exception as exc:  # malformed input must never break OCR
        log.info("QR detection failed: %s", type(exc).__name__)
        return []
    values: list[str] = []
    for r in results:
        if r.valid and r.text and r.text not in values:
            values.append(r.text)
    return values
