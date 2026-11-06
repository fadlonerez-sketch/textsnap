"""Main window: animated sidebar navigation plus eight sections and the welcome tour."""

from __future__ import annotations

import platform
import sys
import time
from pathlib import Path

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl, Signal, qVersion
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QSlider, QStackedWidget, QVBoxLayout,
    QWidget,
)

from textsnap import APP_NAME, __version__
from textsnap.app.controller import AppController
from textsnap.history.store import HistoryError
from textsnap.keyboard import keys as K
from textsnap.storage import paths
from textsnap.storage.settings import LANGUAGE_LABELS
from textsnap.ui import dialogs, motion, theme
from textsnap.ui.theme import C, S, T
from textsnap.ui.widgets import (
    ActionTile, Banner, Binder, Card, ChoiceCard, EmptyState, Page, Spinner, StatusPill, Toggle, button, glyph,
    hline, keycap, label, overline, row_layout,
)

# Accurate statements only: each line is backed by the implementation.
PRIVACY_POINTS = [
    ("cpu", "Recognition runs on this computer",
     "The bundled Tesseract engine reads the pixels locally. TextSnap makes no network connections and has "
     "no telemetry."),
    ("image", "Screenshots stay in memory",
     "A capture is discarded after recognition. The most recent one is kept for up to 10 minutes so Run again "
     "works, or until you clear it. Images are written to disk only if you turn on Save captured images."),
    ("clipboard", "Text goes to the clipboard",
     "History is off unless you turn it on. You can also keep results out of Windows clipboard history."),
    ("text", "Logs never contain your text",
     "Logs record events and timings - never recognised text, clipboard contents, key presses or images."),
    ("keyboard", "The keyboard hook records nothing",
     "It watches only your trigger key. With the Spacebar trigger a plain Space press is held back until the "
     "hold is decided, then re-sent in order (or dropped once the overlay opened). Turning the trigger off "
     "removes the hook."),
]
PRIVACY_TEXT = "\n".join(f"• {title}. {text}" for _i, title, text in PRIVACY_POINTS)


