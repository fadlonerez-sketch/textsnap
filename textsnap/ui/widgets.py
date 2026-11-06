"""Reusable components of the TextSnap design system, plus the settings binder.

Components never carry their own style sheets: they set an object name and,
where they have states, a dynamic property (``kind``, ``tone``,
``selected``); every rule lives in ``theme.stylesheet()``. Changing a state
is a property change plus a re-polish, which is far cheaper than parsing a
per-widget style sheet and keeps all styling in one place.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from textsnap.ui import motion, theme
from textsnap.ui.theme import C, S, T

TONE_OF = {C.TEXT: "default", C.TEXT_2: "muted", C.TEXT_3: "subtle", C.ACCENT: "accent", C.DANGER: "danger",
           C.SUCCESS: "success", C.WARNING: "warning"}


def set_prop(widget: QWidget, name: str, value: Any) -> None:
    """Change a styling property and re-apply the style sheet rules for it."""
    if widget.property(name) != value:
        widget.setProperty(name, value)
        theme.polish(widget)


# ----------------------------------------------------------------------------- primitives
def label(text: str, name: str = "", wrap: bool = True, rich: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    lab.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
    if rich:
        lab.setOpenExternalLinks(False)
    return lab


def overline(text: str) -> QLabel:
    """Small uppercase section label."""
    lab = QLabel(text.upper())
    lab.setObjectName("overline")
    f = theme.font(T.CAPTION, QFont.Weight.DemiBold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
    lab.setFont(f)
    return lab


def keycap(text: str, large: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("keycapLarge" if large else "keycap")
    lab.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lab


def glyph(name: str, color: str = C.TEXT_2, px: int = 16) -> QLabel:
    """An icon from the icon font as a label (tone and size come from the style sheet)."""
    assert px in theme.GLYPH_SIZES, f"add {px} to theme.GLYPH_SIZES"
    lab = QLabel(theme.GLYPH.get(name, name))
    lab.setObjectName("glyphIcon")
    lab.setProperty("tone", TONE_OF.get(color, "muted"))
    lab.setProperty("px", str(px))
    lab.setFixedSize(px + 4, px + 4)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lab


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("divider")
    f.setFrameShape(QFrame.Shape.NoFrame)
    return f


divider = hline


def button(text: str, icon: str | None = None, variant: str = "", tooltip: str = "",
           on_click: Callable[[], Any] | None = None) -> QPushButton:
    """Standard button. ``variant``: '', 'primary', 'hero', 'ghost', 'link' or 'danger'."""
    b = QPushButton((" " + text) if icon and text else text)  # breathing room between icon and label
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # focus ring for keyboard users, not after every click
    if variant:
        b.setObjectName(variant)
    if icon:
        color = {"primary": C.ON_ACCENT, "hero": C.ON_ACCENT, "link": C.ACCENT, "danger": "#FF9B9B"}.get(
            variant, C.TEXT_2)
        b.setIcon(theme.icon(icon, color, 16))
        b.setIconSize(QSize(16, 16))
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click is not None:
        b.clicked.connect(lambda _=False: on_click())
    return b


def row_layout(*widgets, spacing: int = S.SM, stretch_end: bool = True) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for w in widgets:
        if isinstance(w, QWidget):
            lay.addWidget(w)
        elif w is None:
            lay.addStretch(1)
        else:
            lay.addLayout(w)
    if stretch_end:
        lay.addStretch(1)
    return lay


# ----------------------------------------------------------------------------- toggle
class Toggle(QCheckBox):
    """On/off switch: a QCheckBox painted as a track with a sliding knob."""

    TRACK_W, TRACK_H = 38, 22

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._pos = 0.0  # 0 = off, 1 = on (animated)
        self._hover = False
        self.toggled.connect(self._animate)

    def _animate(self, on: bool) -> None:
        motion.tween(self, self._pos, 1.0 if on else 0.0, motion.Duration.FAST, self._set_pos, key="knob")

    def _set_pos(self, v: float) -> None:
        self._pos = v
        self.update()

    def setChecked(self, on: bool) -> None:  # noqa: N802 - Qt API
        super().setChecked(on)
        if self.signalsBlocked():  # programmatic refresh: jump straight to the end state
            motion.stop(self, "knob")
            self._pos = 1.0 if on else 0.0
            self.update()

    def showEvent(self, e) -> None:  # noqa: N802
        motion.stop(self, "knob")
        self._pos = 1.0 if self.isChecked() else 0.0
        super().showEvent(e)

    def enterEvent(self, e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        extra = 12 + fm.horizontalAdvance(self.text()) if self.text() else 0
        return QSize(self.TRACK_W + extra + 4, max(self.TRACK_H + 4, fm.height() + 6))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = (self.height() - self.TRACK_H) / 2
        track = QRectF(2, y, self.TRACK_W, self.TRACK_H)
        enabled = self.isEnabled()
        off_col, on_col = QColor(C.RAISED_HOVER), QColor(C.ACCENT)
        t = self._pos
        col = QColor(round(off_col.red() + (on_col.red() - off_col.red()) * t),
                     round(off_col.green() + (on_col.green() - off_col.green()) * t),
                     round(off_col.blue() + (on_col.blue() - off_col.blue()) * t))
        if self._hover and enabled:
            col = col.lighter(112)
        if not enabled:
            col.setAlpha(90)
        p.setPen(QPen(QColor("#3A4150"), 1) if t < 0.5 else Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)
        r = self.TRACK_H / 2 - 4
        cx = track.left() + self.TRACK_H / 2 + (self.TRACK_W - self.TRACK_H) * t
        knob = QColor("#FFFFFF") if t > 0.5 else QColor("#C5CAD3")
        if not enabled:
            knob = QColor(C.TEXT_DISABLED)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(knob)
        p.drawEllipse(QRectF(cx - r, y + 4, 2 * r, 2 * r))
        if self.hasFocus() and self.focusPolicy() != Qt.FocusPolicy.NoFocus:
            p.setPen(QPen(QColor(C.ACCENT), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(track.adjusted(-2, -2, 2, 2), self.TRACK_H / 2 + 2, self.TRACK_H / 2 + 2)
        if self.text():
            p.setPen(QColor(C.TEXT if enabled else C.TEXT_DISABLED))
            p.setFont(self.font())
            p.drawText(QRectF(self.TRACK_W + 14, 0, self.width() - self.TRACK_W - 14, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        p.end()


# ----------------------------------------------------------------------------- cards and rows
class Card(QFrame):
    """A grouped surface. ``row()`` adds hairline-separated setting rows."""

    def __init__(self, title: str = "", description: str = "", accent: bool = False, kind: str = "card",
                 icon: str | None = None):
        super().__init__()
        self.setObjectName("hero" if accent else {"danger": "dangerCard"}.get(kind, "card"))
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(S.XL, S.LG, S.XL, S.LG)
        self.body.setSpacing(S.MD)
        self._has_rows = False
        if title or description:
            head = QVBoxLayout()
            head.setSpacing(3)
            if title:
                tl = QHBoxLayout()
                tl.setSpacing(S.SM)
                if icon:
                    tl.addWidget(glyph(icon, C.DANGER if kind == "danger" else C.TEXT_2, 16))
                tl.addWidget(label(title, "dangerTitle" if kind == "danger" else "sectionTitle"), 1)
                head.addLayout(tl)
            if description:
                head.addWidget(label(description, "hint"))
            self.body.addLayout(head)
            self.body.addSpacing(2)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)

    def row(self, text: str, widget: QWidget, hint: str = "") -> QWidget:
        """Setting row: label + hint on the left, the control on the right."""
        if self._has_rows:
            self.body.addWidget(hline())
        self._has_rows = True
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(S.XXL)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(label(text, "body"))
        if hint:
            col.addWidget(label(hint, "hint"))
        h.addLayout(col, 1)
        h.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addWidget(w)
        return w


class Page(QScrollArea):
    """A settings/dashboard page: header (title, subtitle, saved state) + scrolling content."""

    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("pageInner")
        outer = QHBoxLayout(inner)
        outer.setContentsMargins(S.PAGE_X, S.PAGE_Y, S.PAGE_X, S.PAGE_Y)
        column = QWidget()
        column.setMaximumWidth(S.MAX_CONTENT)
        outer.addWidget(column, 1)
        outer.addStretch(0)
        self.content = QVBoxLayout(column)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(S.LG)
        header = QHBoxLayout()
        header.setSpacing(S.MD)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        self.title_label = label(title, "pageTitle")
        titles.addWidget(self.title_label)
        if subtitle:
            titles.addWidget(label(subtitle, "muted"))
        header.addLayout(titles, 1)
        self.saved = SavedIndicator()
        header.addWidget(self.saved, 0, Qt.AlignmentFlag.AlignTop)
        self.content.addLayout(header)
        self.content.addSpacing(S.SM)
        self.inner = inner
        self.setWidget(inner)
        self._stretch_added = False

    def add(self, widget: QWidget) -> QWidget:
        self.content.addWidget(widget)
        return widget

    def section(self, text: str) -> QLabel:
        lab = overline(text)
        lab.setContentsMargins(2, S.SM, 0, 0)
        self.content.addWidget(lab)
        return lab

    def finish(self) -> None:
        if not self._stretch_added:
            self.content.addStretch(1)
            self._stretch_added = True

    def on_show(self) -> None:
        """Called when the page becomes visible."""


# ----------------------------------------------------------------------------- feedback components
class Banner(QFrame):
    """Inline message with an icon: info, success, warning or error."""

    def __init__(self, text: str = "", kind: str = "info"):
        super().__init__()
        self.setObjectName("banner")
        self._kind = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(S.MD, 10, S.MD, 10)
        lay.setSpacing(10)
        self._icon = QLabel()
        self._icon.setObjectName("bannerIcon")
        self._icon.setFixedWidth(20)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        self._text = label(text, "bannerText")
        self._text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(S.SM)
        lay.addLayout(self.actions)
        self.set(kind, text)

    def set(self, kind: str, text: str) -> None:
        if kind != self._kind:
            self._kind = kind
            self._icon.setText(theme.STATE_GLYPH.get(kind, theme.GLYPH["info"]))
            set_prop(self, "kind", kind)
            set_prop(self._icon, "kind", kind)
        self._text.setText(text)
        self.setVisible(bool(text))

    def setText(self, text: str) -> None:  # noqa: N802 - mirrors QLabel
        self.set(self._kind, text)

    def text(self) -> str:
        return self._text.text()

    @property
    def kind(self) -> str:
        return self._kind


class StatusPill(QFrame):
    """A small dot + text status, e.g. 'Trigger active'."""

    def __init__(self, text: str = "", kind: str = "neutral"):
        super().__init__()
        self.setObjectName("statusPill")
        self.setFixedHeight(26)  # matches the 13px radius
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 12, 4)
        lay.setSpacing(7)
        self._dot = QLabel()
        self._dot.setObjectName("pillDot")
        self._dot.setFixedSize(8, 8)
        lay.addWidget(self._dot)
        self._text = label("", "pillText", wrap=False)
        lay.addWidget(self._text)
        self.set(kind, text)

    def set(self, kind: str, text: str) -> None:
        set_prop(self._dot, "kind", kind)
        self._text.setText(text)

    def text(self) -> str:
        return self._text.text()


class SavedIndicator(QLabel):
    """'Saved' confirmation that fades in and out after a setting changes."""

    def __init__(self):
        super().__init__()
        self.setObjectName("savedIndicator")
        self.setFixedHeight(24)  # pill: Qt drops a corner radius larger than half the height
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setText(f"<span style='font-family:\"{T.icons()}\"; color:{C.SUCCESS};'>{theme.GLYPH['check']}</span>"
                     f"&nbsp;&nbsp;Saved")
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.setVisible(False)

    def flash(self) -> None:
        self.setVisible(True)
        motion.animate(self._effect, b"opacity", 1.0, motion.Duration.FAST)
        self._timer.start(1400)

    def _fade_out(self) -> None:
        motion.animate(self._effect, b"opacity", 0.0, motion.Duration.BASE,
                       on_done=lambda: self.setVisible(False))


class Spinner(QWidget):
    """Indeterminate progress arc. Its timer runs only while visible."""

    def __init__(self, px: int = 16, color: str = C.ACCENT):
        super().__init__()
        self.setFixedSize(px, px)
        self._angle = 0
        self._color = QColor(color)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._angle = (self._angle + 9) % 360
        self.update()

    def showEvent(self, e) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(e)

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def paintEvent(self, e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = 2.0
        r = QRectF(w, w, self.width() - 2 * w, self.height() - 2 * w)
        track = QColor(self._color)
        track.setAlpha(45)
        p.setPen(QPen(track, w))
        p.drawEllipse(r)
        pen = QPen(self._color, w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, -self._angle * 16, 100 * 16)
        p.end()


class ActionTile(QFrame):
    """A compact clickable tile: icon, title, one-line description. Keyboard activatable."""

    clicked = Signal()

    def __init__(self, icon_name: str, title: str, description: str, tooltip: str = ""):
        super().__init__()
        self.setObjectName("tile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if tooltip:
            self.setToolTip(tooltip)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(S.MD + 2, S.MD, S.MD, S.MD)
        lay.setSpacing(S.MD)
        badge = QLabel(theme.GLYPH.get(icon_name, icon_name))
        badge.setObjectName("tileBadge")
        badge.setFixedSize(32, 32)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(badge)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(title, "tileTitle", wrap=False))
        col.addWidget(label(description, "hint"))
        lay.addLayout(col, 1)
        self.title = title

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(e)


class ChoiceCard(QFrame):
    """One option of a single-choice group, shown as a selectable card."""

    picked = Signal(object)

    def __init__(self, value: Any, title: str, description: str, badge: str = ""):
        super().__init__()
        self.value = value
        self.setObjectName("choice")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(S.LG, S.MD, S.LG, S.MD)
        lay.setSpacing(S.MD)
        self._mark = QLabel()
        self._mark.setObjectName("choiceMark")
        self._mark.setFixedSize(18, 18)
        lay.addWidget(self._mark, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(S.SM)
        head.addWidget(label(title, "tileTitle", wrap=False))
        if badge:
            chip = label(badge, "choiceBadge", wrap=False)
            chip.setFixedHeight(18)
            head.addWidget(chip)
        head.addStretch(1)
        col.addLayout(head)
        col.addWidget(label(description, "hint"))
        col.addStretch(1)
        lay.addLayout(col, 1)
        self.set_selected(False)

    def set_selected(self, on: bool) -> None:
        set_prop(self, "selected", bool(on))
        set_prop(self._mark, "selected", bool(on))

    @property
    def selected(self) -> bool:
        return bool(self.property("selected"))

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.value)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.picked.emit(self.value)
        else:
            super().keyPressEvent(e)


class EmptyState(QFrame):
    """Centered icon, title, explanation and an optional action."""

    def __init__(self, icon_name: str, title: str, text: str, action: QPushButton | None = None):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S.XXXL, S.XXL, S.XXXL, S.XXL)
        lay.setSpacing(S.SM)
        g = glyph(icon_name, C.TEXT_3, 26)
        g.setMinimumWidth(0)
        g.setMaximumWidth(16777215)
        lay.addWidget(g)
        self.title = label(title, "sectionTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title)
        self.text = label(text, "hint")
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.text)  # full width so word-wrap height is computed correctly
        if action is not None:
            lay.addSpacing(S.SM)
            lay.addWidget(action, 0, Qt.AlignmentFlag.AlignHCenter)


# ----------------------------------------------------------------------------- binder
class Binder:
    """Two-way binding between widgets and Settings fields."""

    def __init__(self, get_settings: Callable[[], Any], update: Callable[..., Any],
                 on_saved: Callable[[], None] | None = None):
        self._get = get_settings
        self._update = update
        self._on_saved = on_saved or (lambda: None)
        self._items: list[tuple[str, QWidget, Callable[[Any], None]]] = []

    def _set(self, key: str, value: Any) -> None:
        self._update(**{key: value})
        self._on_saved()

    def _register(self, key: str, widget: QWidget, setter: Callable[[Any], None]) -> None:
        self._items.append((key, widget, setter))
        setter(getattr(self._get(), key))

    def check(self, key: str, text: str = "", confirm: Callable[[bool], bool] | None = None) -> QCheckBox:
        box = Toggle(text)

        def changed(state: bool) -> None:
            if confirm is not None and not confirm(state):
                box.blockSignals(True)
                box.setChecked(not state)
                box.blockSignals(False)
                return
            self._set(key, state)

        box.toggled.connect(changed)
        self._register(key, box, lambda v: box.setChecked(bool(v)))
        return box

    def combo(self, key: str, options: list[tuple[str, Any]], width: int = 220) -> QComboBox:
        box = QComboBox()
        box.setMinimumWidth(width)
        for text, value in options:
            box.addItem(text, value)
        box.currentIndexChanged.connect(lambda i: self._set(key, box.itemData(i)))

        def setter(v: Any) -> None:
            idx = box.findData(v)
            if idx >= 0:
                box.setCurrentIndex(idx)

        self._register(key, box, setter)
        return box

    def spin(self, key: str, lo: float, hi: float, step: float = 1, suffix: str = "", decimals: int = 0) -> QWidget:
        box = QDoubleSpinBox() if decimals else QSpinBox()
        if decimals:
            box.setDecimals(decimals)
        box.setRange(lo, hi)
        box.setSingleStep(step)
        box.setSuffix(suffix)
        box.setFixedWidth(110)
        box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        box.setKeyboardTracking(False)
        box.valueChanged.connect(lambda v: self._set(key, v))
        self._register(key, box, lambda v: box.setValue(v))
        return box

    def refresh(self) -> None:
        s = self._get()
        for key, widget, setter in self._items:
            widget.blockSignals(True)
            try:
                setter(getattr(s, key))
            finally:
                widget.blockSignals(False)
