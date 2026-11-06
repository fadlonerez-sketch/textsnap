"""Corner notification ("toast").

Shown without activation and never accepting focus, so the application the
user captured from keeps keyboard focus and Ctrl+V pastes right away.
A hairline at the bottom shows the time left; hovering pauses it. Repeated
events update the visible toast in place instead of stacking new ones.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QStackedLayout, QVBoxLayout, QWidget,
)

from textsnap.ui import motion, theme
from textsnap.ui.theme import C, R, S
from textsnap.ui.widgets import Spinner, set_prop

KIND_STYLE = {
    "success": ("success", C.SUCCESS),
    "info": ("info", C.ACCENT),
    "busy": ("info", C.ACCENT),
    "warning": ("warning", C.WARNING),
    "error": ("error", C.DANGER),
}
SHADOW = 16  # transparent margin around the card for its shadow


class _Countdown(QWidget):
    """2 px progress line along the bottom edge of the card."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFixedHeight(2)
        self.fraction = 0.0
        self.color = QColor(C.ACCENT)

    def set_fraction(self, f: float) -> None:
        self.fraction = max(0.0, min(1.0, f))
        self.update()

    def paintEvent(self, e) -> None:  # noqa: N802
        if self.fraction <= 0:
            return
        p = QPainter(self)
        c = QColor(self.color)
        c.setAlpha(150)
        p.fillRect(QRectF(0, 0, self.width() * self.fraction, self.height()), c)
        p.end()


class Toast(QWidget):
    WIDTH = 384

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("TextSnap notification")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW, SHADOW - 6, SHADOW, SHADOW + 4)
        self.card = QFrame(self)
        self.card.setObjectName("toastCard")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)
        col = QVBoxLayout(self.card)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(S.LG, S.MD + 2, S.SM + 2, S.MD + 2)
        row.setSpacing(S.MD)
        badge_host = QWidget()
        badge_host.setFixedSize(30, 30)
        self._badge_stack = QStackedLayout(badge_host)
        self.icon = QLabel(objectName="toastIcon")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge_stack.addWidget(self.icon)
        spin_host = QWidget()
        sh = QHBoxLayout(spin_host)
        sh.setContentsMargins(0, 0, 0, 0)
        self.spinner = Spinner(18)
        sh.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignCenter)
        self._badge_stack.addWidget(spin_host)
        row.addWidget(badge_host, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = QLabel(objectName="toastTitle")
        self.body = QLabel(objectName="toastBody")
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.PlainText)
        text.addWidget(self.title)
        text.addWidget(self.body)
        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 6, 0, 0)
        self.actions.setSpacing(6)
        self.actions.addStretch(1)
        text.addLayout(self.actions)
        row.addLayout(text, 1)
        close = QPushButton(theme.GLYPH["close"], objectName="toastClose")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("Dismiss")
        close.clicked.connect(self.dismiss)
        row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        col.addLayout(row)
        self.countdown = _Countdown(self.card)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(R.XL, 0, R.XL, 1)  # stays clear of the rounded corners
        bottom.addWidget(self.countdown)
        col.addLayout(bottom)
        self.setFixedWidth(self.WIDTH + 2 * SHADOW)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._clock = QElapsedTimer()
        self._seconds = 3.5
        self._remaining_ms = 0
        self._buttons: list[QPushButton] = []
        self._kind = "info"
        self._leaving = False

    # -- content ------------------------------------------------------------------
    def show_message(self, kind: str, title: str, body: str = "", seconds: float = 3.5,
                     actions: list[tuple[str, Callable[[], None]]] | None = None,
                     near: QRect | None = None) -> None:
        name, color = KIND_STYLE.get(kind, KIND_STYLE["info"])
        self._kind = kind
        q = QColor(color)
        if kind == "busy":
            self._badge_stack.setCurrentIndex(1)
        else:
            self._badge_stack.setCurrentIndex(0)
            self.icon.setText(theme.STATE_GLYPH.get(name, theme.GLYPH["info"]))
            set_prop(self.icon, "kind", kind if kind in KIND_STYLE else "info")
        self.title.setText(title)
        self.body.setText(body)
        self.body.setVisible(bool(body))
        for b in self._buttons:
            self.actions.removeWidget(b)
            b.deleteLater()
        self._buttons = []
        for caption, callback in actions or []:
            b = QPushButton(caption, objectName="toastAction")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, cb=callback: (self.dismiss(), cb()))
            self.actions.addWidget(b)
            self._buttons.append(b)
        self.countdown.color = q
        self.adjustSize()
        target = self._target_pos(near)
        was_visible = self.isVisible() and not self._leaving
        self._leaving = False
        self._seconds = seconds
        if was_visible:
            # Update in place: settle at the target, with a short emphasis.
            motion.stop(self, b"windowOpacity")
            self.move(target)
            self.setWindowOpacity(0.75)
            motion.animate(self, b"windowOpacity", 1.0, motion.Duration.FAST)
        else:
            self.setWindowOpacity(0.0 if not motion.reduced() else 1.0)
            self.move(target + QPoint(0, 12) if not motion.reduced() else target)
            self.show()
            motion.animate(self, b"windowOpacity", 1.0, motion.Duration.TOAST_IN)
            motion.animate(self, b"pos", target, motion.Duration.TOAST_IN, motion.Ease.OUT)
        self.raise_()
        self._start_countdown(int(seconds * 1000))

    def _target_pos(self, near: QRect | None) -> QPoint:
        screen = None
        if near is not None:
            screen = QGuiApplication.screenAt(near.center())
        screen = screen or QGuiApplication.screenAt(self.cursor().pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        return QPoint(area.right() - self.width() - 6, area.bottom() - self.height() - 4)

    # -- countdown -----------------------------------------------------------------
    def _start_countdown(self, ms: int) -> None:
        self._remaining_ms = ms
        self._timer.start(ms)
        self._clock.restart()
        if self._kind == "busy" or motion.reduced():
            motion.stop(self, "countdown")
            self.countdown.set_fraction(0.0)
            return
        self.countdown.set_fraction(1.0)
        motion.tween(self, 1.0, 0.0, ms, self.countdown.set_fraction, QEasingCurve.Type.Linear,
                     key="countdown")

    def enterEvent(self, event) -> None:  # noqa: N802
        if self._timer.isActive():
            self._remaining_ms = max(0, self._remaining_ms - self._clock.elapsed())
            self._timer.stop()
            motion.stop(self, "countdown")

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.isVisible() and not self._leaving:
            self._start_countdown(max(1500, self._remaining_ms))

    # -- leaving -------------------------------------------------------------------------
    def dismiss(self) -> None:
        self._timer.stop()
        motion.stop(self, "countdown")
        if not self.isVisible() or self._leaving:
            return
        self._leaving = True
        motion.animate(self, b"pos", self.pos() + QPoint(0, 6), motion.Duration.TOAST_OUT, motion.Ease.IN)
        motion.animate(self, b"windowOpacity", 0.0, motion.Duration.TOAST_OUT, motion.Ease.IN,
                       on_done=self._finish_hide)

    def _finish_hide(self) -> None:
        if self._leaving:
            self._leaving = False
            self.hide()

    def hide_now(self) -> None:
        self._timer.stop()
        self._leaving = False
        motion.stop(self, "countdown")
        motion.stop(self, b"windowOpacity")
        motion.stop(self, b"pos")
        self.hide()
