"""Recognise a PDF: page range, progress and cancel (one dialog at a time)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit, QProgressBar, QVBoxLayout, QWidget

from textsnap.app.controller import AppController
from textsnap.ui import dialogs, motion, theme
from textsnap.ui.theme import C, S
from textsnap.ui.widgets import Banner, button, glyph, label


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
