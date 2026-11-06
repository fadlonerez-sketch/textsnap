"""Full-screen selection overlay.

One borderless top-most window per monitor shows the frozen desktop image
dimmed, with the selection cut out at full brightness. Each window maps its
own logical coordinates to physical pixels with its monitor's scale factor
(see capture.geometry), so mixed-DPI setups and negative coordinates work.

Modes: region (drag, the default), window (click the highlighted window),
screen (click a monitor) and "all screens" (key A / toolbar).

Motion never gates input: the dim fades in while the mouse is already live,
and the completion flash runs in a separate click-through window after the
overlay has closed and OCR has started. Cancelling closes instantly.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QImage, QKeyEvent, QMouseEvent, QPainter, QPainterPath,
    QPen, QPixmap, QRegion,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from textsnap.capture.geometry import Monitor, Rect, monitor_at, selection_ok
from textsnap.capture.screen import DesktopSnapshot
from textsnap.capture.windows import window_at
from textsnap.ui import motion, theme
from textsnap.ui.theme import C, R

log = logging.getLogger(__name__)

REGION, WINDOW, MONITOR, DESKTOP = "region", "window", "monitor", "desktop"
MAG_SIZE = 136  # logical px
MAG_ZOOM = 5  # physical pixels -> screen pixels in the magnifier
DIM_RGB = (6, 8, 12)
BRACKET = 14  # corner bracket arm length (logical px)
_PENDING_DELETE: list = []
_FLASHES: list = []


class CaptureFlash(QWidget):
    """A brief highlight over the captured area, shown after the overlay closed.

    Click-through, never focusable, deletes itself; it cannot delay OCR or
    take focus away from the application the user returns to.
    """

    def __init__(self, global_rect: QRect, screen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.NoDropShadowWindowHint)
        for attr in (Qt.WidgetAttribute.WA_TranslucentBackground, Qt.WidgetAttribute.WA_ShowWithoutActivating,
                     Qt.WidgetAttribute.WA_TransparentForMouseEvents, Qt.WidgetAttribute.WA_DeleteOnClose):
            self.setAttribute(attr, True)
        self.setWindowTitle("TextSnap capture")
        if screen is not None:
            self.setScreen(screen)
        self._pad = 6
        self.setGeometry(global_rect.adjusted(-self._pad, -self._pad, self._pad, self._pad))
        self._t = 1.0

    def start(self) -> None:
        _FLASHES.append(self)
        self.destroyed.connect(lambda *_: _FLASHES.remove(self) if self in _FLASHES else None)
        self.show()
        motion.tween(self, 1.0, 0.0, motion.Duration.SLOW + 80, self._set, motion.Ease.OUT, on_done=self.close,
                     key="flash")

    def _set(self, v: float) -> None:
        self._t = v
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(self._pad, self._pad, -self._pad, -self._pad)
        fill = QColor(C.ACCENT)
        fill.setAlpha(int(46 * self._t))
        p.fillRect(r, fill)
        edge = QColor(C.ACCENT)
        edge.setAlpha(int(255 * self._t))
        _paint_frame(p, r, edge, self._t)
        p.end()


def _paint_frame(p: QPainter, r: QRectF, accent: QColor, alpha: float = 1.0) -> None:
    """Selection frame: dark outline + accent border + corner brackets."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setBrush(Qt.BrushStyle.NoBrush)
    outline = QPen(QColor(0, 0, 0, int(150 * alpha)), 1)
    outline.setCosmetic(True)
    p.setPen(outline)
    p.drawRect(r.adjusted(-2, -2, 1, 1))
    border = QPen(accent, 1.5)
    border.setCosmetic(True)
    p.setPen(border)
    p.drawRect(r.adjusted(-1, -1, 0, 0))
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    arm = min(BRACKET, r.width() / 2.5, r.height() / 2.5)
    if arm >= 4:
        pen = QPen(accent, 3)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        p.setPen(pen)
        o = 2.5
        for (x, y, dx, dy) in ((r.left() - o, r.top() - o, 1, 1), (r.right() + o, r.top() - o, -1, 1),
                               (r.left() - o, r.bottom() + o, 1, -1), (r.right() + o, r.bottom() + o, -1, -1)):
            path = QPainterPath(QPointF(x + dx * arm, y))
            path.lineTo(QPointF(x, y))
            path.lineTo(QPointF(x, y + dy * arm))
            p.drawPath(path)
    p.restore()


