"""Process entry point: arguments, single instance, startup and shutdown."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from textsnap import APP_NAME, __version__

log = logging.getLogger("textsnap")

COMMANDS = ("show", "capture", "capture-desktop", "ocr-clipboard", "repeat", "settings", "quit")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog=APP_NAME, description="Screen text capture with offline OCR.")
    p.add_argument("--minimized", action="store_true", help="start in the tray without showing the dashboard")
    p.add_argument("--show", action="store_true", help="show the dashboard (also sent to a running instance)")
    p.add_argument("--capture", action="store_true", help="start a region capture")
    p.add_argument("--capture-desktop", action="store_true", help="recognise all screens")
    p.add_argument("--ocr-clipboard", action="store_true", help="recognise the image on the clipboard")
    p.add_argument("--quit", action="store_true", help="ask a running instance to exit")
    p.add_argument("--data-dir", help="use this folder for settings, history and logs")
    p.add_argument("--self-test", metavar="REPORT", help="run the self-test and write a JSON report")
    p.add_argument("--self-test-clipboard", action="store_true", help="include the clipboard round trip")
    p.add_argument("--self-test-no-ui", action="store_true", help="skip the overlay window check")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p.parse_args(argv)


def forwarded_command(args: argparse.Namespace) -> str:
    if args.quit:
        return "quit"
    if args.capture:
        return "capture"
    if args.capture_desktop:
        return "capture-desktop"
    if args.ocr_clipboard:
        return "ocr-clipboard"
    return "show"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    from textsnap.storage import paths
    if args.data_dir:
        paths.set_data_dir(args.data_dir)

    # PySide6 sets per-monitor DPI awareness v2 and pass-through scale factors by
    # default; state it explicitly so coordinate maths never depends on rounding.
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    if args.self_test:
        from textsnap.app import logs, selftest
        selftest.isolated_env()
        logs.setup("INFO", paths.logs_dir(), console=False)
        from PySide6.QtWidgets import QApplication
        app = QApplication(sys.argv[:1])
        app.setApplicationName(APP_NAME)
        code = selftest.run_full(Path(args.self_test), ui=not args.self_test_no_ui,
                                 clipboard=args.self_test_clipboard)
        logs.shutdown()
        return code

    from PySide6.QtNetwork import QLocalServer
    from textsnap.winsys.single_instance import InstanceLock, instance_key

    lock = InstanceLock()
    if not lock.acquire():
        return _forward(instance_key(), forwarded_command(args))
    if args.quit:
        lock.release()
        return 0  # nothing is running: nothing to quit

    from textsnap.app import logs
    from textsnap.storage.settings import SettingsStore
    store = SettingsStore(paths.settings_path())
    settings = store.load()
    logs.setup(settings.log_level, paths.logs_dir(), console=not paths.is_frozen())
    log.info("%s %s starting", APP_NAME, __version__)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    from textsnap.ui import theme
    theme.apply(app)

    from textsnap.app.controller import AppController
    from textsnap.ui.dashboard import Dashboard
    from textsnap.ui.tray import Tray

    controller = AppController(store)
    tray_ok = QSystemTrayIcon.isSystemTrayAvailable()
    dashboard = Dashboard(controller, tray_available=tray_ok)
    controller.show_dashboard_requested.connect(dashboard.show_page)

    quitting = {"done": False}

    def cleanup() -> None:
        if quitting["done"]:
            return
        quitting["done"] = True
        controller.shutdown()
        server.close()
        if tray is not None:
            tray.hide()

    def quit_app() -> None:
        cleanup()
        app.quit()

    tray = None
    if tray_ok:
        tray = Tray(controller, dashboard.show_page, quit_app)
        tray.show()

    server = QLocalServer()
    QLocalServer.removeServer(instance_key())
    if not server.listen(instance_key()):
        log.warning("Command server unavailable: %s", server.errorString())

    def on_connection() -> None:
        sock = server.nextPendingConnection()
        if sock is None:
            return

        def read() -> None:
            command = bytes(sock.readAll()).decode("utf-8", "ignore").strip()
            sock.disconnectFromServer()
            handle(command)

        sock.readyRead.connect(read)

    def handle(command: str) -> None:
        if command == "quit":
            quit_app()
        elif command == "capture":
            controller.start_capture(source="command")
        elif command == "capture-desktop":
            controller.capture_full_desktop("command")
        elif command == "ocr-clipboard":
            controller.ocr_clipboard_image()
        elif command == "repeat":
            controller.repeat_last_region()
        elif command == "settings":
            dashboard.show_page("capture")
        else:
            dashboard.show_page("home")

    server.newConnection.connect(on_connection)
    dashboard.quit_requested.connect(quit_app)
    app.aboutToQuit.connect(cleanup)  # also covers Windows logoff/shutdown

    controller.start()
    first_run = not settings.first_run_done
    if first_run:
        controller.update_settings(first_run_done=True)
    action = args.capture or args.capture_desktop or args.ocr_clipboard
    if not tray_ok or args.show or first_run or not (args.minimized or action):
        dashboard.show_page("home")
    if not controller.settings.onboarding_done and not action:
        dashboard.show_page("home")
        QTimer.singleShot(450, dashboard.show_onboarding)  # brief, skippable, shown once
    if not tray_ok:
        from textsnap.ui import dialogs
        dialogs.inform(dashboard, "Running without a tray icon", "The Windows notification area is unavailable, "
                       "so TextSnap runs from this window. Closing it exits the app. You can also run "
                       "TextSnap.exe --capture to start a capture.")
    if args.capture:
        controller.start_capture(source="command")
    elif args.capture_desktop:
        controller.capture_full_desktop("command")
    elif args.ocr_clipboard:
        controller.ocr_clipboard_image()

    code = app.exec()
    cleanup()
    lock.release()
    log.info("Exited cleanly")
    logs.shutdown()
    return code


def _forward(key: str, command: str) -> int:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtNetwork import QLocalSocket
    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])  # noqa: F841 (keeps the Qt application alive)
    sock = QLocalSocket()
    sock.connectToServer(key)
    if not sock.waitForConnected(2000):
        print(f"{APP_NAME} is already running but did not respond.", file=sys.stderr)
        return 2
    sock.write(command.encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.waitForDisconnected(1000)
    return 0