# ======================================================================= sidebar
class Sidebar(QFrame):
    """Grouped navigation with a sliding selection indicator.

    Exposes the small QListWidget-like API the rest of the app uses:
    ``count()``, ``currentRow()``, ``setCurrentRow()`` and ``currentRowChanged``.
    """

    currentRowChanged = Signal(int)

    def __init__(self, sections: list[tuple[str, str, str, str]]):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(224)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S.MD, S.XL, S.MD, S.LG)
        lay.setSpacing(0)
        brand = QHBoxLayout()
        brand.setContentsMargins(S.SM, 0, 0, 0)
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(28))
        brand.addWidget(logo)
        name = QLabel(APP_NAME)
        name.setFont(theme.font(T.BODY_LG + 2, QFont.Weight.DemiBold, display=True))
        brand.addWidget(name)
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addSpacing(S.XXL)

        self._items_host = QWidget()
        items = QVBoxLayout(self._items_host)
        items.setContentsMargins(0, 0, 0, 0)
        items.setSpacing(2)
        self._indicator = QWidget(self._items_host)
        self._indicator.setObjectName("navIndicator")
        self._indicator.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._marker = QWidget(self._indicator)
        self._marker.setObjectName("navMarker")
        self._marker.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._indicator.hide()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: list[QPushButton] = []
        current_group = None
        for key, text, icon_name, group in sections:
            if group != current_group:
                if current_group is not None:
                    items.addSpacing(S.MD)
                    head = overline(group)
                    head.setContentsMargins(S.MD, 0, 0, S.XS)
                    items.addWidget(head)
                current_group = group
            b = QPushButton(text.replace("&", "&&"))  # '&' would otherwise become a mnemonic underline
            b.setObjectName("navItem")
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setCheckable(True)
            b.setIcon(theme.icon(icon_name, C.TEXT_2, 16))
            b.setIconSize(QSize(16, 16))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("key", key)
            self._group.addButton(b, len(self.buttons))
            items.addWidget(b)
            self.buttons.append(b)
        self._group.idClicked.connect(self.setCurrentRow)
        lay.addWidget(self._items_host)
        lay.addStretch(1)
        self.footer = QVBoxLayout()
        self.footer.setSpacing(S.SM)
        lay.addLayout(self.footer)
        self._row = -1

    def count(self) -> int:
        return len(self.buttons)

    def currentRow(self) -> int:  # noqa: N802 - mirrors QListWidget
        return self._row

    def setCurrentRow(self, row: int) -> None:  # noqa: N802
        if not 0 <= row < len(self.buttons):
            return
        changed = row != self._row
        self._row = row
        self.buttons[row].setChecked(True)
        self._move_indicator(animated=changed and self.isVisible())
        if changed:
            self.currentRowChanged.emit(row)

    def _target(self) -> QRect:
        return self.buttons[self._row].geometry() if self._row >= 0 else QRect()

    def _move_indicator(self, animated: bool) -> None:
        target = self._target()
        if target.isEmpty():
            return
        self._indicator.show()
        self._indicator.lower()
        self._marker.setGeometry(0, (target.height() - 16) // 2, 3, 16)
        if animated and self._indicator.geometry().isValid() and not self._indicator.geometry().isEmpty():
            motion.animate(self._indicator, b"geometry", target, motion.Duration.BASE, motion.Ease.IN_OUT)
        else:
            motion.stop(self._indicator, b"geometry")
            self._indicator.setGeometry(target)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        QTimer.singleShot(0, self, lambda: self._move_indicator(animated=False))

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        QTimer.singleShot(0, self, lambda: self._move_indicator(animated=False))


# ======================================================================= main window
class _LazyPages(dict):
    """``pages[key]`` builds a page on first access; iteration only sees pages that exist."""

    def __init__(self, build):
        super().__init__()
        self._build = build

    def __missing__(self, key: str) -> Page:
        return self._build(key)


class Dashboard(QWidget):
    quit_requested = Signal()  # the user closed the window while there is no tray icon

    SECTIONS = [
        ("home", "Home", "home", "General"),
        ("capture", "Capture & results", "capture", "Settings"),
        ("keyboard", "Keyboard trigger", "keyboard", "Settings"),
        ("languages", "Languages & engine", "language", "Settings"),
        ("history", "History", "history", "Data"),
        ("privacy", "Privacy & storage", "privacy", "Data"),
        ("advanced", "Advanced", "advanced", "System"),
        ("about", "About & diagnostics", "about", "System"),
    ]

    def __init__(self, controller: AppController, tray_available: bool = True):
        super().__init__(None, Qt.WindowType.Window)
        self.c = controller
        self.tray_available = tray_available
        self.setObjectName("appRoot")
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(theme.app_icon())
        self.resize(1080, 740)
        self.setMinimumSize(900, 600)
        self.setAcceptDrops(True)
        # The window itself holds focus when it opens, so no sidebar item shows a focus ring until the
        # user presses Tab (Qt would otherwise focus the first tab-focusable child on activation).
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.binder = Binder(lambda: self.c.settings, self.c.update_settings, on_saved=self._saved)
        motion.set_reduced(controller.settings.reduce_motion)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.nav = Sidebar(self.SECTIONS)
        self.trigger_badge = StatusPill("Starting…")
        self.nav.footer.addWidget(self.trigger_badge, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(self.nav)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        # Pages are built the first time they are needed: polishing a page against the application style
        # sheet is the main cost of opening the dashboard, so startup pays only for Home.
        self.pages: dict[str, Page] = _LazyPages(self._build_page)
        for _key in self.SECTIONS:
            self.stack.addWidget(QWidget())  # placeholder, swapped for the page on first use
        self.nav.currentRowChanged.connect(self._switch)
        self.nav.setCurrentRow(0)

        controller.settings_changed.connect(lambda _s: self.refresh())
        controller.trigger_status.connect(self._trigger_status)
        self._trigger_status(controller.trigger.state, controller.trigger.message)
        self._onboarding: OnboardingDialog | None = None

    # -- navigation -----------------------------------------------------------
    def show_page(self, key: str = "home") -> None:
        for i, (k, *_rest) in enumerate(self.SECTIONS):
            if k == key:
                self.nav.setCurrentRow(i)
        appearing = not self.isVisible()
        self.show()
        if self.isMinimized():
            self.showNormal()
        if appearing:
            motion.window_fade_in(self, motion.Duration.BASE)
        self.raise_()
        self.activateWindow()

    def _build_page(self, key: str) -> Page:
        keys = [k for k, *_rest in self.SECTIONS]
        if key not in keys:
            raise KeyError(key)
        page = PAGE_CLASSES[key](self)
        page.finish()
        self.pages[key] = page
        row = keys.index(key)
        placeholder = self.stack.widget(row)
        self.stack.insertWidget(row, page)
        self.stack.removeWidget(placeholder)
        placeholder.deleteLater()
        if hasattr(page, "trigger_status"):
            page.trigger_status(self.c.trigger.state, self.c.trigger.message)
        return page

    def _switch(self, row: int) -> None:
        page = self.pages[self.SECTIONS[row][0]]
        self.stack.setCurrentWidget(page)
        page.verticalScrollBar().setValue(0)
        page.on_show()
        if self.isVisible():
            motion.fade_in(page.inner, motion.Duration.BASE)

    def current_page(self) -> Page | None:
        page = self.stack.currentWidget()
        return page if isinstance(page, Page) else None

    def _saved(self) -> None:
        page = self.current_page()
        if page is not None and self.isVisible():
            page.saved.flash()

    def refresh(self) -> None:
        motion.set_reduced(self.c.settings.reduce_motion)
        self.binder.refresh()
        for page in list(self.pages.values()):
            if hasattr(page, "refresh"):
                page.refresh()

    def _trigger_status(self, state: str, message: str) -> None:
        kind = {"active": "success", "error": "error", "disabled": "neutral"}.get(state, "neutral")
        text = {"active": "Trigger active", "error": "Trigger unavailable", "disabled": "Trigger off"}.get(
            state, "Starting…")
        self.trigger_badge.set(kind, text)
        self.trigger_badge.setToolTip(message)
        for page in list(self.pages.values()):
            if hasattr(page, "trigger_status"):
                page.trigger_status(state, message)

    def show_onboarding(self) -> None:
        if self._onboarding is not None and self._onboarding.isVisible():
            self._onboarding.raise_()
            return
        self._onboarding = OnboardingDialog(self)
        self._onboarding.finished.connect(lambda _r: self._onboarding_closed())
        self._onboarding.open()

    def _onboarding_closed(self) -> None:
        dlg, self._onboarding = self._onboarding, None
        if not self.c.settings.onboarding_done:
            self.c.update_settings(onboarding_done=True)
        if dlg is not None:
            try_now = dlg.try_now
            dlg.deleteLater()
            if try_now:
                QTimer.singleShot(120, lambda: self.c.start_capture(source="dashboard"))

    # -- window events ----------------------------------------------------------------
    def showEvent(self, e) -> None:  # noqa: N802
        dialogs.dark_title_bar(self)
        super().showEvent(e)
        if self.focusWidget() is None:
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    # The title-bar close button hides to the tray (the app keeps running; Exit is in the tray menu).
    # Programmatic closes are accepted: quitting and Windows logoff close every window and are cancelled
    # if one refuses. Without a tray this window is the app, so closing it asks to quit.
    def closeEvent(self, event) -> None:  # noqa: N802
        if self.tray_available and event.spontaneous():
            event.ignore()
            self.hide()
            return
        event.accept()
        if not self.tray_available and event.spontaneous():
            self.quit_requested.emit()

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:  # noqa: N802
        mime = e.mimeData()
        if mime.hasImage():
            from textsnap.capture.convert import qimage_to_rgb
            from textsnap.app.controller import _JobContext
            self.c.run_ocr(qimage_to_rgb(mime.imageData()), _JobContext("file", open_window=True))
            return
        for url in mime.urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if path.lower().endswith(".pdf"):
                    PdfDialog.open_for(self.c, self, path)
                else:
                    self.c.ocr_image_file(path)
                return


def _trigger_keycaps(names: list[str], large: bool = False) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for i, n in enumerate(K.ordered(names)):
        if i:
            plus = label("+", "muted", wrap=False)
            lay.addWidget(plus)
        lay.addWidget(keycap(K.KEYS[n].label, large=large))
    return lay


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


# ======================================================================= Home
class HomePage(Page):
    def __init__(self, d: Dashboard):
        super().__init__("Home", "Copy text from anything on your screen — offline, in Hebrew and English.")
        self.d = d
        c = d.c

        hero = Card(accent=True)
        hero.body.setContentsMargins(S.XXL + 4, S.XXL, S.XXL + 4, S.XXL)
        top = QHBoxLayout()
        top.setSpacing(S.XXL)
        left = QVBoxLayout()
        left.setSpacing(S.MD)
        self.gesture = QHBoxLayout()
        self.gesture.setSpacing(10)
        left.addLayout(self.gesture)
        self.gesture_hint = label("", "muted")
        left.addWidget(self.gesture_hint)
        left.addSpacing(S.XS)
        pills = QHBoxLayout()
        pills.setSpacing(S.SM)
        self.trigger_pill = StatusPill("Trigger…")
        self.engine_pill = StatusPill("OCR engine: checking…")
        self.lang_pill = StatusPill("")
        for p in (self.trigger_pill, self.engine_pill, self.lang_pill):
            pills.addWidget(p)
        pills.addStretch(1)
        left.addLayout(pills)
        top.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(8)
        right.addStretch(1)
        start = button("Capture now", "capture", "hero", "Select an area of the screen now",
                       lambda: c.start_capture(source="dashboard"))
        right.addWidget(start)
        self.start_hint = label("", "hint", wrap=False)
        self.start_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(self.start_hint)
        right.addStretch(1)
        top.addLayout(right)
        hero.add_layout(top)
        self.add(hero)

        self.section("More ways to capture")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(S.MD)
        grid.setVerticalSpacing(S.MD)
        tiles = [
            ("desktop", "All screens", "Read everything that is visible", lambda: c.capture_full_desktop("dashboard")),
            ("window", "Pick a window", "Click a window to read it", lambda: c.start_capture("window", "dashboard")),
            ("repeat", "Repeat last area", "Read the same spot again", c.repeat_last_region),
            ("image", "Image file", "PNG, JPEG, BMP, TIFF, GIF, WebP", lambda: c.ocr_image_file(parent=self)),
            ("paste", "Clipboard image", "A copied screenshot or image", c.ocr_clipboard_image),
            ("pdf", "PDF document", "Choose pages, see progress", lambda: PdfDialog.open_for(c, self)),
        ]
        self.tiles: list[ActionTile] = []
        for i, (ic, title, desc, slot) in enumerate(tiles):
            tile = ActionTile(ic, title, desc)
            tile.clicked.connect(slot)
            grid.addWidget(tile, i // 3, i % 3)
            self.tiles.append(tile)
        holder = QWidget()
        holder.setLayout(grid)
        self.add(holder)

        self.section("Recent")
        self.recent = Card()
        self.recent.body.setSpacing(S.SM)
        self.recent_body = QVBoxLayout()
        self.recent_body.setSpacing(0)
        self.recent.add_layout(self.recent_body)
        self.add(self.recent)

        links = row_layout(button("Quick tour", "sparkle", "ghost", "Show the welcome tour again",
                                  d.show_onboarding),
                           button("Privacy", "privacy", "ghost", on_click=lambda: d.show_page("privacy")),
                           button("All settings", "advanced", "ghost", on_click=lambda: d.show_page("capture")))
        lw = QWidget()
        lw.setLayout(links)
        self.add(lw)

        c.engine_status_changed.connect(self._engine)
        c.last_status_changed.connect(lambda _s: self._refresh_recent())
        c.result_ready.connect(lambda _r: self._refresh_recent())
        c.history_changed.connect(self._refresh_recent)
        if c.engine_status is not None:
            self._engine(c.engine_status)
        self.refresh()

    def _engine(self, status) -> None:
        if status.ok:
            self.engine_pill.set("success", f"OCR ready · Tesseract {status.version}")
        else:
            self.engine_pill.set("error", "OCR engine unavailable")
        self.engine_pill.setToolTip(status.summary())

    def on_show(self) -> None:
        self._refresh_recent()

    def refresh(self) -> None:
        s = self.d.c.settings
        _clear_layout(self.gesture)
        if s.trigger_enabled:
            hold = label("Hold", "h2", wrap=False)
            self.gesture.addWidget(hold)
            self.gesture.addLayout(_trigger_keycaps(s.trigger_keys, large=True))
            self.gesture.addWidget(label("to capture text", "h2", wrap=False))
            self.gesture_hint.setText(f"Hold for {s.hold_ms / 1000:.1f} s anywhere, then drag over text. "
                                      "It is copied for you — paste with Ctrl+V.")
            self.start_hint.setText(f"or hold {K.describe_trigger(s.trigger_keys)}")
        else:
            self.gesture.addWidget(label("Capture text from your screen", "h2", wrap=False))
            self.gesture_hint.setText("The keyboard trigger is off. Use Capture now or the tray menu, or turn the "
                                      "trigger on in Keyboard trigger.")
            self.start_hint.setText("or use the tray menu")
        self.gesture.addStretch(1)
        self.lang_pill.set("info", LANGUAGE_LABELS.get(s.ocr_language, s.ocr_language)
                           + (" · Thorough" if s.ocr_quality == "thorough" else ""))
        self._refresh_recent()

    def trigger_status(self, state: str, message: str) -> None:
        names = K.describe_trigger(self.d.c.settings.trigger_keys)
        kind, text = {"active": ("success", f"Trigger active · {names}"),
                      "disabled": ("neutral", "Trigger off"),
                      "error": ("error", "Trigger unavailable")}.get(state, ("neutral", "Trigger starting…"))
        self.trigger_pill.set(kind, text)
        self.trigger_pill.setToolTip(message)

    def _refresh_recent(self) -> None:
        c = self.d.c
        _clear_layout(self.recent_body)
        entries = []
        if c.settings.history_enabled and c.history.is_open:
            try:
                entries = c.history.search(limit=4)
            except HistoryError:
                entries = []
        if entries:
            for i, e in enumerate(entries):
                if i:
                    self.recent_body.addWidget(hline())
                self.recent_body.addWidget(self._recent_row(e))
            return
        if c.last_record is not None:
            rec = c.last_record
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, S.XS, 0, S.XS)
            ok = rec.result is not None and not rec.result.empty and not rec.error
            h.addWidget(glyph("success" if ok else "warning", C.SUCCESS if ok else C.WARNING, 18))
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(c.last_status))
            col.addWidget(label("History is off, so only the latest result is kept (in memory)." if
                                not c.settings.history_enabled else "Latest result", "hint"))
            h.addLayout(col, 1)
            h.addWidget(button("View result", "open", on_click=lambda: c.show_result()))
            self.recent_body.addWidget(row)
            return
        action = button("Turn on history", "history", "ghost", on_click=lambda: self.d.show_page("history")) \
            if not c.settings.history_enabled else None
        names = K.describe_trigger(c.settings.trigger_keys)
        self.recent_body.addWidget(EmptyState(
            "text", "No captures yet",
            f"Hold {names} anywhere, or click Capture now. "
            + ("Turn on History to keep a searchable list here." if not c.settings.history_enabled else ""),
            action))

    def _recent_row(self, e) -> QWidget:
        c = self.d.c
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 6, 0, 6)
        h.setSpacing(S.MD)
        h.addWidget(glyph("pin" if e.pinned else "text", C.ACCENT if e.pinned else C.TEXT_3, 16))
        col = QVBoxLayout()
        col.setSpacing(1)
        preview = label((e.title or e.preview or "(empty)")[:90], wrap=False)
        col.addWidget(preview)
        col.addWidget(label(time.strftime("%d %b, %H:%M", time.localtime(e.created_at))
                            + f" · {len(e.text)} characters", "hint"))
        h.addLayout(col, 1)
        h.addWidget(button("Copy", "copy", "ghost", "Copy this text again", lambda t=e.text: c.copy_text(t)))
        return w


