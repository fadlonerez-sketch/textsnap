"""First-run welcome tour (shown once; available later from Home/About)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout

from textsnap.keyboard import keys as K
from textsnap.ui import dialogs, motion, theme
from textsnap.ui.theme import C, S
from textsnap.ui.widgets import Banner, button, glyph, label

if TYPE_CHECKING:
    from textsnap.ui.dashboard import Dashboard


class OnboardingDialog(QDialog):
    """A brief, skippable first-run introduction (shown once; available later from Home/About)."""

    STEPS = [
        ("keyboard", "Hold the trigger", "Hold {trigger} for {hold} s anywhere. The screen dims and freezes."),
        ("region", "Drag over text", "Release the mouse to read it. Esc or a right-click cancels."),
        ("paste", "Paste anywhere", "The text is already on the clipboard — press Ctrl+V."),
    ]

    def __init__(self, dashboard: Dashboard):
        super().__init__(dashboard)
        self.setObjectName("appRoot")
        self.setWindowTitle("Welcome to TextSnap")
        self.setWindowIcon(theme.app_icon())
        self.setModal(True)
        self.setMinimumWidth(720)
        self.try_now = False
        s = dashboard.c.settings
        root = QVBoxLayout(self)
        root.setContentsMargins(S.XXXL, S.XXXL, S.XXXL, S.XXL)
        root.setSpacing(S.LG)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(48))
        root.addWidget(logo)
        root.addWidget(label("Copy text from anything on your screen", "pageTitle"))
        root.addWidget(label("TextSnap reads text from any part of your screen — apps, images, videos, "
                             "error dialogs — and puts it on your clipboard. Hebrew and English, fully "
                             "offline.", "muted"))
        root.addSpacing(S.SM)
        steps = QHBoxLayout()
        steps.setSpacing(S.MD)
        self.step_cards: list[QFrame] = []
        trigger = K.describe_trigger(s.trigger_keys) if s.trigger_enabled else "the trigger"
        for n, (ic, title, text) in enumerate(self.STEPS, 1):
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(S.LG, S.LG, S.LG, S.LG)
            cl.setSpacing(S.SM)
            top = QHBoxLayout()
            num = QLabel(str(n), objectName="stepNumber")
            num.setFixedSize(24, 24)
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            top.addWidget(num)
            top.addStretch(1)
            top.addWidget(glyph(ic, C.TEXT_3, 18))
            cl.addLayout(top)
            t = label(title, "sectionTitle")
            cl.addWidget(t)
            cl.addWidget(label(text.format(trigger=trigger, hold=f"{s.hold_ms / 1000:.1f}"), "hint"))
            cl.addStretch(1)
            steps.addWidget(card, 1)
            self.step_cards.append(card)
        root.addLayout(steps)
        privacy = Banner("Everything stays on this PC: recognition is local, screenshots are not saved, and "
                         "history is off unless you turn it on.", "info")
        root.addWidget(privacy)
        root.addWidget(label("You can change the trigger, languages and everything else in the sidebar at any "
                             "time.", "hint"))
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        skip = button("Skip", variant="ghost", on_click=self.reject)
        buttons.addWidget(skip)
        self.try_btn = button("Try it now", "capture", "primary", "Close this tour and start a capture",
                              self._try)
        buttons.addWidget(self.try_btn)
        self.got_it = button("Got it", variant="", on_click=self.accept)
        buttons.addWidget(self.got_it)
        root.addLayout(buttons)

    def _try(self) -> None:
        self.try_now = True
        self.accept()

    def showEvent(self, e) -> None:  # noqa: N802
        dialogs.dark_title_bar(self)
        motion.window_fade_in(self, motion.Duration.SLOW)
        for i, card in enumerate(self.step_cards):
            QTimer.singleShot(60 * i, card, lambda w=card: motion.fade_in(w, motion.Duration.SLOW))  # dropped if closed
        self.try_btn.setFocus()
        super().showEvent(e)