class SelectionSession(QObject):
    """Coordinates the overlay windows of one capture."""

    selected = Signal(object, str)  # Rect (physical), mode
    cancelled = Signal()

    def __init__(self, snapshot: DesktopSnapshot, mode: str = REGION, *, magnifier: bool = True,
                 crosshair: bool = False, dimensions: bool = True, dim_percent: int = 45,
                 min_px: int = 8, last_region: Rect | None = None, activate: bool = True):
        super().__init__()
        self.snapshot = snapshot
        self.mode = mode if mode in (REGION, WINDOW, MONITOR) else REGION
        self.magnifier = magnifier
        self.crosshair = crosshair
        self.dimensions = dimensions
        self.dim_alpha = int(255 * max(0.1, min(0.85, dim_percent / 100)))
        self.min_px = min_px
        self.last_region = last_region
        self._activate = activate
        self.windows: list[OverlayWindow] = []
        self.finished = False

    def start(self) -> None:
        for flash in list(_FLASHES):  # a new capture replaces any lingering completion flash
            flash.close()
        screens = QGuiApplication.screens()
        for m in self.snapshot.monitors:
            screen = screens[m.index] if m.index < len(screens) else None
            w = OverlayWindow(self, m, screen)
            self.windows.append(w)
        for w in self.windows:
            w.show_on_screen()
        target = self._window_under_cursor() or (self.windows[0] if self.windows else None)
        if target is not None and self._activate:
            QTimer.singleShot(0, target, target.take_focus)

    def _window_under_cursor(self) -> "OverlayWindow | None":
        from textsnap.winsys.focus import user32  # local: Windows only
        import ctypes.wintypes as wt
        import ctypes
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        mon = monitor_at(self.snapshot.monitors, pt.x, pt.y)
        return next((w for w in self.windows if w.monitor is mon), None)

    def set_mode(self, mode: str) -> None:
        if mode == DESKTOP:
            self.finish(self.snapshot.bounds, DESKTOP)
            return
        self.mode = mode
        for w in self.windows:
            w.mode_changed()

    def repeat_last(self) -> bool:
        if self.last_region is None:
            for w in self.windows:
                w.flash("No previous selection to repeat")
            return False
        self.finish(self.last_region, "repeat")
        return True

    def finish(self, rect: Rect, mode: str) -> None:
        if self.finished:
            return
        self.finished = True
        if mode != DESKTOP and not motion.reduced():
            self._flash_capture(rect)
        self._close_windows()
        self.selected.emit(rect, mode)

    def cancel(self) -> None:
        if self.finished:
            return
        self.finished = True
        self._close_windows()
        self.cancelled.emit()

    def _flash_capture(self, rect: Rect) -> None:
        for w in self.windows:
            local = w._local_rect(rect)
            if local.isEmpty() or local.width() < 4 or local.height() < 4:
                continue
            g = w.monitor.logical
            global_rect = local.toAlignedRect().translated(g.x, g.y)
            try:
                CaptureFlash(global_rect, w._screen).start()
            except Exception:  # purely cosmetic: never let it affect the capture
                log.debug("Capture flash unavailable", exc_info=True)

    def _close_windows(self) -> None:
        # This often runs inside one of the windows' own event handlers, so the
        # Python references are kept until the event loop has moved on.
        closing = list(self.windows)
        for w in closing:
            w.stop_animations()
            w.hide()
            w.release()
            w.deleteLater()
        self.windows.clear()
        _PENDING_DELETE.extend(closing)
        QTimer.singleShot(100, lambda: [_PENDING_DELETE.remove(w) for w in closing if w in _PENDING_DELETE])


