# TextSnap - maintenance notes

Windows 10/11 tray app: long-press a key -> freeze-frame overlay -> drag ->
offline Tesseract OCR (Hebrew + English) -> clipboard. Python 3.14, PySide6.

## Commands

- Run from source: `run.bat` (or `.venv\Scripts\python main.py --data-dir %TEMP%\ts-dev` to keep real settings untouched)
- Tests: `run_tests.bat` (offscreen, real OCR); `run_tests.bat --desktop` adds tests that inject real
  keyboard/mouse input (Space/F24/F23 into a TextSnap-owned text box, one brief Right Ctrl). They skip while the
  session is locked or while someone used the keyboard/mouse in the last 10 s.
- Build + verify: `build_exe.bat` -> `dist\TextSnap\` (PyInstaller) and `dist\TextSnap-Portable\` (signed embeddable
  Python, for Smart App Control machines); `tools\verify_build.py [--portable]` runs a build's self-test (exit 3 = blocked by
  application control). `build_portable.py` refuses to replace a folder a running TextSnap uses; pass
  `--out DIR` (and `verify_build.py --portable --dir DIR`) to build beside it.
- Packaged E2E: `set TEXTSNAP_EXE=...\dist\TextSnap\TextSnap.exe` (or `...\dist\TextSnap-Portable\TextSnap.bat`)
  then `run_tests.bat --desktop -k packaged`.
- Engine files: `vendor\tesseract` is checked in; `tools\prepare_vendor.py` rebuilds it from hash-pinned
  downloads, `--verify` checks `MANIFEST.json`. Never modify the vendored binaries.

## Layout

- `textsnap/keyboard/` detector (pure state machine), intercept (Spacebar hold-back/replay, pure), hook (LL hook
  thread), service (Qt wrapper), keys.
- `textsnap/capture/` geometry (pure), screen (GDI snapshot), windows (window rects), convert.
- `textsnap/ocr/` engine (tesseract subprocess), preprocess, pipeline (strategy + mixed-script fix), text, qr,
  documents (images/PDF), samples (synthetic test images).
- `textsnap/app/` controller (workflow hub), jobs (thread pool), main (entry, single instance), selftest, logs.
- `textsnap/ui/` theme (tokens, generated style sheet, icons, logo), motion (all animation), widgets (components),
  dialogs, dashboard (8 lazily built pages + onboarding), overlay, result_window, toast, tray.
- `textsnap/winsys/` focus, startup (HKCU Run), single_instance, sendinput (opt-in paste).

## Rules

- Never log recognised text, clipboard contents, keys or images (test: `test_ocr_text_not_in_log_file`).
- Hook callback must stay tiny. It blocks input only for the Spacebar hold-back in intercept.py (plain Space
  while pending, its auto-repeats/release after activation, and a key/click that is re-sent behind Space).
  Everything blocked is either re-sent in order or intentionally swallowed after activation.
- UI only on the GUI thread; OCR via `controller.jobs`; only `_current_job` results are used.
- Coordinates: physical pixels everywhere except inside an overlay window (logical); convert with
  `Monitor.local_to_physical`. Do not assume dpr == 1.
- History, capture saving, autostart and auto-paste are opt-in; keep defaults off.
- Tests use `TEXTSNAP_DATA_DIR` temp dirs (conftest) and synthetic images only. Don't stub the OCR engine in
  OCR tests; if Tesseract is missing they must fail.
- UI styling only in `theme.stylesheet()`: give widgets an object name / dynamic property and use
  `widgets.set_prop`; no `setStyleSheet` outside theme.py (tested). New glyph label sizes go in `GLYPH_SIZES`.
- Animate only through `ui/motion.py` (respects reduced motion, one animation per property). Nothing may run
  while idle; delayed UI callbacks use `QTimer.singleShot(ms, widget, fn)`.
- Never let a window refuse a programmatic close (it would cancel quitting and Windows logoff).
- Do not touch other projects in the parent folder (LaunchDeck, AISender, ...).