# ======================================================================= Capture
class CapturePage(Page):
    def __init__(self, d: Dashboard):
        super().__init__("Capture & results", "How the selection overlay behaves and what happens after a capture.")
        b = d.binder
        cap = Card("Selection overlay", icon="region")
        cap.row("Default mode", b.combo("capture_mode", [("Region (drag)", "region"), ("Window (click)", "window"),
                                                          ("Screen (click)", "monitor"), ("All screens", "desktop"),
                                                          ("Active window (no overlay)", "active")]),
                "In the overlay, R / W / M / A switch modes and Enter repeats the last area.")
        cap.row("Magnifier", b.check("show_magnifier"), "A zoomed view beside the cursor for precise edges.")
        cap.row("Crosshair guides", b.check("show_crosshair"), "Thin guide lines through the cursor.")
        cap.row("Show selection size", b.check("show_dimensions"), "Width × height in screen pixels.")
        cap.row("Dim the screen by", b.spin("overlay_dim_percent", 10, 85, 5, " %"))
        cap.row("Minimum selection", b.spin("min_selection_px", 3, 200, 1, " px"),
                "Smaller drags show a hint and let you select again.")
        self.add(cap)

        res = Card("After a capture", icon="success")
        res.row("Copy text automatically", b.check("auto_copy"), "Recommended — the text is ready for Ctrl+V.")
        res.row("Copy cleaned text", b.check("copy_cleaned"), "Removes extra spaces and blank lines; keeps line breaks.")
        res.row("Show a confirmation", b.check("show_toast"), "A small notice in the corner that never takes focus.")
        res.row("Confirmation time", b.spin("toast_seconds", 1, 20, 0.5, " s", decimals=1))
        res.row("Open the result window every time", b.check("open_result_window"),
                "Otherwise it opens from the confirmation’s View button or the tray.")
        res.row("Keep the result window on top", b.check("result_on_top"))
        res.row("Return focus to the previous app", b.check("restore_focus"),
                "So you can paste immediately where you were working.")
        res.row("Detect QR codes", b.check("detect_qr"), "Shows a QR code’s value; links are never opened "
                                                         "automatically.")
        self.add(res)

        auto = Card("Automatic paste", icon="paste")
        auto.row("Paste automatically (Ctrl+V)", b.check("auto_paste", confirm=lambda on: self._confirm_paste(on)),
                 "Off by default. Sends one Ctrl+V to the app you captured from.")
        self.add(auto)

    def _confirm_paste(self, on: bool) -> bool:
        if not on:
            return True
        return dialogs.confirm(
            self, "Paste automatically?",
            "After each screen capture TextSnap will return focus to the window you were using and send it one "
            "Ctrl+V keystroke, pasting the recognised text at the cursor.\n\n"
            "Only turn this on if you always want the text inserted immediately.", "Turn on")


