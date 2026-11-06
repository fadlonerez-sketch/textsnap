"""Design system and motion: components, animations, onboarding, dialogs (offscreen)."""

from __future__ import annotations

import gc
import json
import weakref

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRect, Qt, QTimer, QVariantAnimation
from PySide6.QtWidgets import QPushButton, QWidget

from textsnap.app.controller import AppController
from textsnap.clipboard.clipboard import ClipboardService
from textsnap.storage import paths
from textsnap.storage.settings import Settings, SettingsStore
from textsnap.ui import dialogs, motion, theme
from textsnap.ui.widgets import Banner, SavedIndicator, Spinner, Toggle, button

from helpers import FakeClipboardBackend, FakeTrigger


@pytest.fixture(autouse=True)
def full_motion():
    motion.set_reduced(False)
    yield
    motion.set_reduced(False)


@pytest.fixture
def controller(qtbot, isolated_data_dir):
    c = AppController(SettingsStore(paths.settings_path()), trigger=FakeTrigger(),
                      clipboard=ClipboardService(FakeClipboardBackend(), sleep=lambda s: None))
    yield c
    c.shutdown()


# ----------------------------------------------------------------- tokens & primitives
def test_stylesheet_is_built_from_tokens(qapp):
    qss = theme.stylesheet()
    for token in (theme.C.ACCENT, theme.C.BG, theme.C.DANGER, theme.C.BORDER):
        assert token in qss
    assert "letter-spacing" not in qss  # unsupported in QSS


def test_icons_come_from_one_font_family(qapp):
    ic = theme.icon("copy")
    assert not ic.isNull()
    assert theme.T.icons() in ("Segoe Fluent Icons", "Segoe MDL2 Assets")


def test_buttons_take_focus_from_keyboard_only(qapp):
    b = button("Copy", "copy", "primary")
    assert b.focusPolicy() == Qt.FocusPolicy.TabFocus
    assert b.text().strip() == "Copy" and not b.icon().isNull()


def test_banner_kinds_and_visibility(qapp):
    b = Banner("", "warning")
    assert b.isHidden() and b.text() == ""  # an empty banner takes no space
    b.set("error", "Something failed")
    assert b.kind == "error" and b.text() == "Something failed" and not b.isHidden()
    assert b.property("kind") == "error" and b._icon.property("kind") == "error"
    assert 'QFrame#banner[kind="error"]' in theme.stylesheet()


def test_styles_live_only_in_the_theme():
    """Components switch object names/properties; per-widget style sheets would bypass the design system."""
    import pathlib
    ui = pathlib.Path(theme.__file__).parent
    offenders = [p.name for p in ui.glob("*.py") if p.name != "theme.py" and "setStyleSheet(" in p.read_text("utf-8")]
    assert offenders == []


# ----------------------------------------------------------------- motion
def test_reduced_motion_jumps_to_end_state(qapp):
    motion.set_reduced(True)
    w = QWidget()
    done = []
    assert motion.animate(w, b"windowOpacity", 0.25, on_done=lambda: done.append(1)) is None
    assert w.windowOpacity() == pytest.approx(0.25, abs=0.01) and done == [1]
    values = []
    assert motion.tween(w, 0.0, 1.0, 300, values.append) is None
    assert values == [1.0]


def test_new_animation_replaces_running_one(qtbot):
    w = QWidget()
    first = motion.animate(w, b"windowOpacity", 0.0, 1000, start=1.0)
    assert first is not None
    second = motion.animate(w, b"windowOpacity", 1.0, 100)
    assert motion.running_count() >= 1
    qtbot.waitUntil(lambda: motion.running_count() == 0, timeout=2000)
    assert w.windowOpacity() == pytest.approx(1.0, abs=0.01)
    assert second is not first


def test_animations_end_and_are_released(qtbot):
    owners = [QObject() for _ in range(5)]
    for o in owners:
        motion.tween(o, 0.0, 1.0, 60, lambda v: None)
    qtbot.waitUntil(lambda: motion.running_count() == 0, timeout=2000)
    assert not motion._running


def test_toggle_animates_and_settles(qtbot):
    t = Toggle()
    qtbot.addWidget(t)
    t.show()
    t.click()
    assert t.isChecked()
    qtbot.waitUntil(lambda: t._pos == pytest.approx(1.0), timeout=1000)
    t.blockSignals(True)
    t.setChecked(False)  # programmatic refresh jumps without animating
    t.blockSignals(False)
    assert t._pos == 0.0