class OverlayToolbar(QWidget):
    MODES = [(REGION, "region", "Region", "R"), (WINDOW, "window", "Window", "W"),
             (MONITOR, "monitor", "Screen", "M"), (DESKTOP, "desktop", "All screens", "A")]

    def __init__(self, session: SelectionSession, parent: QWidget):
        super().__init__(parent)
        self.session = session
        self.setObjectName("overlayToolbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 7)
        outer.setSpacing(5)
        row = QHBoxLayout()
        row.setSpacing(2)
        self.buttons: dict[str, QToolButton] = {}
        for mode, glyph, caption, key in self.MODES:
            b = QToolButton(self)
            b.setText(" " + caption)
            b.setIcon(theme.icon(glyph, C.TEXT_2, 15))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setToolTip(f"{caption}  ({key})")
            b.setCheckable(mode != DESKTOP)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, m=mode: session.set_mode(m))
            row.addWidget(b)
            self.buttons[mode] = b
        sep = QWidget(self)
        sep.setObjectName("overlaySep")
        sep.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sep.setFixedSize(1, 18)
        row.addSpacing(4)
        row.addWidget(sep)
        row.addSpacing(4)
        close = QToolButton(self)
        close.setIcon(theme.icon("close", C.TEXT_2, 12))
        close.setToolTip("Cancel  (Esc)")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(session.cancel)
        row.addWidget(close)
        outer.addLayout(row)
        self.hint = QLabel(self)
        self.hint.setTextFormat(Qt.TextFormat.RichText)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.hint)
        self.sync()

    @staticmethod
    def _key(k: str) -> str:
        return (f"<span style='color:{C.TEXT_2}; background:{C.RAISED_HOVER}; border-radius:3px;'>"
                f"&nbsp;{k}&nbsp;</span>")

    def sync(self) -> None:
        for mode, b in self.buttons.items():
            b.setChecked(mode == self.session.mode)
            glyph = next(g for m, g, _c, _k in self.MODES if m == mode)
            b.setIcon(theme.icon(glyph, C.ACCENT if mode == self.session.mode else C.TEXT_2, 15))
        k = self._key
        hints = {REGION: f"Drag over the text &nbsp;·&nbsp; {k('Enter')} last area &nbsp;·&nbsp; "
                         f"{k('Esc')} cancel",
                 WINDOW: f"Click a window to read it &nbsp;·&nbsp; {k('Esc')} cancel",
                 MONITOR: f"Click a screen to read it &nbsp;·&nbsp; {k('Esc')} cancel"}
        self.hint.setText(hints.get(self.session.mode, ""))
        self.adjustSize()