# ======================================================================= Keyboard
class KeyboardPage(Page):
    CUSTOM = "__custom__"

    def __init__(self, d: Dashboard):
        super().__init__("Keyboard trigger",
                         "Hold the trigger anywhere to open the selection overlay. A quick press keeps its normal "
                         "meaning, and pressing another key or a mouse button while holding cancels the hold.")
        self.d = d
        c = d.c
        b = d.binder

        summary = Card(accent=True)
        sl = QHBoxLayout()
        sl.setSpacing(S.LG)
        self.summary_keys = QHBoxLayout()
        self.summary_keys.setSpacing(6)
        sl.addLayout(self.summary_keys)
        self.summary_text = label("", "muted")
        sl.addWidget(self.summary_text, 1)
        self.status = StatusPill("")
        sl.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        summary.add_layout(sl)
        self.add(summary)

        main = Card("Trigger", icon="keyboard")
        main.row("Enable the keyboard trigger", b.check("trigger_enabled"),
                 "When off, the keyboard hook is removed completely.")
        self.preset = QComboBox()
        self.preset.setMinimumWidth(240)
        for text, names in K.PRESETS:
            self.preset.addItem(text, names)
        self.preset.addItem("Custom combination…", self.CUSTOM)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        main.row("Key", self.preset, "The Spacebar is the default; other keys and combinations work too.")

        self.custom = QFrame()
        self.custom.setObjectName("inset")
        cl = QVBoxLayout(self.custom)
        cl.setContentsMargins(S.LG, S.MD, S.LG, S.MD)
        cl.setSpacing(S.MD)
        cl.addWidget(label("Modifier keys", "hint"))
        mods = QGridLayout()
        mods.setHorizontalSpacing(S.LG)
        mods.setVerticalSpacing(S.SM)
        self.mod_boxes: dict[str, QCheckBox] = {}
        for i, n in enumerate(K.MODIFIER_NAMES):
            box = QCheckBox(K.KEYS[n].label)
            self.mod_boxes[n] = box
            mods.addWidget(box, i // 4, i % 4)
        cl.addLayout(mods)
        row = QHBoxLayout()
        row.setSpacing(S.SM)
        row.addWidget(label("Plus key", "hint", wrap=False))
        self.main_key = QComboBox()
        self.main_key.setMinimumWidth(160)
        self.main_key.addItem("(none)", "")
        for n in K.MAIN_KEY_NAMES:
            self.main_key.addItem(K.KEYS[n].label, n)
        row.addWidget(self.main_key)
        row.addStretch(1)
        row.addWidget(button("Use this combination", "check", "primary", on_click=self._apply_custom))
        cl.addLayout(row)
        self.custom_error = Banner("", "error")
        cl.addWidget(self.custom_error)
        main.add(self.custom)

        hold = QHBoxLayout()
        hold.setSpacing(S.MD)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(200, 3000)
        self.slider.setSingleStep(50)
        self.slider.setPageStep(100)
        self.slider.setMinimumWidth(220)
        self.hold_label = label("", "value", wrap=False)
        self.hold_label.setFixedWidth(56)
        self.hold_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider.valueChanged.connect(lambda v: self.hold_label.setText(f"{v / 1000:.2f} s"))
        self.slider.sliderReleased.connect(self._hold_changed)
        self.slider.valueChanged.connect(lambda _v: self._hold_timer.start(400))
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._hold_changed)
        hold.addWidget(self.slider, 1)
        hold.addWidget(self.hold_label)
        hw = QWidget()
        hw.setLayout(hold)
        hw.setMinimumWidth(300)
        main.row("Hold for", hw, "0.5 s is recommended. Shorter holds are easier to trigger by accident.")
        main.row("Cancel when another key or mouse button is pressed", b.check("cancel_on_other_input"),
                 "Keeps typing and shortcuts from opening the overlay.")
        self.hold_back_row = main.row(
            "Hold back the Spacebar until the hold is decided", b.check("hold_back_trigger_key"),
            "Recommended. A tap types its space when you release the key; a hold types nothing. When off, "
            "every hold first types a space (and repeats if held past your keyboard repeat delay).")
        self.warnings = Banner("", "warning")
        main.add(self.warnings)
        main.add(self._defaults_row())
        self.add(main)

        test = Card("Test the trigger", "Click Test, then hold your trigger. Nothing is captured during the test.",
                    icon="test")
        tr = QHBoxLayout()
        tr.setSpacing(S.MD)
        self.test_btn = button("Test", "play", "primary", on_click=self._start_test)
        tr.addWidget(self.test_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        tr.addWidget(self.progress, 1)
        test.add_layout(tr)
        self.test_result = label("Not tested yet.", "hint")
        test.add(self.test_result)
        self.test_banner = Banner("", "info")
        test.add(self.test_banner)
        self.add(test)
        self._anim = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._tick)
        self._armed_at = 0.0
        self._hold = 500
        c.trigger_test_event.connect(self._test_event)
        self.refresh()

    def _defaults_row(self) -> QWidget:
        w = QWidget()
        w.setLayout(row_layout(None, button("Restore recommended defaults", "refresh", "ghost",
                                            on_click=self._restore_defaults), stretch_end=False))
        return w

    def _restore_defaults(self) -> None:
        self.d.c.update_settings(trigger_enabled=True, trigger_keys=list(K.DEFAULT_TRIGGER), hold_ms=500,
                                 cancel_on_other_input=True, hold_back_trigger_key=True)
        self.saved.flash()

    def refresh(self) -> None:
        s = self.d.c.settings
        names = list(s.trigger_keys)
        idx = next((i for i in range(self.preset.count() - 1) if sorted(self.preset.itemData(i)) == sorted(names)),
                   self.preset.count() - 1)
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(idx)
        self.preset.blockSignals(False)
        self.custom.setVisible(idx == self.preset.count() - 1)
        for n, box in self.mod_boxes.items():
            box.setChecked(n in names)
        main = [n for n in names if not K.KEYS[n].modifier]
        self.main_key.setCurrentIndex(max(0, self.main_key.findData(main[0] if main else "")))
        self.slider.blockSignals(True)
        self.slider.setValue(s.hold_ms)
        self.slider.blockSignals(False)
        self.hold_label.setText(f"{s.hold_ms / 1000:.2f} s")
        self.hold_back_row.setVisible(names == ["Space"])
        w = K.conflict_warnings(names, s.hold_back_trigger_key)
        self.warnings.setText("\n".join(w) + ("\nTextSnap cannot detect every possible conflict with other apps."
                                              if w else ""))
        _clear_layout(self.summary_keys)
        self.summary_keys.addWidget(label("Hold", "sectionTitle", wrap=False))
        self.summary_keys.addLayout(_trigger_keycaps(names, large=True))
        self.summary_text.setText(f"for {s.hold_ms / 1000:.2f} s to open the selection overlay"
                                  if s.trigger_enabled else "The keyboard trigger is off.")

    def trigger_status(self, state: str, message: str) -> None:
        kind = {"active": "success", "error": "error"}.get(state, "neutral")
        self.status.set(kind, {"active": "Active", "error": "Unavailable", "disabled": "Off"}.get(state, "Starting"))
        self.status.setToolTip(message)
        if state == "error":
            self.test_banner.set("error", message)

    def _preset_changed(self, i: int) -> None:
        data = self.preset.itemData(i)
        if data == self.CUSTOM:
            self.custom.setVisible(True)
            motion.fade_in(self.custom, motion.Duration.BASE)
            return
        self.custom.setVisible(False)
        self.d.c.update_settings(trigger_keys=list(data))
        self.saved.flash()

    def _apply_custom(self) -> None:
        names = [n for n, box in self.mod_boxes.items() if box.isChecked()]
        if self.main_key.currentData():
            names.append(self.main_key.currentData())
        error = K.validate_trigger(names)
        self.custom_error.set("error", (error[0].upper() + error[1:] + ".") if error else "")
        if not error:
            self.d.c.update_settings(trigger_keys=K.ordered(names))
            self.saved.flash()

    def _hold_changed(self) -> None:
        self._hold_timer.stop()
        if self.slider.value() != self.d.c.settings.hold_ms:
            self.d.c.update_settings(hold_ms=self.slider.value())
            self.saved.flash()

    def _start_test(self) -> None:
        if not self.d.c.settings.trigger_enabled:
            self._result("Turn the keyboard trigger on first.", "warning")
            return
        self._hold = self.d.c.settings.hold_ms
        self.d.c.begin_trigger_test(20)
        self.test_btn.setEnabled(False)
        self.progress.setValue(0)
        self.test_banner.setText("")
        self.test_result.setText(f"Listening for 20 s… hold {K.describe_trigger(self.d.c.settings.trigger_keys)}.")

    def _tick(self) -> None:
        elapsed = (time.monotonic() - self._armed_at) * 1000
        self.progress.setValue(min(1000, int(1000 * elapsed / max(1, self._hold))))

    def _result(self, text: str, kind: str) -> None:
        self.test_result.setText("")
        self.test_banner.set({"ok": "success", "muted": "info"}.get(kind, kind), text)

    def _test_event(self, name: str, info: dict) -> None:
        if name == "armed":
            self._armed_at = time.monotonic()
            self._anim.start()
            self.test_result.setText("Holding…")
            self.test_banner.setText("")
        elif name == "cancelled":
            self._anim.stop()
            self.progress.setValue(0)
            reason = info.get("reason")
            if reason == "released_early":
                self._result(f"Released after {info.get('held_ms', 0) / 1000:.2f} s — hold a little longer "
                             f"({self._hold / 1000:.2f} s).", "warning")
            elif reason in ("other_input", "other_keys_held"):
                self._result("Cancelled because another key or mouse button was pressed (this keeps shortcuts "
                             "working).", "warning")
            else:
                self._result("Cancelled.", "warning")
        elif name == "activated":
            self._anim.stop()
            self.progress.setValue(1000)
            self._result("Trigger detected — the selection overlay would open now.", "success")
            self.d.c.end_trigger_test()
        elif name == "test_ended":
            self._anim.stop()
            self.test_btn.setEnabled(True)
            if self.test_result.text().startswith("Listening"):
                self._result("No trigger detected during the test.", "warning")

    def hideEvent(self, e) -> None:  # noqa: N802
        self._anim.stop()  # never animate a hidden page
        super().hideEvent(e)