def _flush_deletes():
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_animation_never_owns_its_widget(qtbot):
    """Regression for the full-run abort: the knob tween held Toggle._set_pos strongly, so an animation
    could hold the last reference to its own parent. Deleting the (stopped) animation later then freed
    the toggle from inside the animation's destructor - a double delete that aborted Qt."""
    t = Toggle()
    t.show()
    t.click()  # knob animation running, a child of the toggle
    assert t.findChildren(QVariantAnimation)
    ref = weakref.ref(t)
    del t
    gc.collect()
    assert ref() is None  # freed right here (with its animation), never from inside the animation
    _flush_deletes()
    qtbot.wait(motion.Duration.FAST + 50)  # the event loop survives the animation's would-be ticks


def test_fade_in_removes_its_effect_after_the_signal(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    child = QWidget(host)
    host.show()
    motion.fade_in(child, 40)
    assert child.graphicsEffect() is not None
    qtbot.waitUntil(lambda: child.graphicsEffect() is None, timeout=2000)
    assert motion.running_count() == 0


def test_shutdown_releases_the_controller(qtbot, isolated_data_dir):
    """Toast actions and result-window lambdas capture the controller; held by Qt connections, that cycle is
    invisible to Python's GC. shutdown() must break it, or every controller (and its windows) leaks and is
    later destroyed at an arbitrary moment."""
    c = AppController(SettingsStore(paths.settings_path()), trigger=FakeTrigger(),
                      clipboard=ClipboardService(FakeClipboardBackend(), sleep=lambda s: None))
    c._toast("info", "Text recognised", "3 characters", actions=[("Copy", lambda: c.copy_text("abc"))])
    c.ensure_result_window()
    c.shutdown()
    ref = weakref.ref(c)
    del c
    _flush_deletes()
    assert ref() is None


def test_spinner_timer_only_runs_while_visible(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    s = Spinner()
    s.setParent(host)
    host.show()
    assert s.active
    s.hide()
    assert not s.active


def test_saved_indicator_fades_out(qtbot):
    ind = SavedIndicator()
    qtbot.addWidget(ind)
    ind._timer.setInterval(10)
    ind.flash()
    assert ind.isVisible() and ind._timer.isActive()
    qtbot.waitUntil(lambda: not ind.isVisible(), timeout=3000)


# ----------------------------------------------------------------- dashboard
def test_sidebar_indicator_follows_selection(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    motion.set_reduced(True)  # end state immediately
    d = Dashboard(controller)
    qtbot.addWidget(d)
    d.show()
    qtbot.waitExposed(d)
    for row in (3, 6, 0):
        d.nav.setCurrentRow(row)
        qtbot.waitUntil(lambda: d.nav._indicator.geometry() == d.nav.buttons[row].geometry(), timeout=1000)
        assert d.nav.buttons[row].isChecked() and d.stack.currentIndex() == row
    assert "&" not in d.nav.buttons[1].text().replace("&&", "")  # '&' escaped, no mnemonic underline


def test_no_focus_ring_when_the_dashboard_opens(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    d = Dashboard(controller)
    qtbot.addWidget(d)
    d.show_page("keyboard")
    qtbot.waitExposed(d)
    d.activateWindow()
    qtbot.wait(50)
    assert not any(b.hasFocus() for b in d.nav.buttons)  # rings appear only after Tab


def test_pills_are_tall_enough_for_their_radius(qapp):
    """Qt draws square corners when a radius exceeds half the height."""
    from textsnap.ui.result_window import ResultWindow
    from textsnap.storage.settings import Settings
    from textsnap.ui.widgets import ChoiceCard, StatusPill
    assert SavedIndicator().height() >= 24 and StatusPill("x").height() >= 26
    assert ResultWindow(lambda: Settings()).feedback.height() >= 24
    card = ChoiceCard(1, "Hebrew + English", "", badge="Recommended")
    assert all(lab.height() >= 18 for lab in card.findChildren(QWidget) if lab.objectName() == "choiceBadge")


def test_setting_change_shows_saved_feedback(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    d = Dashboard(controller)
    qtbot.addWidget(d)
    d.show_page("capture")
    widgets = {key: w for key, w, _s in d.binder._items}
    widgets["show_crosshair"].click()
    assert d.pages["capture"].saved.isVisible()
    assert SettingsStore(paths.settings_path()).load().show_crosshair is True


def test_rejected_search_address_is_not_reported_as_saved(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    d = Dashboard(controller)
    qtbot.addWidget(d)
    d.show_page("advanced")
    page = d.pages["advanced"]
    before = controller.settings.search_url
    page.search.setText("ms-settings:{query}")
    page.search.editingFinished.emit()
    assert not page.saved.isVisible()
    assert not page.search_error.isHidden() and "Not saved" in page.search_error.text()
    assert controller.settings.search_url == before
    assert SettingsStore(paths.settings_path()).load().search_url == before

    page.search.setText("  https://www.bing.com/search?q={query}  ")
    page.search.editingFinished.emit()
    assert page.saved.isVisible() and page.search_error.isHidden()
    assert controller.settings.search_url == "https://www.bing.com/search?q={query}"
    assert page.search.text() == controller.settings.search_url


def test_reduce_motion_setting(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    d = Dashboard(controller)
    qtbot.addWidget(d)
    assert not motion._user_reduced
    controller.update_settings(reduce_motion=True)
    assert motion.reduced()
    assert SettingsStore(paths.settings_path()).load().reduce_motion is True
    controller.update_settings(reduce_motion=False)
    assert not motion._user_reduced


def test_onboarding_shown_once_and_persisted(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    assert controller.settings.onboarding_done is False  # fresh install
    d = Dashboard(controller)
    qtbot.addWidget(d)
    d.show_onboarding()
    dlg = d._onboarding
    assert dlg is not None and dlg.isVisible()
    d.show_onboarding()  # a second request reuses the open tour
    assert d._onboarding is dlg
    dlg.reject()  # "Skip"
    qtbot.waitUntil(lambda: d._onboarding is None, timeout=2000)
    assert SettingsStore(paths.settings_path()).load().onboarding_done is True
    assert controller.session is None  # Skip does not start a capture


def test_existing_installs_skip_the_tour(isolated_data_dir):
    path = paths.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"trigger_keys": ["Space"], "_schema": 2}), encoding="utf-8")
    assert SettingsStore(path).load().onboarding_done is True
    assert Settings().onboarding_done is False


def test_history_empty_state_messages(qtbot, controller):
    from textsnap.ui.dashboard import Dashboard
    d = Dashboard(controller)
    qtbot.addWidget(d)
    page = d.pages["history"]
    d.show_page("history")
    assert page.empty.isVisible() and page.empty.title.text() == "History is off"
    assert not page.danger.isEnabled()  # destructive actions look and are unavailable
    page.enable_box.click()
    assert page.empty.title.text() == "Nothing here yet"
    controller.history.add("stored", "eng", "region")
    page.reload()
    assert page.list.isVisible() and not page.empty.isVisible()


def test_pdf_dialog_releases_its_connections(qtbot, controller):
    from textsnap.ui.dashboard import PdfDialog
    before = controller.receivers("2result_ready(PyObject)")
    dlg = PdfDialog.open_for(controller, None)
    assert PdfDialog.open_for(controller, None) is dlg  # one at a time
    assert controller.receivers("2result_ready(PyObject)") == before + 1
    dlg.close()
    qtbot.waitUntil(lambda: PdfDialog._open is None, timeout=2000)
    assert controller.receivers("2result_ready(PyObject)") == before


# ----------------------------------------------------------------- dialogs
def _click_later(qtbot, text: str):
    def press():
        for w in qtbot_widgets():
            if isinstance(w, QPushButton) and w.text().strip() == text and w.isVisible():
                w.click()
                return
        QTimer.singleShot(30, press)
    QTimer.singleShot(50, press)


def qtbot_widgets():
    from PySide6.QtWidgets import QApplication
    return QApplication.allWidgets()


def test_confirm_dialog_returns_choice(qtbot):
    _click_later(qtbot, "Delete")
    assert dialogs.confirm(None, "Delete?", "Gone for good.", "Delete", danger=True) is True
    _click_later(qtbot, "Cancel")
    assert dialogs.confirm(None, "Delete?", "Gone for good.", "Delete", danger=True) is False


def test_choose_and_prompt(qtbot):
    _click_later(qtbot, "Keep entries")
    assert dialogs.choose(None, "Turn off?", "", [("Cancel", None, ""), ("Keep entries", "keep", "")]) == "keep"
    _click_later(qtbot, "Save")
    assert dialogs.prompt(None, "Name", "", "My snippet") == "My snippet"


# ----------------------------------------------------------------- capture flash
def test_capture_flash_is_click_through_and_self_deleting(qtbot):
    from textsnap.ui.overlay import _FLASHES, CaptureFlash
    f = CaptureFlash(QRect(10, 10, 200, 80), None)
    assert f.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert f.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert f.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    f.start()
    assert f in _FLASHES
    qtbot.waitUntil(lambda: not _FLASHES, timeout=3000)


def test_no_capture_flash_with_reduced_motion(qtbot):
    import numpy as np
    from textsnap.capture.geometry import Monitor, Rect
    from textsnap.ui.overlay import _FLASHES, SelectionSession
    from helpers import snapshot_from
    motion.set_reduced(True)
    mon = Monitor(0, Rect(0, 0, 800, 800), Rect(0, 0, 800, 800), 1.0)
    s = SelectionSession(snapshot_from([mon], np.full((800, 800, 3), 200, np.uint8)), activate=False)
    s.start()
    s.finish(Rect(10, 10, 100, 50), "region")
    assert not _FLASHES
