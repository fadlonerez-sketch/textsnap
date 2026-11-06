"""Screen geometry in physical pixels and Qt logical coordinates.

Conventions
-----------
* ``Rect`` is integer, half-open: it covers x..x+w-1 and y..y+h-1.
* Physical coordinates are Windows virtual-desktop pixels as seen by a
  per-monitor-DPI-aware process. They can be negative (monitors left of or
  above the primary monitor).
* Each overlay window covers exactly one monitor; positions inside it are
  Qt logical pixels relative to the window, so the conversion is
  ``physical = monitor_origin + round(local * device_pixel_ratio)``. This
  holds for any per-monitor scale factor and never mixes the DPIs of two
  monitors in one computation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def empty(self) -> bool:
        return self.w <= 0 or self.h <= 0

    @property
    def area(self) -> int:
        return 0 if self.empty else self.w * self.h

    @classmethod
    def from_edges(cls, left: int, top: int, right: int, bottom: int) -> "Rect":
        return cls(left, top, max(0, right - left), max(0, bottom - top))

    @classmethod
    def from_points(cls, x1: int, y1: int, x2: int, y2: int) -> "Rect":
        """Rectangle spanned by two drag points, whatever the drag direction."""
        return cls.from_edges(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def intersected(self, other: "Rect") -> "Rect":
        return Rect.from_edges(max(self.x, other.x), max(self.y, other.y),
                               min(self.right, other.right), min(self.bottom, other.bottom))

    def united(self, other: "Rect") -> "Rect":
        if self.empty:
            return other
        if other.empty:
            return self
        return Rect.from_edges(min(self.x, other.x), min(self.y, other.y),
                               max(self.right, other.right), max(self.bottom, other.bottom))

    def translated(self, dx: int, dy: int) -> "Rect":
        return Rect(self.x + dx, self.y + dy, self.w, self.h)

    def iou(self, other: "Rect") -> float:
        inter = self.intersected(other).area
        union = self.area + other.area - inter
        return inter / union if union else 0.0

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]


@dataclass(frozen=True)
class Monitor:
    """One display: its physical rectangle and the matching Qt screen geometry."""

    index: int
    physical: Rect
    logical: Rect  # QScreen.geometry() (device-independent pixels)
    dpr: float  # QScreen.devicePixelRatio()
    primary: bool = False
    name: str = ""
    handle: int = 0  # HMONITOR

    @property
    def scale_percent(self) -> int:
        return int(round(self.dpr * 100))

    def local_to_physical(self, lx: float, ly: float) -> tuple[int, int]:
        """Overlay-window local logical position -> physical desktop pixel."""
        px = self.physical.x + int(math.floor(lx * self.dpr + 0.5))
        py = self.physical.y + int(math.floor(ly * self.dpr + 0.5))
        return clamp_point(px, py, self.physical)

    def physical_to_local(self, px: int, py: int) -> tuple[float, float]:
        return (px - self.physical.x) / self.dpr, (py - self.physical.y) / self.dpr

    def local_rect_to_physical(self, x1: float, y1: float, x2: float, y2: float) -> Rect:
        ax, ay = self.local_to_physical(x1, y1)
        bx, by = self.local_to_physical(x2, y2)
        return Rect.from_points(ax, ay, bx, by).intersected(self.physical)

    def physical_rect_to_local(self, r: Rect) -> tuple[float, float, float, float]:
        x1, y1 = self.physical_to_local(r.x, r.y)
        x2, y2 = self.physical_to_local(r.right, r.bottom)
        return x1, y1, x2 - x1, y2 - y1


def clamp_point(px: int, py: int, bounds: Rect) -> tuple[int, int]:
    """Clamp to the closed range [x, right] so a drag can reach the far edge."""
    return min(max(px, bounds.x), bounds.right), min(max(py, bounds.y), bounds.bottom)


def virtual_bounds(monitors: list[Monitor]) -> Rect:
    bounds = Rect(0, 0, 0, 0)
    for m in monitors:
        bounds = bounds.united(m.physical)
    return bounds


def monitor_at(monitors: list[Monitor], px: int, py: int) -> Monitor | None:
    for m in monitors:
        if m.physical.contains(px, py):
            return m
    return None


def crop_offsets(selection: Rect, image_origin_x: int, image_origin_y: int) -> Rect:
    """Selection in physical desktop coordinates -> rectangle within a capture image."""
    return selection.translated(-image_origin_x, -image_origin_y)


def selection_ok(r: Rect, min_physical: int) -> bool:
    return not r.empty and r.w >= min_physical and r.h >= min_physical


def match_monitor(handle: int, qt_logical: Rect, qt_dpr: float, native: list[tuple[int, Rect]]) -> Rect | None:
    """Find a Qt screen's physical rectangle.

    ``native`` lists (HMONITOR, physical rect) from EnumDisplayMonitors.
    Match by HMONITOR first; otherwise fall back to geometry: Qt keeps a
    screen's top-left at its native position and scales only the size.
    """
    for h, rect in native:
        if handle and h == handle:
            return rect
    best, best_err = None, None
    for _h, rect in native:
        err = (abs(rect.x - qt_logical.x) + abs(rect.y - qt_logical.y)
               + abs(rect.w - qt_logical.w * qt_dpr) + abs(rect.h - qt_logical.h * qt_dpr))
        if best_err is None or err < best_err:
            best, best_err = rect, err
    if best is not None and best_err is not None and best_err <= 8:
        return best
    return None