# ======================================================================= Languages
class LanguagesPage(Page):
    DESCRIPTIONS = {
        "heb+eng": ("Recommended for Hebrew and English, including both in one line.", "Recommended"),
        "heb": ("Hebrew text only (digits and punctuation included).", ""),
        "eng": ("English text only. Slightly faster and more accurate for pure English.", ""),
        "auto": ("Reads with both models, then re-reads with a single model when only one script is found and "
                 "keeps the better result. Best effort: it chooses only between Hebrew and English.", ""),
    }

    def __init__(self, d: Dashboard):
        super().__init__("Languages & engine", "All recognition happens on this computer.")
        self.d = d
        c = d.c
        self.section("Recognition language")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(S.MD)
        self.choices: list[ChoiceCard] = []
        for i, code in enumerate(("heb+eng", "heb", "eng", "auto")):
            desc, badge = self.DESCRIPTIONS[code]
            card = ChoiceCard(code, LANGUAGE_LABELS[code], desc, badge)
            card.picked.connect(self._pick)
            grid.addWidget(card, i // 2, i % 2)
            self.choices.append(card)
        gw = QWidget()
        gw.setLayout(grid)
        self.add(gw)

        quality = Card("Accuracy and speed", icon="sparkle")
        quality.row("Processing", d.binder.combo("ocr_quality", [("Fast (one pass)", "fast"),
                                                                 ("Thorough (several image variants)", "thorough")]),
                    "Thorough is slower but helps with small, low-contrast or colored text.")
        quality.row("Models", d.binder.combo("ocr_model", [("Accurate (tessdata_best)", "best"),
                                                           ("Fast (tessdata_fast)", "fast")]))
        self.add(quality)

        eng = Card("OCR engine", icon="cpu")
        head = QHBoxLayout()
        self.engine_pill = StatusPill("Checking…")
        head.addWidget(self.engine_pill)
        head.addStretch(1)
        self.spinner = Spinner(16)
        self.spinner.hide()
        head.addWidget(self.spinner)
        head.addWidget(button("Check again", "refresh", "ghost", on_click=self._check))
        self.selftest_btn = button("Run a recognition test", "test", tooltip="Recognises built-in sample images in "
                                                                             "Hebrew and English",
                                   on_click=self._self_test)
        head.addWidget(self.selftest_btn)
        eng.add_layout(head)
        box = QFrame()
        box.setObjectName("codeBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(S.MD, 10, S.MD, 10)
        self.engine_info = label("Checking…", "mono")
        self.engine_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bl.addWidget(self.engine_info)
        eng.add(box)
        self.selftest_out = Banner("", "success")
        eng.add(self.selftest_out)
        self.add(eng)

        custom = Card("Another Tesseract installation", "Optional. Choose a folder that contains tesseract.exe and "
                      "a tessdata folder (either tessdata\\best and tessdata\\fast, or the language files directly in "
                      "tessdata). Hebrew needs heb.traineddata and English needs eng.traineddata.", icon="folder")
        folder_row = QHBoxLayout()
        folder_row.setSpacing(S.SM)
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Using the bundled engine")
        self.folder.setReadOnly(True)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(button("Choose…", "folder", on_click=self._choose_folder))
        folder_row.addWidget(button("Use bundled", "back", "ghost",
                                    on_click=lambda: (c.update_settings(tesseract_dir=""), self.saved.flash())))
        custom.add_layout(folder_row)
        self.add(custom)

        c.engine_status_changed.connect(self._engine)
        c.self_check_done.connect(self._self_test_done)
        if c.engine_status is not None:
            self._engine(c.engine_status)
        self.refresh()

    def _pick(self, code: str) -> None:
        if code != self.d.c.settings.ocr_language:
            self.d.c.update_settings(ocr_language=code)
            self.saved.flash()

    def refresh(self) -> None:
        s = self.d.c.settings
        for card in self.choices:
            card.set_selected(card.value == s.ocr_language)
        self.folder.setText(s.tesseract_dir)

    def _check(self) -> None:
        self.spinner.show()
        self.engine_pill.set("neutral", "Checking…")
        self.d.c.refresh_engine_status()

    def _engine(self, st) -> None:
        self.spinner.hide()
        if not st.ok:
            self.engine_pill.set("error", "Unavailable")
            self.engine_info.setText(st.error)
        else:
            self.engine_pill.set("success", f"Ready · Tesseract {st.version}")
            langs = "\n".join(f"{model:<5} {', '.join(st.languages.get(model, []) or ['none'])}"
                              for model in ("best", "fast"))
            self.engine_info.setText(f"{st.folder}\n{langs}")

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a Tesseract folder")
        if folder:
            if not (Path(folder) / "tesseract.exe").exists():
                dialogs.inform(self, "Not a Tesseract folder", "That folder does not contain tesseract.exe.",
                               "warning")
                return
            self.d.c.update_settings(tesseract_dir=folder)
            self.saved.flash()

    def _self_test(self) -> None:
        self.selftest_btn.setEnabled(False)
        self.spinner.show()
        self.selftest_out.set("info", "Recognising sample images…")
        self.d.c.run_self_check()

    def _self_test_done(self, results) -> None:
        self.selftest_btn.setEnabled(True)
        self.spinner.hide()
        if isinstance(results, str):
            self.selftest_out.set("error", results)
            return
        lines = [f"{r['name']}: {r['accuracy']:.0%} character accuracy in {r['ms']:.0f} ms"
                 + ("" if r["passed"] else "  (below the expected accuracy)") for r in results]
        self.selftest_out.set("success" if all(r["passed"] for r in results) else "warning", "\n".join(lines))


# ======================================================================= History
class HistoryPage(Page):
    def __init__(self, d: Dashboard):
        super().__init__("History", "Optional and off by default. When on, recognised text is stored only on this "
                                    "computer. Images are never stored.")
        self.d = d
        c = d.c
        top = Card()
        self.enable_box = Toggle()
        self.enable_box.toggled.connect(self._toggle)
        top.row("Keep a history of recognised text", self.enable_box,
                "Search, copy again, pin and export earlier results.")
        self.retention = d.binder.combo("history_retention_days", [("1 day", 1), ("7 days", 7), ("30 days", 30),
                                                                    ("90 days", 90), ("1 year", 365), ("Forever", 0)],
                                        width=160)
        top.row("Keep entries for", self.retention, "Pinned entries and snippets are kept until you delete them.")
        self.add(top)

        self.list_card = Card()
        bar = QHBoxLayout()
        bar.setSpacing(S.SM)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search history…")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(theme.icon("search", C.TEXT_3), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _t: self._reload_timer.start(200))
        bar.addWidget(self.search, 1)
        self.filter = QComboBox()
        self.filter.addItem("All entries", False)
        self.filter.addItem("Pinned & snippets", True)
        self.filter.setMinimumWidth(170)
        self.filter.currentIndexChanged.connect(lambda _i: self.reload())
        bar.addWidget(self.filter)
        self.list_card.add_layout(bar)
        self.list = QListWidget(objectName="historyList")
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda _i: self._open())
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.setMinimumHeight(280)
        self.list.setIconSize(QSize(16, 16))
        self.list_card.add(self.list)
        self.empty = EmptyState("history", "", "")
        self.list_card.add(self.empty)
        actions = QHBoxLayout()
        actions.setSpacing(S.SM)
        self.action_buttons = []
        for text, ic, slot in [("Copy", "copy", self._copy), ("Open", "open", self._open),
                               ("Pin / unpin", "pin", self._pin), ("Delete", "delete", self._delete),
                               ("Export…", "export", self._export)]:
            btn = button(text, ic, "ghost", on_click=slot)
            actions.addWidget(btn)
            self.action_buttons.append(btn)
        actions.addStretch(1)
        self.count = label("", "hint", wrap=False)
        actions.addWidget(self.count)
        self.list_card.add_layout(actions)
        self.add(self.list_card)

        danger = Card("Danger zone", "These actions cannot be undone.", kind="danger", icon="warning")
        clear = button("Clear history", "delete", "danger", "Deletes all entries except pinned ones and snippets",
                       self._clear)
        clear_pinned = button("Clear pinned", "unpin", "danger", "Deletes pinned entries and snippets",
                              self._clear_pinned)
        danger.add_layout(row_layout(clear, clear_pinned))
        self.danger = danger
        self.add(danger)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self.reload)
        c.history_changed.connect(self.reload)
        self.refresh()

    def on_show(self) -> None:
        self.reload()

    def refresh(self) -> None:
        on = self.d.c.settings.history_enabled
        self.enable_box.blockSignals(True)
        self.enable_box.setChecked(on)
        self.enable_box.blockSignals(False)
        self.list_card.setEnabled(on)
        self.retention.setEnabled(on)
        self.danger.setEnabled(on)
        self.reload()

    def _toggle(self, on: bool) -> None:
        c = self.d.c
        if on:
            c.update_settings(history_enabled=True)
            self.saved.flash()
            return
        choice = dialogs.choose(self, "Turn off history?", "New captures will no longer be stored.",
                                [("Cancel", None, ""), ("Keep entries", "keep", ""),
                                 ("Delete all entries", "delete", "danger")])
        if choice == "delete":
            c.disable_history(delete_entries=True)
            self.saved.flash()
        elif choice == "keep":
            c.disable_history(delete_entries=False)
            self.saved.flash()
        else:
            self.refresh()

    def reload(self) -> None:
        self.list.clear()
        c = self.d.c
        entries, total, error = [], 0, ""
        if c.settings.history_enabled and c.history.is_open:
            try:
                entries = c.history.search(self.search.text(), pinned_only=bool(self.filter.currentData()))
                total = c.history.count()
            except HistoryError as exc:
                error = str(exc)
        pin_icon = theme.icon("pin", C.ACCENT)
        text_icon = theme.icon("text", C.TEXT_3)
        for e in entries:
            stamp = time.strftime("%d %b %Y, %H:%M", time.localtime(e.created_at))
            head = e.title or e.preview or "(empty)"
            meta = f"{stamp} · {len(e.text)} characters" + (
                f" · {LANGUAGE_LABELS.get(e.language, e.language)}" if e.language else "")
            item = QListWidgetItem(pin_icon if e.pinned else text_icon, f"{head}\n{meta}")
            item.setData(Qt.ItemDataRole.UserRole, e.id)
            item.setToolTip(e.text[:500])
            self.list.addItem(item)
        has = bool(entries)
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        if not c.settings.history_enabled:
            self.empty.title.setText("History is off")
            self.empty.text.setText("Turn it on above to keep a searchable list of recognised text on this computer.")
        elif error or not c.history.is_open:
            self.empty.title.setText("History is unavailable")
            self.empty.text.setText(error or "The history database could not be opened. See the log for details.")
        elif self.search.text().strip() or self.filter.currentData():
            self.empty.title.setText("No matching entries")
            self.empty.text.setText("Try a different search or show all entries.")
        else:
            self.empty.title.setText("Nothing here yet")
            self.empty.text.setText("Captures will appear here as soon as you make one.")
        self.count.setText(f"{len(entries)} shown · {total} stored" if c.settings.history_enabled else "")
        self._selection_changed()

    def _selection_changed(self) -> None:
        any_selected = bool(self.list.selectedItems())
        for b in self.action_buttons:
            b.setEnabled(any_selected)

    def _selected_ids(self) -> list[int]:
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]

    def _entry(self):
        ids = self._selected_ids()
        return self.d.c.history.get(ids[0]) if ids else None

    def _copy(self) -> None:
        e = self._entry()
        if e:
            self.d.c.copy_text(e.text)

    def _open(self) -> None:
        e = self._entry()
        if e:
            from textsnap.app.models import CaptureResult
            from textsnap.ocr.pipeline import OcrResult
            from textsnap.ocr.text import text_direction
            res = OcrResult(e.text, None, e.language or self.d.c.settings.ocr_language, "fast", 0,
                            len(e.text.split()), text_direction(e.text))
            self.d.c.show_result(CaptureResult(0, e.source or "history", res, can_rerun=False,
                                               file_name=e.title))

    def _pin(self) -> None:
        for e in [self.d.c.history.get(i) for i in self._selected_ids()]:
            if e:
                self.d.c.history.set_pinned(e.id, not e.pinned)
        self.reload()

    def _delete(self) -> None:
        ids = self._selected_ids()
        if ids and dialogs.confirm(self, "Delete entries?", f"Delete {len(ids)} selected entr"
                                   f"{'y' if len(ids) == 1 else 'ies'}? This cannot be undone.", "Delete",
                                   danger=True):
            for i in ids:
                self.d.c.history.delete(i)
            self.reload()

    def _export(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export history", str(Path.home() / "Documents" /
                                                                          "TextSnap history.txt"), "Text (*.txt)")
        if path:
            try:
                n = self.d.c.history.export(ids, Path(path))
                dialogs.inform(self, "Export complete", f"Exported {n} entr{'y' if n == 1 else 'ies'} to\n{path}",
                               "success")
            except (OSError, HistoryError) as exc:
                dialogs.inform(self, "Export failed", str(exc), "error")

    def _clear(self) -> None:
        if dialogs.confirm(self, "Clear history?", "Delete all history entries except pinned ones and snippets? "
                           "This cannot be undone.", "Clear history", danger=True):
            self.d.c.history.clear(include_pinned=False)
            self.reload()

    def _clear_pinned(self) -> None:
        if dialogs.confirm(self, "Clear pinned entries?", "Delete all pinned entries and snippets? This cannot be "
                           "undone.", "Clear pinned", danger=True):
            self.d.c.history.clear_pinned()
            self.reload()