class OverlayWindow(QWidget):
    def __init__(self, session: SelectionSession, monitor: Monitor, screen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.NoDropShadowWindowHint)
        self.session = session
        self.monitor = monitor
        self._screen = screen
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWindowTitle("TextSnap selection")
        image: QImage = session.snapshot.monitor_image(monitor)
        self.pixmap = QPixmap.fromImage(image)
        self.pixmap.setDevicePixelRatio(monitor.dpr)
        self._image = image  # physical pixels, for the magnifier
        self._drag_start: QPointF | None = None
        self._cursor: QPointF | None = None
        self._hover: Rect | None = None
        self._message = ""
        self._dim_t = 1.0  # dim fade-in progress
        self._last_dirty = QRegion()
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self._clear_message)
        self._label_font = theme.font(12, QFont.Weight.DemiBold)
        self._small_font = theme.font(11, QFont.Weight.Medium)
        self._message_font = theme.font(14, QFont.Weight.Medium)
        self.toolbar = OverlayToolbar(session, self)
        self.toolbar.hide()
        self._toolbar_shown = False

    # -- lifecycle -------------------------------------------------------
    def show_on_screen(self) -> None:
        if self._screen is not None:
            self.setScreen(self._screen)
        g = self.monitor.logical
        self.setGeometry(QRect(g.x, g.y, g.w, g.h))
        if not motion.reduced():
            self._dim_t = 0.0
        self.show()
        self.raise_()
        local = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(local):
            self._cursor = QPointF(local)
            self._update_hover()
        self._place_toolbar()
        # The dim fades in while input is already live (never gates selection).
        motion.tween(self, self._dim_t, 1.0, motion.Duration.FAST + 40, self._set_dim, motion.Ease.OUT, key="dim")

    def _set_dim(self, v: float) -> None:
        self._dim_t = v
        self.update()

    def stop_animations(self) -> None:
        motion.stop(self, "dim")
        self._dim_t = 1.0

    def take_focus(self) -> None:
        from textsnap.winsys.focus import force_foreground
        self.activateWindow()
        self.raise_()
        force_foreground(int(self.winId()))
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def release(self) -> None:
        self.pixmap = QPixmap()
        self._image = QImage()

    def _place_toolbar(self) -> None:
        self.toolbar.sync()
        self.toolbar.adjustSize()
        self.toolbar.move((self.width() - self.toolbar.width()) // 2, 22)
        visible = self._cursor is not None
        if visible and not self._toolbar_shown:
            self._toolbar_shown = True
            self.toolbar.setVisible(True)
            motion.fade_in(self.toolbar, motion.Duration.BASE)
        else:
            self.toolbar.setVisible(visible)

    def mode_changed(self) -> None:
        self._drag_start = None
        self._hover = None
        self.toolbar.sync()
        self._place_toolbar()
        self._update_hover()
        self.update()

    def flash(self, message: str) -> None:
        self._message = message
        self._message_timer.start(2200)
        self.update()

    def _clear_message(self) -> None:
        self._message = ""
        self.update()

    # -- geometry helpers --------------------------------------------------
    def _physical(self, p: QPointF) -> tuple[int, int]:
        return self.monitor.local_to_physical(p.x(), p.y())

    def _local_rect(self, r: Rect) -> QRectF:
        x, y, w, h = self.monitor.physical_rect_to_local(r.intersected(self.monitor.physical))
        return QRectF(x, y, w, h)

    def current_selection(self) -> Rect | None:
        """The physical rectangle that a mouse release would select now."""
        mode = self.session.mode
        if mode == REGION:
            if self._drag_start is None or self._cursor is None:
                return None
            return self.monitor.local_rect_to_physical(self._drag_start.x(), self._drag_start.y(),
                                                       self._cursor.x(), self._cursor.y())
        if mode == WINDOW:
            return self._hover
        if mode == MONITOR:
            return self.monitor.physical if self._cursor is not None else None
        return None

    def _update_hover(self) -> None:
        if self.session.mode != WINDOW or self._cursor is None:
            self._hover = None
            return
        px, py = self._physical(self._cursor)
        win = window_at(self.session.snapshot.windows, px, py)
        self._hover = win.rect.intersected(self.session.snapshot.bounds) if win else self.monitor.physical

    # -- painting ------------------------------------------------------------
    def _label(self, sel: Rect) -> tuple[str, bool]:
        label = f"{sel.w} × {sel.h}"
        too_small = self.session.mode == REGION and not selection_ok(sel, self.session.min_px)
        if too_small:
            label += f"   minimum {self.session.min_px} × {self.session.min_px}"
        return label, too_small

    def _label_box(self, sel: Rect, r: QRectF) -> QRectF:
        """Where the size label is drawn (shared by painting and invalidation)."""
        fm = QFontMetrics(self._label_font)
        text, _ = self._label(sel)
        box = QRectF(0, 0, fm.horizontalAdvance(text) + 18, fm.height() + 10)
        y = r.bottom() + 10 if r.bottom() + box.height() + 12 < self.height() else r.bottom() - box.height() - 10
        box.moveTo(max(6.0, min(r.left(), self.width() - box.width() - 6)), y)
        return box

    def _dirty_region(self) -> QRegion:
        region = QRegion()
        sel = self.current_selection()
        if sel is not None:
            local = self._local_rect(sel)
            region += local.toAlignedRect().adjusted(-8, -8, 8, 8)
            if self.session.dimensions:
                region += self._label_box(sel, local).toAlignedRect().adjusted(-2, -2, 2, 2)
        if self._cursor is not None:
            c = self._cursor.toPoint()
            if self.session.crosshair:
                region += QRect(0, c.y() - 1, self.width(), 3)
                region += QRect(c.x() - 1, 0, 3, self.height())
            if self.session.magnifier:
                region += self._magnifier_rect().toAlignedRect().adjusted(-4, -4, 4, 30)
        if self._message:
            region += QRect(0, 0, self.width(), 170)
        return region

    def _refresh(self) -> None:
        new = self._dirty_region()
        self.update(new + self._last_dirty)
        self._last_dirty = new

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setClipRegion(event.region())
        p.drawPixmap(0, 0, self.pixmap)
        sel = self.current_selection()
        sel_local = self._local_rect(sel) if sel is not None else None
        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        if sel_local is not None and not sel_local.isEmpty():
            dim.addRect(sel_local)
        dim.setFillRule(Qt.FillRule.OddEvenFill)
        p.fillPath(dim, QColor(*DIM_RGB, int(self.session.dim_alpha * self._dim_t)))

        if sel_local is not None and not sel_local.isEmpty():
            self._paint_selection(p, sel, sel_local)
        if self._cursor is not None and self.session.crosshair and self._drag_start is None:
            for color, width in ((QColor(0, 0, 0, 90), 3), (QColor(255, 255, 255, 120), 1)):
                pen = QPen(color, width)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.drawLine(QPointF(0, self._cursor.y()), QPointF(self.width(), self._cursor.y()))
                p.drawLine(QPointF(self._cursor.x(), 0), QPointF(self._cursor.x(), self.height()))
        if self._cursor is not None and self.session.magnifier:
            self._paint_magnifier(p)
        if self._message:
            self._paint_message(p)
        p.end()

    def _paint_selection(self, p: QPainter, sel: Rect, r: QRectF) -> None:
        _paint_frame(p, r, QColor(C.ACCENT))
        if self.session.dimensions:
            label, too_small = self._label(sel)
            box = self._label_box(sel, r)
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(QPen(QColor(255, 255, 255, 22), 1))
            p.setBrush(QColor(14, 16, 21, 236))
            p.drawRoundedRect(box, R.SM, R.SM)
            p.setFont(self._label_font)
            p.setPen(QColor(C.WARNING if too_small else C.TEXT))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
            p.restore()

    def _magnifier_rect(self) -> QRectF:
        c = self._cursor or QPointF()
        x, y = c.x() + 26, c.y() + 26
        if x + MAG_SIZE > self.width() - 6:
            x = c.x() - 26 - MAG_SIZE
        if y + MAG_SIZE + 28 > self.height() - 6:
            y = c.y() - 26 - MAG_SIZE - 28
        return QRectF(x, y, MAG_SIZE, MAG_SIZE)

    def _paint_magnifier(self, p: QPainter) -> None:
        if self._image.isNull():
            return
        target = self._magnifier_rect()
        px, py = self._physical(self._cursor)
        lx, ly = px - self.monitor.physical.x, py - self.monitor.physical.y
        dpr = self.monitor.dpr
        span = max(9, int(MAG_SIZE * dpr / MAG_ZOOM)) | 1  # odd: a centre pixel exists
        src = QRect(lx - span // 2, ly - span // 2, span, span)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        shadow = QPainterPath()
        shadow.addRoundedRect(target.adjusted(-1, 1, 1, 3), R.LG + 2, R.LG + 2)
        p.fillPath(shadow, QColor(0, 0, 0, 110))
        clip = QPainterPath()
        clip.addRoundedRect(target, R.LG, R.LG)
        p.fillPath(clip, QColor(0, 0, 0))
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(target, self._image, QRectF(src))
        cell = target.width() / span
        mid = span // 2
        guide = QColor(C.ACCENT)
        guide.setAlpha(110)
        p.setPen(QPen(guide, 1))
        cx = target.left() + (mid + 0.5) * cell
        cy = target.top() + (mid + 0.5) * cell
        p.drawLine(QPointF(target.left(), cy), QPointF(target.left() + mid * cell, cy))
        p.drawLine(QPointF(target.left() + (mid + 1) * cell, cy), QPointF(target.right(), cy))
        p.drawLine(QPointF(cx, target.top()), QPointF(cx, target.top() + mid * cell))
        p.drawLine(QPointF(cx, target.top() + (mid + 1) * cell), QPointF(cx, target.bottom()))
        p.setPen(QPen(QColor(255, 255, 255, 230), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(target.left() + mid * cell, target.top() + mid * cell, cell, cell))
        p.restore()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(target, R.LG, R.LG)
        p.setFont(self._small_font)
        text = f"{px}, {py}"
        fm = p.fontMetrics()
        info = QRectF(0, 0, fm.horizontalAdvance(text) + 16, 20)
        info.moveCenter(QPointF(target.center().x(), target.bottom() + 16))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(14, 16, 21, 230))
        p.drawRoundedRect(info, 10, 10)
        p.setPen(QColor(C.TEXT_2))
        p.drawText(info, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()

    def _paint_message(self, p: QPainter) -> None:
        p.save()
        p.setFont(self._message_font)
        fm = p.fontMetrics()
        box = QRectF(0, 0, fm.horizontalAdvance(self._message) + 56, fm.height() + 20)
        box.moveCenter(QPointF(self.width() / 2, 132))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(QColor(242, 184, 75, 90), 1))
        p.setBrush(QColor(38, 30, 14, 240))
        p.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        p.setPen(QColor(C.WARNING))
        p.setFont(theme.glyph_font(14))
        p.drawText(QRectF(box.left() + 14, box.top(), 20, box.height()), Qt.AlignmentFlag.AlignCenter,
                   theme.GLYPH["warning"])
        p.setFont(self._message_font)
        p.setPen(QColor("#FBE3B5"))
        p.drawText(box.adjusted(32, 0, -12, 0), Qt.AlignmentFlag.AlignCenter, self._message)
        p.restore()

    # -- input -----------------------------------------------------------------
    def enterEvent(self, event) -> None:  # noqa: N802
        self.toolbar.show()
        self._place_toolbar()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is None:
            self._cursor = None
            self._hover = None
            self.toolbar.hide()
            self._refresh()

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.RightButton:
            if self._drag_start is not None:
                self._drag_start = None  # abandon this drag, keep the overlay
                self._refresh()
            else:
                self.session.cancel()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._cursor = e.position()
        if self.session.mode == REGION:
            self._drag_start = e.position()
            self.toolbar.hide()
        self._refresh()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        self._cursor = e.position()
        if not self.toolbar.isVisible() and self._drag_start is None:
            self.toolbar.show()
        self._update_hover()
        self._refresh()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._cursor = e.position()
        mode = self.session.mode
        if mode == REGION:
            if self._drag_start is None:
                return
            sel = self.current_selection()
            self._drag_start = None
            self.toolbar.show()
            if sel is None or not selection_ok(sel, self.session.min_px):
                self.flash(f"Too small — drag over at least {self.session.min_px} × "
                           f"{self.session.min_px} pixels")
                self._refresh()
                return
            self.session.finish(sel, REGION)
        elif mode in (WINDOW, MONITOR):
            sel = self.current_selection()
            if sel is not None and not sel.empty:
                self.session.finish(sel, mode)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        key = e.key()
        if key == Qt.Key.Key_Escape:
            self.session.cancel()
        elif key == Qt.Key.Key_R:
            self.session.set_mode(REGION)
        elif key == Qt.Key.Key_W:
            self.session.set_mode(WINDOW)
        elif key == Qt.Key.Key_M:
            self.session.set_mode(MONITOR)
        elif key == Qt.Key.Key_A:
            self.session.set_mode(DESKTOP)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.session.repeat_last()
        else:
            super().keyPressEvent(e)
