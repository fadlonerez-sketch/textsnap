"""Selection geometry, multi-monitor layouts, negative coordinates and DPI."""

from __future__ import annotations

import pytest

from textsnap.capture.geometry import (
    Monitor, Rect, crop_offsets, match_monitor, monitor_at, selection_ok, virtual_bounds,
)

# A realistic mixed layout: 4K at 150% as primary, a 1080p at 100% on the
# left (negative x) and a 1440p at 125% above-right (negative y).
PRIMARY = Monitor(0, Rect(0, 0, 3840, 2160), Rect(0, 0, 2560, 1440), 1.5, primary=True)
LEFT = Monitor(1, Rect(-1920, 300, 1920, 1080), Rect(-1920, 300, 1920, 1080), 1.0)
TOP = Monitor(2, Rect(3840, -1440, 2560, 1440), Rect(3840, -1440, 2048, 1152), 1.25)
LAYOUT = [PRIMARY, LEFT, TOP]


def test_rect_from_points_any_direction():
    assert Rect.from_points(10, 20, 2, 5) == Rect(2, 5, 8, 15)
    assert Rect.from_points(2, 5, 10, 20) == Rect(2, 5, 8, 15)


def test_rect_ops():
    a, b = Rect(0, 0, 10, 10), Rect(5, 5, 10, 10)
    assert a.intersected(b) == Rect(5, 5, 5, 5)
    assert a.united(b) == Rect(0, 0, 15, 15)
    assert a.intersected(Rect(20, 20, 5, 5)).empty
    assert a.contains(0, 0) and not a.contains(10, 10)
    assert a.iou(a) == 1.0 and a.iou(Rect(50, 50, 1, 1)) == 0.0


def test_virtual_bounds_with_negative_coordinates():
    vb = virtual_bounds(LAYOUT)
    assert vb == Rect.from_edges(-1920, -1440, 6400, 2160)


def test_monitor_at():
    assert monitor_at(LAYOUT, -5, 400) is LEFT
    assert monitor_at(LAYOUT, 100, 100) is PRIMARY
    assert monitor_at(LAYOUT, 4000, -10) is TOP
    assert monitor_at(LAYOUT, -5, 0) is None  # gap above the left monitor


@pytest.mark.parametrize("mon,local,expected", [
    (PRIMARY, (0, 0), (0, 0)),
    (PRIMARY, (100, 50), (150, 75)),
    (PRIMARY, (2560, 1440), (3840, 2160)),  # far edge reachable
    (LEFT, (0, 0), (-1920, 300)),
    (LEFT, (1919, 1079), (-1, 1379)),
    (TOP, (0, 0), (3840, -1440)),
    (TOP, (100, 100), (3965, -1315)),
    (TOP, (2048, 1152), (6400, 0)),
])
def test_local_to_physical(mon, local, expected):
    assert mon.local_to_physical(*local) == expected


def test_fractional_logical_positions_round_to_nearest_pixel():
    # Qt 6 reports fractional positions on fractional scaling.
    assert PRIMARY.local_to_physical(100.334, 0) == (151, 0)  # 150.5 -> 151
    assert PRIMARY.local_to_physical(100.32, 0) == (150, 0)


def test_points_outside_the_monitor_are_clamped():
    assert PRIMARY.local_to_physical(-50, 3000) == (0, 2160)
    assert LEFT.local_to_physical(5000, -1) == (0, 300)


def test_local_rect_to_physical_on_scaled_negative_monitor():
    r = TOP.local_rect_to_physical(200, 120, 40, 20)  # dragged up-left
    assert r == Rect(3890, -1415, 200, 125)


def test_physical_local_roundtrip():
    for mon in LAYOUT:
        for px, py in [(mon.physical.x, mon.physical.y), (mon.physical.x + 333, mon.physical.y + 77)]:
            lx, ly = mon.physical_to_local(px, py)
            assert mon.local_to_physical(lx, ly) == (px, py)


def test_crop_offsets_against_virtual_origin():
    vb = virtual_bounds(LAYOUT)
    sel = LEFT.local_rect_to_physical(10, 10, 110, 60)
    crop = crop_offsets(sel, vb.x, vb.y)
    # -1920 + 10 - (-1920) = 10 ; 300 + 10 - (-1440) = 1750
    assert crop == Rect(10, 1750, 100, 50)


def test_selection_size_rules():
    assert selection_ok(Rect(0, 0, 8, 8), 8)
    assert not selection_ok(Rect(0, 0, 7, 100), 8)
    assert not selection_ok(Rect(0, 0, 0, 0), 1)


def test_match_monitor_by_handle_then_geometry():
    native = [(111, Rect(0, 0, 2560, 1600)), (222, Rect(-1920, 0, 1920, 1080))]
    assert match_monitor(222, Rect(0, 0, 1707, 1067), 1.5, native) == Rect(-1920, 0, 1920, 1080)
    assert match_monitor(0, Rect(0, 0, 1707, 1067), 1.5, native) == Rect(0, 0, 2560, 1600)
    assert match_monitor(0, Rect(-1920, 0, 1920, 1080), 1.0, native) == Rect(-1920, 0, 1920, 1080)
    assert match_monitor(0, Rect(5000, 5000, 100, 100), 1.0, native) is None