# ======================================================================= Privacy
class PrivacyPage(Page):
    def __init__(self, d: Dashboard):
        super().__init__("Privacy & storage", "What TextSnap does with your screen and your text.")
        self.d = d
        b = d.binder
        info = Card()
        info.body.setSpacing(S.MD)
        for i, (ic, title, text) in enumerate(PRIVACY_POINTS):
            if i:
                info.add(hline())
            r = QHBoxLayout()
            r.setSpacing(S.MD)
            r.addWidget(glyph(ic, C.ACCENT, 18), 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(label(title, "strong"))
            col.addWidget(label(text, "hint"))
            r.addLayout(col, 1)
            info.add_layout(r)
        self.add(info)

        shots = Card("Captured images", icon="image")
        shots.row("Save captured images", b.check("save_captures", confirm=self._confirm_save),
                  "Off by default. When on, every capture is saved as a PNG in the folder below.")
        row = QHBoxLayout()
        row.setSpacing(S.SM)
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        self.folder.setPlaceholderText("No folder chosen")
        row.addWidget(self.folder, 1)
        row.addWidget(button("Choose folder…", "folder", on_click=self._choose))
        shots.add_layout(row)
        self.add(shots)

        clip = Card("Clipboard", icon="clipboard")
        clip.row("Keep results out of clipboard history and cloud sync", b.check("exclude_from_clipboard_history"),
                 "Uses Windows’ standard opt-out so Win+V history and cloud clipboard skip TextSnap text.")
        self.add(clip)

        storage = Card("Storage", icon="folder")
        loc = QHBoxLayout()
        loc.setSpacing(S.SM)
        path_field = QLineEdit(str(paths.data_dir()))
        path_field.setReadOnly(True)
        loc.addWidget(path_field, 1)
        loc.addWidget(button("Open", "open", on_click=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(paths.data_dir())))))
        storage.add(label("Settings, history and logs are stored in", "hint"))
        storage.add_layout(loc)
        storage.row("Diagnostics log detail", b.combo("log_level", [("Warnings only", "WARNING"),
                                                                    ("Normal", "INFO"), ("Detailed", "DEBUG")],
                                                      width=170),
                    "Logs never contain recognised text.")
        storage.add(QWidget())
        storage.add_layout(row_layout(
            button("Open log folder", "folder", "ghost",
                   on_click=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.logs_dir())))),
            button("Delete old logs", "delete", "ghost", on_click=self._delete_logs)))
        self.add(storage)

        startup = Card("Startup", icon="power")
        self.autostart = Toggle()
        self.autostart.toggled.connect(self._autostart)
        startup.row("Start TextSnap when I sign in to Windows", self.autostart,
                    "Off by default. Adds one entry named “TextSnap” under your account’s Run key "
                    "(HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run). Turning it off removes it.")
        self.add(startup)

        reset = Card("Danger zone", "Restores every setting to its default. History entries are not deleted.",
                     kind="danger", icon="warning")
        reset.add_layout(row_layout(button("Reset all settings", "refresh", "danger", on_click=self._reset)))
        self.add(reset)
        self.refresh()

    def refresh(self) -> None:
        s = self.d.c.settings
        self.folder.setText(s.save_captures_dir)
        self.autostart.blockSignals(True)
        try:
            self.autostart.setChecked(self.d.c.startup.is_enabled())
        except OSError:
            self.autostart.setChecked(False)
        self.autostart.blockSignals(False)

    def _choose(self) -> bool:
        folder = QFileDialog.getExistingDirectory(self, "Folder for saved captures",
                                                  self.d.c.settings.save_captures_dir or str(Path.home() / "Pictures"))
        if folder:
            self.d.c.update_settings(save_captures_dir=folder)
            self.saved.flash()
            return True
        return False

    def _confirm_save(self, on: bool) -> bool:
        if not on:
            return True
        if not self.d.c.settings.save_captures_dir and not self._choose():
            return False
        folder = self.d.c.settings.save_captures_dir
        return dialogs.confirm(self, "Save captured images?",
                               f"Every capture will be saved as a PNG file in:\n{folder}\n\n"
                               "Captures can contain sensitive information.", "Turn on", kind="warning")

    def _autostart(self, on: bool) -> None:
        c = self.d.c
        try:
            if on:
                if not dialogs.confirm(
                        self, "Start with Windows?",
                        "TextSnap will add an entry named “TextSnap” to your user account’s startup "
                        f"list so it starts in the tray when you sign in:\n\n{c.startup.command}\n\n"
                        "You can turn this off here at any time.", "Turn on"):
                    self.refresh()
                    return
                c.startup.enable()
            else:
                c.startup.disable()
            c.update_settings(start_with_windows=c.startup.is_enabled())
            self.saved.flash()
        except OSError as exc:
            dialogs.inform(self, "Startup setting not changed", f"The startup entry could not be changed:\n{exc}",
                           "error")
        self.refresh()

    def _delete_logs(self) -> None:
        removed = 0
        for p in paths.logs_dir().glob("textsnap.log.*"):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        dialogs.inform(self, "Old logs deleted", f"Deleted {removed} old log file(s). The current log stays open.",
                       "success")

    def _reset(self) -> None:
        if dialogs.confirm(self, "Reset all settings?", "Every setting returns to its default. History entries "
                           "are not deleted.", "Reset settings", danger=True):
            self.d.c.reset_settings()
            self.saved.flash()


