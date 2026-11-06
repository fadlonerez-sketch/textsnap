"""Floating result window: view, edit, copy, re-run and save recognised text.

Text is shown exactly as recognised (logical order). Each paragraph's
direction is decided by Qt's bidi algorithm from its first strong
character, so Hebrew paragraphs render right-to-left and English ones
left-to-right; the direction override only changes the display.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QTextEdit, QToolButton, QVBoxLayout,
    QWidget,
)

from textsnap.app.models import CaptureResult
from textsnap.ocr import text as tx
from textsnap.storage.settings import LANGUAGE_CHOICES, LANGUAGE_LABELS
from textsnap.ui import dialogs, motion, theme
from textsnap.ui.theme import C, S, T
from textsnap.ui.widgets import button, set_prop

PARAGRAPH_SEPARATOR = " "
SOURCE_ICON = {"region": "region", "window": "window", "monitor": "monitor", "desktop": "desktop",
               "repeat": "repeat", "active": "window", "clipboard": "paste", "file": "image", "pdf": "pdf"}


def tool(text: str, tip: str, icon: str | None = None) -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    if icon:
        b.setIcon(theme.icon(icon, C.TEXT_2, 16))
        b.setIconSize(QSize(16, 16))
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if text
                             else Qt.ToolButtonStyle.ToolButtonIconOnly)
    else:
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    return b


class TextEditor(QTextEdit):
    """Plain-text editor that right-aligns RTL paragraphs (QPlainTextEdit does not).

    Copy/drag always produce plain Unicode text only, never HTML.
    """

    def __init__(self):
        super().__init__()
        self.setAcceptRichText(False)

    def createMimeDataFromSelection(self) -> QMimeData:  # noqa: N802
        mime = QMimeData()
        # Qt uses U+2029 as the paragraph separator inside selections.
        mime.setText(self.textCursor().selectedText().replace(PARAGRAPH_SEPARATOR, "\n"))
        return mime


class ResultWindow(QWidget):
    copy_requested = Signal(str)
    rerun_requested = Signal(str, str)  # language, quality
    snippet_requested = Signal(str, str)  # text, title
    search_requested = Signal(str)
    save_dir_changed = Signal(str)
    cleared = Signal()

    COMPACT = QSize(640, 440)
    LARGE = QSize(1000, 720)

    def __init__(self, settings_provider):
        super().__init__(None, Qt.WindowType.Window)
        self.setObjectName("appRoot")
        self.setWindowTitle("TextSnap — Result")
        self.setWindowIcon(theme.app_icon())
        self._settings = settings_provider
        self._record: CaptureResult | None = None
        self._expanded = False
        self.resize(self.COMPACT)
        self.setMinimumSize(460, 320)

        root = QVBoxLayout(self)
        root.setContentsMargins(S.XL, S.LG, S.XL, S.LG)
        root.setSpacing(S.MD)

        # header: source, metadata, status
        header = QHBoxLayout()
        header.setSpacing(S.MD)
        self.source_icon = QLabel(objectName="sourceBadge")
        self.source_icon.setFixedSize(32, 32)
        self.source_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.source_icon)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.heading = QLabel(objectName="sectionTitle")
        titles.addWidget(self.heading)
        self.info = QLabel(objectName="subtle")
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        titles.addWidget(self.info)
        header.addLayout(titles, 1)
        self.feedback = QLabel(objectName="statusChip")
        self.feedback.setFixedHeight(24)  # pill: Qt drops a corner radius larger than half the height
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        header.addWidget(self.feedback, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(header)

        # toolbar
        bar = QHBoxLayout()
        bar.setSpacing(S.XS)
        self.copy_btn = button("Copy", "copy", "primary", "Copy the text as shown (including your edits)  "
                                                          "Ctrl+Shift+C", self._copy_current)
        self.copy_btn.setMinimumWidth(96)
        bar.addWidget(self.copy_btn)
        bar.addSpacing(S.XS)
        more_copy = tool("Copy as", "Other copy formats", "more")
        more_copy.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more_copy)
        menu.addAction(theme.icon("clean"), "Cleaned text (extra spaces removed)",
                       lambda: self._emit_copy(tx.clean_text(self.text())))
        menu.addAction("Trimmed (no leading/trailing whitespace)", lambda: self._emit_copy(self.text().strip()))
        menu.addAction("Joined paragraphs (no line wraps)", lambda: self._emit_copy(tx.join_lines(self.text())))
        menu.addAction("Original recognised text", self._copy_original)
        menu.addAction("Selection only", self._copy_selection)
        more_copy.setMenu(menu)
        bar.addWidget(more_copy)
        clean = tool("Clean", "Remove excess spaces and blank lines in the editor (keeps every line and character)",
                     "clean")
        clean.clicked.connect(lambda: self._replace_text(tx.clean_text(self.text())))
        bar.addWidget(clean)
        save = tool("Save", "Save as a .txt file  Ctrl+S", "save")
        save.clicked.connect(self._save)
        bar.addWidget(save)
        bar.addStretch(1)
        self.expand_btn = tool("Expand", "Open in a larger editor", "expand")
        self.expand_btn.clicked.connect(self.toggle_expanded)
        bar.addWidget(self.expand_btn)
        more = tool("", "More actions", "more")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(more)
        m.addAction("Select all", lambda: (self.editor.setFocus(), self.editor.selectAll()))
        m.addAction(theme.icon("pin"), "Save as snippet…", self._snippet)
        m.addAction(theme.icon("search"), "Search the web for this text", self._search)
        m.addSeparator()
        self.dir_menu = m.addMenu("Text direction")
        for caption, mode in (("Automatic (per paragraph)", "auto"), ("Right to left", "rtl"),
                              ("Left to right", "ltr")):
            self.dir_menu.addAction(caption, lambda md=mode: self._set_direction(md))
        m.addSeparator()
        m.addAction(theme.icon("clear"), "Clear", self._clear)
        more.setMenu(m)
        bar.addWidget(more)
        root.addLayout(bar)

        # editor
        self.editor = TextEditor()
        self.editor.setPlaceholderText("Recognised text appears here.")
        self.editor.setFont(theme.font(T.BODY_LG))
        self.editor.document().setDocumentMargin(10)
        root.addWidget(self.editor, 1)

        self.detected = QFrame()
        self.detected_row = QHBoxLayout(self.detected)
        self.detected_row.setContentsMargins(0, 0, 0, 0)
        self.detected_row.setSpacing(S.SM)
        root.addWidget(self.detected)

        # run again
        rerun = QHBoxLayout()
        rerun.setContentsMargins(0, 0, 0, 0)
        rerun.setSpacing(S.SM)
        rerun.addWidget(QLabel("Run again with", objectName="subtle"))
        self.lang = QComboBox()
        for code in LANGUAGE_CHOICES:
            self.lang.addItem(LANGUAGE_LABELS[code], code)
        self.lang.setMinimumWidth(190)
        rerun.addWidget(self.lang)
        self.quality = QComboBox()
        self.quality.addItem("Fast", "fast")
        self.quality.addItem("Thorough", "thorough")
        self.quality.setToolTip("Thorough tries several image preparations and keeps the best result")
        self.quality.setMinimumWidth(120)
        rerun.addWidget(self.quality)
        self.rerun_btn = button("Run again", "refresh", "", "Recognise the same capture again with these options",
                                self._rerun)
        rerun.addWidget(self.rerun_btn)
        rerun.addStretch(1)
        self.rerun_row = QWidget()
        self.rerun_row.setLayout(rerun)
        root.addWidget(self.rerun_row)

        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(lambda: self.feedback.setText(""))
        self._copied_timer = QTimer(self)
        self._copied_timer.setSingleShot(True)
        self._copied_timer.timeout.connect(self._reset_copy_button)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self._copy_current)
        QShortcut(QKeySequence("Ctrl+S"), self, self._save)
        QShortcut(QKeySequence("Esc"), self, self.close)

    # -- content ---------------------------------------------------------------
    def text(self) -> str:
        return self.editor.toPlainText()

    @property
    def record(self) -> CaptureResult | None:
        return self._record

    def show_record(self, record: CaptureResult, activate: bool = True) -> None:
        self._record = record
        doc = self.editor.document()
        doc.setUndoRedoEnabled(False)  # the initial formatting is not an undo step
        self.editor.setPlainText(record.text)
        self._set_direction("auto")
        doc.setUndoRedoEnabled(True)
        s = self._settings()
        language = record.result.language if record.result else s.ocr_language
        idx = self.lang.findData(s.ocr_language if language not in LANGUAGE_CHOICES else language)
        self.lang.setCurrentIndex(max(0, idx))
        self.quality.setCurrentIndex(max(0, self.quality.findData(s.ocr_quality)))
        self.rerun_row.setVisible(record.can_rerun)
        self.source_icon.setText(theme.GLYPH[SOURCE_ICON.get(record.source, "text")])
        self.heading.setText(record.source_label)
        self._update_info()
        self._update_detected()
        if record.error:
            self._set_feedback("error", record.error, 0)
        elif record.copy_error:
            self._set_feedback("error", record.copy_error, 0)
        elif record.copied:
            self._set_feedback("ok", "Copied to clipboard", 4000)
        elif record.result is not None and record.result.empty:
            self._set_feedback("warning", "No text found", 0)
        else:
            self.feedback.setText("")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(s.result_on_top))
        appearing = not self.isVisible()
        if appearing:
            self._place()
        self.show()
        if appearing:
            motion.window_fade_in(self, motion.Duration.BASE)
        if activate:
            self.raise_()
            self.activateWindow()

    def showEvent(self, e) -> None:  # noqa: N802
        dialogs.dark_title_bar(self)
        super().showEvent(e)

    def _set_feedback(self, kind: str, text: str, ms: int) -> None:
        set_prop(self.feedback, "kind", kind if kind in ("ok", "error", "warning") else "neutral")
        self.feedback.setText(text)
        self.feedback.setToolTip(text)
        self.feedback.setVisible(bool(text))
        if ms:
            self._feedback_timer.start(ms)
        else:
            self._feedback_timer.stop()

    def _update_info(self) -> None:
        r = self._record
        if r is None or r.result is None:
            self.info.setText("")
            return
        res = r.result
        parts = [LANGUAGE_LABELS.get(res.language, res.language)]
        if res.confidence is not None:
            parts.append(f"{res.confidence:.0f}% confidence")
        parts.append(f"{len(res.text)} characters")
        if res.duration_ms:
            parts.append(f"{res.duration_ms / 1000:.2f} s")
        if res.quality == "thorough":
            parts.append("thorough")
        self.info.setText(" · ".join(parts))
        self.info.setToolTip("\n".join(res.notes))

    def _update_detected(self) -> None:
        while self.detected_row.count():
            item = self.detected_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        text = self.text()
        items: list[QPushButton] = []
        for url in tx.find_urls(text)[:4]:
            b = button(self._short(url), "link", "ghost", f"Open {url} in your browser (asks first)",
                       lambda u=url: self._open_url(u))
            items.append(b)
        for email in tx.find_emails(text)[:3]:
            b = button(f"Copy {email}", "mail", "ghost", "Copy this e-mail address", lambda e=email: self._emit_copy(e))
            items.append(b)
        for value in (self._record.qr if self._record else [])[:3]:
            b = button(f"QR: {self._short(value)}", "qr", "ghost", value)
            qr_menu = QMenu(b)
            qr_menu.addAction("Copy QR value", lambda v=value: self._emit_copy(v))
            if tx.find_urls(value):
                qr_menu.addAction("Open link…", lambda v=tx.find_urls(value)[0]: self._open_url(v))
            b.setMenu(qr_menu)
            items.append(b)
        for w in items:
            w.setObjectName("chip")
            self.detected_row.addWidget(w)
        self.detected_row.addStretch(1)
        self.detected.setVisible(bool(items))

    @staticmethod
    def _short(s: str, n: int = 38) -> str:
        return s if len(s) <= n else s[: n - 1] + "…"

    def _place(self) -> None:
        screen = QGuiApplication.screenAt(self.cursor().pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        size = self.LARGE if self._expanded else self.COMPACT
        self.resize(size)
        self.move(area.center().x() - size.width() // 2, area.center().y() - size.height() // 2)

    def toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self.expand_btn.setText("Compact" if self._expanded else "Expand")
        self.expand_btn.setIcon(theme.icon("collapse" if self._expanded else "expand", C.TEXT_2))
        self._place()

    def _set_direction(self, mode: str, cursor: QTextCursor | None = None) -> None:
        """Display direction only: block formats change, the text never does.

        Pass ``cursor`` to apply it inside an existing edit block (one undo step).
        """
        direction = {"auto": Qt.LayoutDirection.LayoutDirectionAuto, "rtl": Qt.LayoutDirection.RightToLeft,
                     "ltr": Qt.LayoutDirection.LeftToRight}[mode]
        fmt = QTextBlockFormat()
        fmt.setLayoutDirection(direction)
        fmt.setAlignment(Qt.AlignmentFlag.AlignLeading)
        fmt.setBottomMargin(3)
        fmt.setLineHeight(118, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        c = cursor or QTextCursor(self.editor.document())
        c.select(QTextCursor.SelectionType.Document)
        c.mergeBlockFormat(fmt)

    # -- actions -----------------------------------------------------------------
    def _emit_copy(self, text: str) -> None:
        if text:
            self.copy_requested.emit(text)

    def _copy_current(self) -> None:
        self._emit_copy(self.text())

    def _copy_original(self) -> None:
        if self._record is not None:
            self._emit_copy(self._record.text)

    def _copy_selection(self) -> None:
        # QTextEdit uses U+2029 as paragraph separator in selections.
        self._emit_copy(self.editor.textCursor().selectedText().replace(PARAGRAPH_SEPARATOR, "\n"))

    def copy_feedback(self, ok: bool, message: str) -> None:
        self._set_feedback("ok" if ok else "error", message, 4000)
        if ok and message.startswith("Copied"):
            self.copy_btn.setText(" Copied")
            self.copy_btn.setIcon(theme.icon("check", C.ON_ACCENT))
            self._copied_timer.start(1600)

    def _reset_copy_button(self) -> None:
        self.copy_btn.setText(" Copy")
        self.copy_btn.setIcon(theme.icon("copy", C.ON_ACCENT))

    def _replace_text(self, text: str) -> None:
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text)
        self._set_direction("auto", cursor)
        cursor.endEditBlock()  # one undo step

    def _rerun(self) -> None:
        self._set_feedback("info", "Recognising…", 0)
        self.rerun_requested.emit(self.lang.currentData(), self.quality.currentData())

    def busy(self, busy: bool) -> None:
        self.rerun_btn.setEnabled(not busy and bool(self._record and self._record.can_rerun))

    def _save(self) -> None:
        s = self._settings()
        start = Path(s.last_save_dir) if s.last_save_dir else Path.home() / "Documents"
        path, _ = QFileDialog.getSaveFileName(self, "Save text", str(start / "TextSnap.txt"), "Text files (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(self.text(), encoding="utf-8")
        except OSError as exc:
            dialogs.inform(self, "Save failed", f"The file could not be saved:\n{exc}", "error")
            return
        self.copy_feedback(True, f"Saved {Path(path).name}")
        self.save_dir_changed.emit(str(Path(path).parent))

    def _snippet(self) -> None:
        text = self.text().strip()
        if not text:
            return
        default = text.splitlines()[0][:40]
        title = dialogs.prompt(self, "Save as snippet", "Snippets are pinned in History so you can reuse them.",
                               default)
        if title is not None:
            self.snippet_requested.emit(text, title or default)

    def _search(self) -> None:
        text = self.editor.textCursor().selectedText().replace(PARAGRAPH_SEPARATOR, " ").strip() or self.text().strip()
        if text:
            self.search_requested.emit(text)

    def _open_url(self, url: str) -> None:
        if dialogs.confirm(self, "Open this link?", f"It opens in your default browser:\n{url}", "Open link"):
            QDesktopServices.openUrl(QUrl(url))

    def _clear(self) -> None:
        self.editor.clear()
        self._record = None
        self.info.setText("")
        self.heading.setText("Cleared")
        self._set_feedback("", "", 0)
        self._update_detected()
        self.cleared.emit()
