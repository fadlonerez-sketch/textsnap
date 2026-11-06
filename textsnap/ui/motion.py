"""Motion language: durations, easing and safe reusable animations.

Principles
* Motion confirms cause and effect; it never delays work. Input stays live
  while anything animates, and capture/OCR never wait for an animation.
* Short and decelerating: things arrive quickly and settle (OutCubic).
* One animation per (object, property): starting a new one stops the old one,
  so rapid clicks never stack or fight.
* Animations are children of their target, stop when it hides and are
  deleted when they finish - nothing keeps running for hidden windows.
* Reduced motion (TextSnap setting, or Windows' "Show animations" turned off)
  replaces every transition with its end state.
"""

from __future__ import annotations

import ctypes
from typing import Any, Callable

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QObject, QPoint, QPropertyAnimation, QVariantAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget


class Duration:
    FAST = 120  # hover-sized feedback, toggles, dismissals
    BASE = 180  # page and panel transitions
    SLOW = 260  # first appearance, completion feedback
    TOAST_IN = 220
    TOAST_OUT = 160


class Ease:
    OUT = QEasingCurve.Type.OutCubic  # entrances and most transitions
    IN_OUT = QEasingCurve.Type.InOutCubic  # movement between two places (nav indicator)
    IN = QEasingCurve.Type.InCubic  # exits


_user_reduced = False


def set_reduced(enabled: bool) -> None:
    global _user_reduced
    _user_reduced = bool(enabled)


def system_animations_enabled() -> bool:
    """Windows Settings > Accessibility > Visual effects > Animation effects."""
    try:
        value = ctypes.c_int(1)
        spi_getclientareaanimation = 0x1042
        if ctypes.windll.user32.SystemParametersInfoW(spi_getclientareaanimation, 0, ctypes.byref(value), 0):
            return bool(value.value)
    except (AttributeError, OSError):
        pass
    return True


def reduced() -> bool:
    return _user_reduced or not system_animations_enabled()


def scaled(ms: int) -> int:
    return 0 if reduced() else ms


_running: dict[tuple[int, bytes], QAbstractAnimation] = {}


def _forget(key: tuple[int, bytes], anim: QAbstractAnimation) -> None:
    if _running.get(key) is anim:  # never evict a newer animation of the same property
        del _running[key]


def animate(target: QObject, prop: bytes, end: Any, duration: int = Duration.BASE,
            easing: QEasingCurve.Type = Ease.OUT, start: Any = None,
            on_done: Callable[[], None] | None = None) -> QPropertyAnimation | None:
    """Animate a Qt property, replacing any running animation of the same property."""
    key = (id(target), prop)
    previous = _running.pop(key, None)
    if previous is not None:
        previous.stop()
    ms = scaled(duration)
    if ms <= 0:
        target.setProperty(prop.decode(), end)
        if on_done:
            on_done()
        return None
    anim = QPropertyAnimation(target, prop, target)
    anim.setDuration(ms)
    anim.setEasingCurve(easing)
    if start is not None:
        anim.setStartValue(start)
    anim.setEndValue(end)
    anim.finished.connect(lambda: _forget(key, anim))
    anim.destroyed.connect(lambda *_: _forget(key, anim))  # target deleted mid-animation
    if on_done:
        anim.finished.connect(on_done)
    _running[key] = anim
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


def tween(owner: QObject, start: float, end: float, duration: int, on_value: Callable[[float], None],
          easing: QEasingCurve.Type = Ease.OUT, on_done: Callable[[], None] | None = None,
          key: str = "tween") -> QVariantAnimation | None:
    """Animate a plain number (for custom-painted widgets)."""
    k = (id(owner), key.encode())
    previous = _running.pop(k, None)
    if previous is not None:
        previous.stop()
    ms = scaled(duration)
    if ms <= 0:
        on_value(end)
        if on_done:
            on_done()
        return None
    anim = QVariantAnimation(owner)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(ms)
    anim.setEasingCurve(easing)
    anim.valueChanged.connect(lambda v: on_value(float(v)))
    anim.finished.connect(lambda: _forget(k, anim))
    anim.destroyed.connect(lambda *_: _forget(k, anim))
    if on_done:
        anim.finished.connect(on_done)
    _running[k] = anim
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return anim


def stop(owner: QObject, key: str | bytes = "tween") -> None:
    k = (id(owner), key if isinstance(key, bytes) else key.encode())
    anim = _running.pop(k, None)
    if anim is not None:
        anim.stop()


def fade_in(widget: QWidget, duration: int = Duration.BASE, rise: int = 0) -> None:
    """Fade (and optionally rise) a child widget into place.

    The opacity effect is removed when done, so the widget renders normally
    afterwards (graphics effects cost a pixmap round-trip on every paint).
    """
    if reduced():
        widget.setGraphicsEffect(None)
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    def finish() -> None:
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    animate(effect, b"opacity", 1.0, duration, Ease.OUT, start=0.0, on_done=finish)
    if rise:
        end = widget.pos()
        animate(widget, b"pos", end, duration, Ease.OUT, start=end + QPoint(0, rise))


def window_fade_in(window: QWidget, duration: int = Duration.BASE) -> None:
    if reduced():
        window.setWindowOpacity(1.0)
        return
    window.setWindowOpacity(0.0)
    animate(window, b"windowOpacity", 1.0, duration, Ease.OUT, start=0.0)


def window_fade_out(window: QWidget, duration: int = Duration.FAST, on_done: Callable[[], None] | None = None) -> None:
    animate(window, b"windowOpacity", 0.0, duration, Ease.IN, on_done=on_done)


def running_count() -> int:
    """Animations currently alive (used by tests to prove nothing keeps running)."""
    return sum(1 for a in _running.values() if a.state() == QAbstractAnimation.State.Running)