# ======================================================================= Advanced
class AdvancedPage(Page):
    def __init__(self, d: Dashboard):
        super().__init__("Advanced", "Fine-tuning for unusual captures and accessibility. The defaults suit most "
                                     "screens.")
        b = d.binder
        ocr = Card("Recognition", icon="text")
        ocr.row("Image preparation", b.combo("preprocess", [("Automatic (recommended)", "auto"),
                                                            ("Light (invert + upscale only)", "light"),
                                                            ("Off (raw pixels)", "off")]))
        ocr.row("Page layout", b.combo("ocr_layout", [("Automatic", "auto"), ("Single block", "block"),
                                                      ("Single line", "line"), ("Sparse text", "sparse"),
                                                      ("Columns / complex layout", "columns")]),
                "Use Columns for multi-column pages; Sparse for scattered labels.")
        ocr.row("Time limit per recognition", b.spin("ocr_timeout_s", 3, 180, 1, " s"))
        ocr.row("Correct mixed Hebrew/English words", b.check("fix_mixed_script"),
                "Re-reads words that look like misread Hebrew (or English) with the other model.")
        ocr.row("Remove invisible direction marks", b.check("strip_bidi_marks"),
                "Tesseract adds LRM/RLM marks around English inside Hebrew; they are invisible but break searches.")
        ocr.row("Keep line breaks", b.check("preserve_line_breaks"), "Off joins wrapped lines into paragraphs.")
        self.add(ocr)

        access = Card("Motion & accessibility", icon="sparkle")
        access.row("Reduce motion", b.check("reduce_motion"),
                   "Turns off non-essential animation (page transitions, fades, the capture flash).")
        self.system_note = Banner("", "info")
        access.add(self.system_note)
        self.add(access)

        kb = Card("Keyboard", icon="keyboard")
        kb.row("Respond to synthesized key presses", b.check("accept_injected_keys"),
               "Needed for remote desktop, macro tools and on-screen keyboards.")
        self.add(kb)
        web = Card("Web search", icon="search")
        self.search = QLineEdit(d.c.settings.search_url)
        self.search.setMinimumWidth(320)
        self.search.editingFinished.connect(lambda: (d.c.update_settings(search_url=self.search.text().strip()),
                                                     self.saved.flash()))
        web.row("Search address", self.search, "{query} is replaced by the text. Used only when you click Search.")
        self.add(web)
        self.refresh()

    def refresh(self) -> None:
        self.system_note.set("info", "" if motion.system_animations_enabled() else
                             "Windows animation effects are turned off, so TextSnap already keeps motion to a "
                             "minimum.")


# ======================================================================= About
class AboutPage(Page):
    def __init__(self, d: Dashboard):
        super().__init__("About & diagnostics")
        self.d = d
        about = Card()
        h = QHBoxLayout()
        h.setSpacing(S.LG)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(56))
        h.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addWidget(label(APP_NAME, "h2"))
        col.addWidget(label(f"Version {__version__} · Offline OCR for Hebrew and English", "muted"))
        col.addWidget(label("Hold a key, drag over the screen, paste the text.", "hint"))
        h.addLayout(col, 1)
        about.add_layout(h)
        about.add_layout(row_layout(button("Quick tour", "sparkle", "ghost", on_click=d.show_onboarding),
                                    button("Third-party notices", "info", "ghost", on_click=self._notices)))
        self.add(about)
        diag = Card("Diagnostics", "Contains no recognised text. Safe to share when reporting a problem.",
                    icon="info")
        self.text = QPlainTextEdit()
        self.text.setObjectName("mono")
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(280)
        diag.add(self.text)
        self.copy_btn = button("Copy diagnostics", "copy", on_click=self._copy)
        diag.add_layout(row_layout(self.copy_btn, button("Open log folder", "folder", "ghost",
                                                         on_click=lambda: QDesktopServices.openUrl(
                                                             QUrl.fromLocalFile(str(paths.logs_dir()))))))
        self.add(diag)

    def on_show(self) -> None:
        self.text.setPlainText(diagnostics(self.d.c))

    def _copy(self) -> None:
        if self.d.c.copy_text(self.text.toPlainText()):
            self.copy_btn.setText("Copied")
            self.copy_btn.setIcon(theme.icon("check", C.SUCCESS))
            QTimer.singleShot(1600, self.copy_btn, lambda: (self.copy_btn.setText("Copy diagnostics"),
                                                              self.copy_btn.setIcon(theme.icon("copy", C.TEXT_2))))

    def _notices(self) -> None:
        path = paths.resource_root() / "THIRD_PARTY_NOTICES.md"
        dlg = dialogs.Dialog(self, "Third-party notices", "Components bundled with TextSnap and their licenses.",
                             "info")
        dlg.setMaximumWidth(900)
        dlg.resize(780, 560)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setMinimumHeight(380)
        view.setPlainText(path.read_text(encoding="utf-8") if path.exists() else "Notices file not found.")
        dlg.extra.addWidget(view)
        dlg.add_button("Close", True, "primary", default=True)
        dlg.run()


