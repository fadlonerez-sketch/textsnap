"""Dashboard, result window, toast and tray (offscreen)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from textsnap.app.controller import AppController
from textsnap.app.models import CaptureResult
from textsnap.clipboard.clipboard import ClipboardService
from textsnap.ocr.pipeline import OcrResult
from textsnap.storage import paths
from textsnap.storage.settings import Settings, SettingsStore
from textsnap.ui.result_window import ResultWindow
from textsnap.ui.toast import Toast
from textsnap.ui.widgets import Toggle

from helpers import FakeClipboardBackend, FakeTrigger

MIXED = "הפגישה עם Microsoft תתקיים ביום שלישי\nEnglish line\nVisit https://example.com or mail a@b.co"


def record(text=MIXED, **kw):
    return CaptureResult(1, "region", OcrResult(text, 90.0, "heb+eng", "fast", 250, 10, "mixed"), **kw)


@pytest.fixture
def window(qtbot):
    w = ResultWindow(lambda: Settings())
    qtbot.addWidget(w)
    w.show_record(record(copied=True), activate=False)
    return w


def test_result_window_shows_exact_text(window):
    assert window.text() == MIXED
    assert "Copied" in window.feedback.text()
    assert "90% confidence" in window.info.text()


def test_direction_override_never_changes_text(window):
    for mode in ("rtl", "ltr", "auto"):
        window._set_direction(mode)
        assert window.text() == MIXED
    block = window.editor.document().begin()
    assert block.textDirection() == Qt.LayoutDirection.RightToLeft  # Hebrew paragraph
    assert block.next().textDirection() == Qt.LayoutDirection.LeftToRight


def test_copy_emits_edited_text(qtbot, window):
    window.editor.setPlainText("edited שלום")
    with qtbot.waitSignal(window.copy_requested) as sig:
        window.copy_btn.click()
    assert sig.args == ["edited שלום"]


def test_copy_original_after_edit(qtbot, window):
    window.editor.setPlainText("changed")
    with qtbot.waitSignal(window.copy_requested) as sig:
        window._copy_original()
    assert sig.args == [MIXED]


def test_editor_copy_is_plain_text_only(window):
    window.editor.selectAll()
    mime = window.editor.createMimeDataFromSelection()
    assert mime.hasText() and not mime.hasHtml()
    assert mime.text() == MIXED


def test_clean_keeps_content_and_is_undoable(window):
    window.editor.setPlainText("a   b\n\n\n\nc")
    window._replace_text("a b\n\nc")
    assert window.text() == "a b\n\nc"
    window.editor.undo()
    assert window.text() == "a   b\n\n\n\nc"


def test_detected_links_and_emails(window):
    labels = [window.detected_row.itemAt(i).widget().text() for i in range(window.detected_row.count())
              if window.detected_row.itemAt(i).widget()]
    assert any("https://example.com" in t for t in labels)
    assert any("a@b.co" in t for t in labels)


def test_rerun_hidden_when_not_possible(qtbot):
    w = ResultWindow(lambda: Settings())
    qtbot.addWidget(w)
    w.show_record(record(can_rerun=False), activate=False)
    assert not w.rerun_row.isVisible()


def test_rerun_request(qtbot, window):
    window.lang.setCurrentIndex(window.lang.findData("heb"))
    with qtbot.waitSignal(window.rerun_requested) as sig:
        window.rerun_btn.click()
    assert sig.args == ["heb", "fast"]


def test_expand_toggles_size(window):
    small = window.size()
    window.toggle_expanded()
    assert window.width() > small.width() and window.expand_btn.text() == "Compact"


def test_toast_never_takes_focus(qtbot):
    t = Toast()
    qtbot.addWidget(t)
    assert t.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert t.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    t.show_message("success", "Text copied", "12 characters", seconds=0.3, actions=[("View", lambda: None)])
    assert t.isVisible()
    qtbot.waitUntil(lambda: not t.isVisible(), timeout=3000)


@pytest.fixture
def controller(qtbot, isolated_data_dir):
    c = AppController(SettingsStore(paths.settings_path()), trigger=FakeTrigger(),
                      clipboard=ClipboardService(FakeClipboardBackend(), sleep=lambda s: None))
    yield c
    c.shutdown()


def test_dashboard_pages_and_bindings(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    d = Dashboard(controller)
    qtbot.addWidget(d)
    assert set(d.pages) == {"home"}  # other pages are built on first use (startup cost)
    for i in range(d.nav.count()):
        d.nav.setCurrentRow(i)
        assert d.stack.currentWidget() is d.pages[d.SECTIONS[i][0]]
    assert set(d.pages) == {"home", "capture", "keyboard", "languages", "history", "privacy", "advanced", "about"}
    assert d.stack.count() == 8
    widgets = {key: w for key, w, _setter in d.binder._items}
    magnifier = widgets["show_magnifier"]
    assert isinstance(magnifier, Toggle) and magnifier.isChecked()
    magnifier.click()
    assert SettingsStore(paths.settings_path()).load().show_magnifier is False  # persisted immediately
    controller.update_settings(show_magnifier=True)
    assert magnifier.isChecked()  # and the widget follows external changes
    hold = widgets["toast_seconds"]
    hold.setValue(6.5)
    assert SettingsStore(paths.settings_path()).load().toast_seconds == 6.5


def test_dashboard_close_hides_to_tray(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    d = Dashboard(controller, tray_available=True)
    qtbot.addWidget(d)
    d.show()
    d.close()
    assert not d.isVisible()  # hidden, application keeps running


def test_open_windows_never_veto_quitting(qtbot, controller):
    """Qt 6 quits by closing every top-level window and cancels if one refuses (tray Exit, Windows logoff).

    The dashboard hides to the tray only for the user's own title-bar close (a spontaneous event; checked
    against a real window in the manual QA notes), so a programmatic close must be accepted."""
    from PySide6.QtWidgets import QApplication
    from textsnap.ui.dashboard import Dashboard
    from textsnap.ui.toast import Toast
    d = Dashboard(controller, tray_available=True)
    qtbot.addWidget(d)
    d.show_page("home")
    t = Toast()
    t.show_message("success", "Text copied", "", actions=[("View", lambda: None)])
    qtbot.waitExposed(d)
    for window in QApplication.topLevelWindows():
        if window.isVisible():
            assert window.close(), window  # what QGuiApplication does on QEvent.Quit
    assert not d.isVisible()
    t.hide_now()


def test_keyboard_page_custom_trigger(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    d = Dashboard(controller)
    qtbot.addWidget(d)
    page = d.pages["keyboard"]
    assert page.preset.currentText() == "Spacebar (default)"
    page.preset.setCurrentIndex(page.preset.count() - 1)  # custom: starts from the current trigger
    assert page.main_key.currentData() == "Space" and not any(b.isChecked() for b in page.mod_boxes.values())
    page.mod_boxes["LCtrl"].setChecked(True)
    page.mod_boxes["LAlt"].setChecked(True)
    page.main_key.setCurrentIndex(page.main_key.findData("T"))
    page._apply_custom()
    assert controller.settings.trigger_keys == ["LCtrl", "LAlt", "T"]
    assert controller.trigger.applied[-1][1] == ["LCtrl", "LAlt", "T"]
    assert page.warnings.isVisible() or page.warnings.text()
    page.preset.setCurrentIndex(1)
    assert controller.settings.trigger_keys == ["RCtrl"]
    page.preset.setCurrentIndex(0)
    assert controller.settings.trigger_keys == ["Space"]


def test_history_page_requires_opt_in(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    d = Dashboard(controller)
    qtbot.addWidget(d)
    page = d.pages["history"]
    assert not page.list_card.isEnabled()
    page.enable_box.click()
    assert controller.settings.history_enabled and page.list_card.isEnabled()
    controller.history.add("stored text", "eng", "region")
    page.reload()
    assert page.list.count() == 1


def test_tray_menu(qtbot, controller):
    from textsnap.ui.tray import Tray
    shown = []
    tray = Tray(controller, shown.append, lambda: None)
    actions = [a.text() for a in tray.contextMenu().actions() if a.text()]
    for expected in ["Start text capture", "Capture all screens", "OCR clipboard image", "Open dashboard",
                     "Settings", "Keyboard trigger enabled", "Exit TextSnap"]:
        assert expected in actions
    tray.toggle.setChecked(False)
    assert controller.settings.trigger_enabled is False
    assert "off" in tray.toolTip()


def test_keyboard_page_shows_spacebar(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    d = Dashboard(controller)
    qtbot.addWidget(d)
    d.show()
    page = d.pages["keyboard"]
    d.show_page("keyboard")
    assert page.preset.currentText() == "Spacebar (default)"
    assert page.hold_back_row.isVisible()
    assert "release" in page.warnings.text()
    controller.apply_trigger()
    assert controller.trigger.applied[-1] == (True, ["Space"], 500) and controller.trigger.hold_back is True
    home = d.pages["home"]
    from PySide6.QtWidgets import QLabel
    assert any(w.text() == "Spacebar" for w in home.findChildren(QLabel))
    page.preset.setCurrentIndex(1)  # Right Ctrl
    assert controller.settings.trigger_keys == ["RCtrl"] and not page.hold_back_row.isVisible()
    from textsnap.storage.settings import SettingsStore
    from textsnap.storage import paths
    assert SettingsStore(paths.settings_path()).load().trigger_keys == ["RCtrl"]
