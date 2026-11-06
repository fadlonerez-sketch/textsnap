"""Selection overlay: drag geometry, DPI mapping, cancellation, teardown."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from textsnap.capture.convert import qimage_to_rgb
from textsnap.capture.geometry import Monitor, Rect
from textsnap.capture.windows import WindowInfo
from textsnap.ui.overlay import SelectionSession

from helpers import coordinate_image, decode, snapshot_from


def make_session(qtbot, dpr=1.0, phys_origin=(0, 0), **kw):
    # The offscreen Qt screen is 800x800 logical; give it a physical size of
    # 800*dpr at a (possibly negative) origin to model a scaled monitor.
    size = int(800 * dpr)
    mon = Monitor(0, Rect(phys_origin[0], phys_origin[1], size, size), Rect(0, 0, 800, 800), dpr)
    snap = snapshot_from([mon], coordinate_image(mon.physical), kw.pop("windows", None))
    session = SelectionSession(snap, activate=False, **kw)
    session.start()
    win = session.windows[0]
    qtbot.waitExposed(win)
    return session, snap, win


def drag(win, a, b, button=Qt.MouseButton.LeftButton):
    QTest.mousePress(win, button, Qt.KeyboardModifier.NoModifier, QPoint(*a))
    QTest.mouseMove(win, QPoint((a[0] + b[0]) // 2, (a[1] + b[1]) // 2))
    QTest.mouseMove(win, QPoint(*b))
    QTest.mouseRelease(win, button, Qt.KeyboardModifier.NoModifier, QPoint(*b))


@pytest.mark.parametrize("dpr,origin", [(1.0, (0, 0)), (1.5, (0, 0)), (1.25, (-1000, -400)), (2.0, (2560, 0))])
def test_drag_selects_matching_physical_rect(qtbot, dpr, origin):
    session, snap, win = make_session(qtbot, dpr, origin)
    with qtbot.waitSignal(session.selected, timeout=2000) as sig:
        drag(win, (100, 120), (300, 220))
    rect, mode = sig.args
    assert mode == "region"
    ox, oy = origin
    assert rect == Rect(ox + round(100 * dpr), oy + round(120 * dpr), round(200 * dpr), round(100 * dpr))
    crop = qimage_to_rgb(snap.crop(rect))
    assert crop.shape[:2] == (rect.h, rect.w)
    assert decode(crop[0, 0], snap.bounds) == (rect.x, rect.y)  # exact pixel alignment
    assert decode(crop[-1, -1], snap.bounds) == (rect.right - 1, rect.bottom - 1)


def test_reverse_drag_direction(qtbot):
    session, _snap, win = make_session(qtbot)
    with qtbot.waitSignal(session.selected, timeout=2000) as sig:
        drag(win, (300, 220), (100, 120))
    assert sig.args[0] == Rect(100, 120, 200, 100)


def test_too_small_selection_keeps_overlay_open(qtbot):
    session, _snap, win = make_session(qtbot, min_px=20)
    with qtbot.assertNotEmitted(session.selected, wait=200):
        drag(win, (100, 100), (110, 105))
    assert not session.finished and win.isVisible()
    assert "Too small" in win._message
    with qtbot.waitSignal(session.selected, timeout=2000):
        drag(win, (100, 100), (200, 160))  # a new selection works


def test_escape_cancels(qtbot):
    session, _snap, win = make_session(qtbot)
    with qtbot.waitSignal(session.cancelled, timeout=2000):
        QTest.keyClick(win, Qt.Key.Key_Escape)
    assert session.finished and not session.windows


def test_right_click_cancels_and_aborts_drag(qtbot):
    session, _snap, win = make_session(qtbot)
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 50))
    QTest.mouseMove(win, QPoint(150, 150))
    QTest.mouseClick(win, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 150))
    assert not session.finished  # first right-click only abandons the drag
    with qtbot.waitSignal(session.cancelled, timeout=2000):
        QTest.mouseClick(win, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 150))


def test_external_escape_and_teardown(qtbot):
    session, snap, win = make_session(qtbot)
    with qtbot.waitSignal(session.cancelled, timeout=2000):
        session.cancel()  # e.g. Esc seen by the keyboard hook
    assert not win.isVisible() and win.pixmap.isNull()
    session.cancel()  # idempotent
    snap.release()
    assert snap.image.isNull()


def test_all_screens_key(qtbot):
    session, snap, win = make_session(qtbot)
    with qtbot.waitSignal(session.selected, timeout=2000) as sig:
        QTest.keyClick(win, Qt.Key.Key_A)
    assert sig.args == [snap.bounds, "desktop"]


def test_monitor_mode_click(qtbot):
    session, snap, win = make_session(qtbot, 1.5)
    QTest.keyClick(win, Qt.Key.Key_M)
    assert session.mode == "monitor"
    QTest.mouseMove(win, QPoint(400, 400))
    with qtbot.waitSignal(session.selected, timeout=2000) as sig:
        QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(400, 400))
    assert sig.args == [snap.monitors[0].physical, "monitor"]


def test_window_mode_picks_topmost_window(qtbot):
    windows = [WindowInfo(1, Rect(100, 100, 200, 150)), WindowInfo(2, Rect(50, 50, 600, 600))]
    session, _snap, win = make_session(qtbot, windows=windows)
    QTest.keyClick(win, Qt.Key.Key_W)
    QTest.mouseMove(win, QPoint(150, 150))
    with qtbot.waitSignal(session.selected, timeout=2000) as sig:
        QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 150))
    assert sig.args == [Rect(100, 100, 200, 150), "window"]


def test_enter_repeats_last_region(qtbot):
    last = Rect(10, 20, 30, 40)
    session, _snap, win = make_session(qtbot, last_region=last)
    with qtbot.waitSignal(session.selected, timeout=2000) as sig:
        QTest.keyClick(win, Qt.Key.Key_Return)
    assert sig.args == [last, "repeat"]


def test_selection_emitted_once(qtbot):
    session, _snap, win = make_session(qtbot)
    seen = []
    session.selected.connect(lambda r, m: seen.append(r))
    drag(win, (10, 10), (200, 200))
    session.finish(Rect(0, 0, 50, 50), "region")
    session.cancel()
    assert len(seen) == 1