PAGE_CLASSES = {"home": HomePage, "capture": CapturePage, "keyboard": KeyboardPage, "languages": LanguagesPage,
                "history": HistoryPage, "privacy": PrivacyPage, "advanced": AdvancedPage, "about": AboutPage}


def diagnostics(c: AppController) -> str:
    from textsnap.capture.screen import current_monitors
    lines = [f"{APP_NAME} {__version__}", f"Python {sys.version.split()[0]} · Qt {qVersion()} · "
             f"PySide6 {PYSIDE_VERSION}", f"Windows {platform.version()} ({platform.machine()})",
             f"Frozen build: {paths.is_frozen()}", f"Data folder: {paths.data_dir()}", ""]
    st = c.engine_status
    lines.append(f"OCR engine: {st.summary() if st else 'not checked yet'}")
    if st and st.ok:
        for model in ("best", "fast"):
            lines.append(f"  {model}: {', '.join(st.languages.get(model, []))}")
    lines.append(f"  folder: {c.engine.folder}")
    lines.append("")
    lines.append(f"Trigger: {c.trigger.state} — {c.trigger.message}")
    hook = c.trigger.hook
    lines.append(f"  keyboard hook installed: {bool(hook and getattr(hook, 'hooks_installed', False))}")
    try:
        import ctypes
        u = ctypes.windll.user32
        aware = u.GetAwarenessFromDpiAwarenessContext(u.GetThreadDpiAwarenessContext())
        lines.append(f"  DPI awareness: {['unaware', 'system', 'per-monitor'][aware] if 0 <= aware <= 2 else aware}")
    except Exception:
        pass
    lines.append(f"  reduced motion: {motion.reduced()} (setting {c.settings.reduce_motion}, Windows animations "
                 f"{'on' if motion.system_animations_enabled() else 'off'})")
    lines.append("")
    try:
        for m in current_monitors():
            p, g = m.physical, m.logical
            lines.append(f"Display {m.index + 1}{' (primary)' if m.primary else ''}: {p.w}x{p.h} at ({p.x}, {p.y}) "
                         f"physical, {m.scale_percent}% scale, logical {g.w}x{g.h} at ({g.x}, {g.y})")
    except Exception as exc:
        lines.append(f"Displays: unavailable ({exc})")
    s = c.settings
    lines += ["", f"Language {s.ocr_language}, quality {s.ocr_quality}, model {s.ocr_model}, layout {s.ocr_layout}, "
                  f"preprocess {s.preprocess}",
              f"History {'on' if s.history_enabled else 'off'}, save captures {'on' if s.save_captures else 'off'}, "
              f"auto copy {'on' if s.auto_copy else 'off'}, auto paste {'on' if s.auto_paste else 'off'}"]
    return "\n".join(lines)


# ======================================================================= welcome tour
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


# ======================================================================= PDF dialog
class PdfDialog(QDialog):
    _open: "PdfDialog | None" = None

    @classmethod
    def open_for(cls, c: AppController, parent: QWidget | None = None, path: str | None = None) -> "PdfDialog":
        """One PDF dialog at a time; it deletes itself (and its connections) when closed."""
        if cls._open is not None:
            cls._open.raise_()
            cls._open.activateWindow()
            if path:
                cls._open._load(path)
            return cls._open
        dlg = cls(c, parent, path)
        cls._open = dlg
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.destroyed.connect(lambda *_: setattr(cls, "_open", None))
        dlg.show()
        return dlg

    def __init__(self, c: AppController, parent: QWidget | None = None, path: str | None = None):
        super().__init__(parent)
        self.c = c
        self.setObjectName("appRoot")
        self.setWindowTitle("Recognise a PDF")
        self.setWindowIcon(theme.app_icon())
        self.setMinimumWidth(560)
        self.job = 0
        self.pages = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(S.XXL, S.XXL, S.XXL, S.XL)
        lay.setSpacing(S.MD)
        head = QHBoxLayout()
        head.setSpacing(S.MD)
        head.addWidget(glyph("pdf", C.ACCENT, 22))
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label("Recognise a PDF", "sectionTitle"))
        titles.addWidget(label("Scanned pages are read with OCR; pages with their own text can use it directly.",
                               "hint"))
        head.addLayout(titles, 1)
        lay.addLayout(head)
        row = QHBoxLayout()
        row.setSpacing(S.SM)
        self.path = QLineEdit(path or "")
        self.path.setReadOnly(True)
        self.path.setPlaceholderText("Choose a PDF file")
        row.addWidget(self.path, 1)
        row.addWidget(button("Choose…", "folder", on_click=self._choose))
        lay.addLayout(row)
        self.info = label("", "hint")
        lay.addWidget(self.info)
        pr = QHBoxLayout()
        pr.setSpacing(S.SM)
        pr.addWidget(label("Pages", wrap=False))
        self.range = QLineEdit()
        self.range.setPlaceholderText("All pages (or e.g. 1-3, 5)")
        pr.addWidget(self.range, 1)
        lay.addLayout(pr)
        self.embedded = QCheckBox("Use the PDF’s own text when a page has it (faster, exact)")
        self.embedded.setChecked(True)
        lay.addWidget(self.embedded)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        lay.addWidget(self.progress)
        self.error = Banner("", "error")
        lay.addWidget(self.error)
        bb = QHBoxLayout()
        bb.addStretch(1)
        self.cancel = button("Close", variant="ghost", on_click=self._cancel)
        bb.addWidget(self.cancel)
        self.start = button("Recognise", "play", "primary", on_click=self._start)
        bb.addWidget(self.start)
        lay.addLayout(bb)
        c.pdf_progress.connect(self._progress)
        c.result_ready.connect(self._done)
        c.busy_changed.connect(self._busy)
        self._connected = True
        if path:
            self._load(path)

    def closeEvent(self, e) -> None:  # noqa: N802
        self._disconnect()
        super().closeEvent(e)

    def done(self, r: int) -> None:
        self._disconnect()
        super().done(r)

    def _disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        for sig, slot in ((self.c.pdf_progress, self._progress), (self.c.result_ready, self._done),
                          (self.c.busy_changed, self._busy)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def showEvent(self, e) -> None:  # noqa: N802
        dialogs.dark_title_bar(self)
        motion.window_fade_in(self, motion.Duration.FAST)
        super().showEvent(e)

    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a PDF", str(Path.home() / "Documents"), "PDF (*.pdf)")
        if path:
            self._load(path)

    def _load(self, path: str) -> None:
        from textsnap.ocr.documents import DocumentError, PdfDocument
        self.path.setText(path)
        try:
            doc = PdfDocument(path)
            self.pages = len(doc)
            doc.close()
            self.info.setText(f"{self.pages} page{'s' if self.pages != 1 else ''}")
            self.error.setText("")
        except DocumentError as exc:
            self.pages = 0
            self.error.setText(str(exc))

    def _start(self) -> None:
        from textsnap.ocr.documents import parse_page_range
        if not self.pages:
            self.error.setText("Choose a readable PDF first.")
            return
        try:
            pages = parse_page_range(self.range.text(), self.pages)
        except ValueError as exc:
            self.error.setText(str(exc)[0].upper() + str(exc)[1:] + ".")
            return
        self.error.setText("")
        self.progress.setRange(0, len(pages))
        self.progress.setValue(0)
        self.start.setEnabled(False)
        self.cancel.setText("Cancel")
        self.job = self.c.ocr_pdf(self.path.text(), pages, self.embedded.isChecked())

    def _progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.info.setText(f"Page {min(done + 1, total)} of {total}…" if done < total else "Finishing…")

    def _busy(self, busy: bool) -> None:
        if not busy and self.job:
            self.start.setEnabled(True)
            self.cancel.setText("Close")
            self.job = 0

    def _done(self, record) -> None:
        if record.source == "pdf":
            self.accept()

    def _cancel(self) -> None:
        if self.job:
            self.c.cancel_job(self.job)
            self.job = 0
            self.start.setEnabled(True)
            self.cancel.setText("Close")
            self.info.setText("Cancelled.")
        else:
            self.reject()
