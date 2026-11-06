"""Desktop capture into memory with GDI.

The whole virtual desktop is copied once when a capture starts (a
"freeze frame"). The overlay shows this frozen image, so the crop is exactly
what the user saw, video frames hold still while selecting, and no second
capture is needed after the overlay closes. Nothing is written to disk.

The process is per-monitor DPI aware (Qt 6 default), so every coordinate
here is a physical pixel. Protected content (DRM video, some elevated or
exclusive full-screen surfaces) may appear black: that is Windows policy and
is not worked around.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtGui import QGuiApplication, QImage

from textsnap.capture.geometry import Monitor, Rect, match_monitor, virtual_bounds

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SRCCOPY, CAPTUREBLT = 0x00CC0020, 0x40000000
DIB_RGB_COLORS, BI_RGB = 0, 0
MONITORINFOF_PRIMARY = 1


class CaptureError(RuntimeError):
    pass


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD), ("szDevice", wt.WCHAR * 32)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
user32.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.c_void_p, MONITORENUMPROC, wt.LPARAM]
user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
                            ctypes.POINTER(BITMAPINFOHEADER), wt.UINT]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]


def _rect(r: wt.RECT) -> Rect:
    return Rect.from_edges(r.left, r.top, r.right, r.bottom)


def native_monitors() -> list[tuple[int, Rect, bool, str]]:
    """(HMONITOR, physical rect, primary, device name) for every display."""
    found: list[tuple[int, Rect, bool, str]] = []

    def callback(hmon, _hdc, _rc, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            found.append((int(hmon or 0), _rect(info.rcMonitor),
                          bool(info.dwFlags & MONITORINFOF_PRIMARY), info.szDevice))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
    return found


def current_monitors() -> list[Monitor]:
    """Pair every QScreen with its physical rectangle."""
    native = native_monitors()
    pairs = [(h, r) for h, r, _p, _n in native]
    monitors: list[Monitor] = []
    for index, screen in enumerate(QGuiApplication.screens()):
        g = screen.geometry()
        logical = Rect(g.x(), g.y(), g.width(), g.height())
        dpr = float(screen.devicePixelRatio())
        handle = 0
        try:
            handle = int(screen.nativeInterface().handle())
        except Exception:
            pass
        physical = match_monitor(handle, logical, dpr, pairs)
        if physical is None:
            log.warning("Could not match screen %d to a native monitor; estimating its geometry", index)
            physical = Rect(logical.x, logical.y, round(logical.w * dpr), round(logical.h * dpr))
        primary = any(r == physical and p for _h, r, p, _n in native)
        monitors.append(Monitor(index, physical, logical, dpr, primary, screen.name().strip(), handle))
    return monitors


def grab_physical(rect: Rect) -> QImage:
    """Copy a physical-pixel rectangle of the desktop into a QImage (RGB32)."""
    if rect.empty:
        raise CaptureError("empty capture rectangle")
    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise CaptureError("cannot access the screen (GetDC failed)")
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, rect.w, rect.h)
    try:
        if not mem_dc or not bitmap:
            raise CaptureError("not enough memory for the screen capture")
        old = gdi32.SelectObject(mem_dc, bitmap)
        ok = gdi32.BitBlt(mem_dc, 0, 0, rect.w, rect.h, screen_dc, rect.x, rect.y, SRCCOPY | CAPTUREBLT)
        gdi32.SelectObject(mem_dc, old)
        if not ok:
            err = ctypes.get_last_error()
            raise CaptureError(f"the screen could not be captured (error {err}); "
                               "a secure desktop such as a UAC prompt may be active")
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth, header.biHeight = rect.w, -rect.h  # negative: top-down rows
        header.biPlanes, header.biBitCount, header.biCompression = 1, 32, BI_RGB
        buffer = ctypes.create_string_buffer(rect.w * rect.h * 4)
        lines = gdi32.GetDIBits(mem_dc, bitmap, 0, rect.h, buffer, ctypes.byref(header), DIB_RGB_COLORS)
        if lines != rect.h:
            raise CaptureError("reading the captured pixels failed")
        # BGRA bytes in memory == QImage.Format_RGB32 on little-endian; alpha is ignored.
        image = QImage(memoryview(buffer), rect.w, rect.h, rect.w * 4, QImage.Format.Format_RGB32).copy()
        del buffer
        return image
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)


@dataclass
class DesktopSnapshot:
    """A frozen copy of the virtual desktop, held in memory for one capture."""

    monitors: list[Monitor]
    bounds: Rect
    image: QImage
    windows: list = field(default_factory=list)  # list[WindowInfo] for window mode
    taken_at: float = field(default_factory=time.monotonic)

    def crop(self, r: Rect) -> QImage:
        clipped = r.intersected(self.bounds)
        if clipped.empty:
            raise CaptureError("the selection is outside the screen")
        return self.image.copy(clipped.x - self.bounds.x, clipped.y - self.bounds.y, clipped.w, clipped.h)

    def monitor_image(self, m: Monitor) -> QImage:
        return self.crop(m.physical)

    def release(self) -> None:
        self.image = QImage()
        self.windows = []


def take_snapshot(
    monitors: list[Monitor] | None = None,
    grabber: Callable[[Rect], QImage] = grab_physical,
    with_windows: bool = True,
) -> DesktopSnapshot:
    monitors = monitors if monitors is not None else current_monitors()
    if not monitors:
        raise CaptureError("no displays were found")
    bounds = virtual_bounds(monitors)
    started = time.perf_counter()
    image = grabber(bounds)
    windows = []
    if with_windows:
        try:
            from textsnap.capture.windows import visible_windows
            windows = visible_windows()
        except Exception:
            log.exception("Window enumeration failed; window mode will be unavailable")
    log.debug("Desktop snapshot %dx%d in %.0f ms", bounds.w, bounds.h, (time.perf_counter() - started) * 1000)
    return DesktopSnapshot(monitors, bounds, image, windows)
