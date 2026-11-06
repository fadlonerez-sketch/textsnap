"""System tray icon and menu."""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from textsnap.app.controller import AppController
from textsnap.keyboard.keys import describe_trigger
from textsnap.ui import theme


class Tray(QSystemTrayIcon):
    def __init__(self, controller: AppController, show_dashboard: Callable[[str], None], quit_app: Callable[[], None]):
        super().__init__(theme.app_icon())
        self.c = controller
        menu = QMenu()
        ic = theme.icon
        self.capture = menu.addAction(ic("capture", theme.C.ACCENT), "Start text capture",
                                      lambda: controller.start_capture(source="tray"))
        menu.addAction(ic("desktop"), "Capture all screens", lambda: controller.capture_full_desktop("tray"))
        menu.addAction(ic("repeat"), "Repeat last area", controller.repeat_last_region)
        menu.addSeparator()
        menu.addAction(ic("paste"), "OCR clipboard image", controller.ocr_clipboard_image)
        menu.addAction(ic("image"), "OCR image file…", lambda: controller.ocr_image_file())
        menu.addAction(ic("text"), "Show last result", lambda: controller.show_result())
        menu.addSeparator()
        menu.addAction(ic("home"), "Open dashboard", lambda: show_dashboard("home"))
        menu.addAction(ic("advanced"), "Settings", lambda: show_dashboard("capture"))
        self.toggle: QAction = menu.addAction("Keyboard trigger enabled")
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(lambda on: controller.update_settings(trigger_enabled=on))
        menu.addSeparator()
        menu.addAction(ic("power"), "Exit TextSnap", quit_app)
        self.setContextMenu(menu)
        self._menu = menu
        self.activated.connect(self._activated)
        self._show_dashboard = show_dashboard
        controller.settings_changed.connect(lambda _s: self.refresh())
        controller.trigger_status.connect(lambda _st, _m: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        s = self.c.settings
        self.toggle.blockSignals(True)
        self.toggle.setChecked(s.trigger_enabled)
        self.toggle.blockSignals(False)
        if not s.trigger_enabled:
            tip = "TextSnap — keyboard trigger off"
        elif self.c.trigger.state == "error":
            tip = "TextSnap — keyboard trigger unavailable (use this menu)"
        else:
            tip = f"TextSnap — hold {describe_trigger(s.trigger_keys)} to capture text"
        self.setToolTip(tip)

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick, QSystemTrayIcon.ActivationReason.Trigger):
            self._show_dashboard("home")
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.c.start_capture(source="tray")
