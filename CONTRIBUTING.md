# Contributing to TextSnap

## Setup

TextSnap is Windows-only. You need Python 3.11+ (developed on 3.14) and Git LFS (the OCR engine in
`vendor/tesseract` is stored with LFS - see [Clone](README.md#clone)).

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python tools\prepare_vendor.py --verify
```

## Tests

```bat
.venv\Scripts\python -m pytest tests --ignore=tests/test_desktop.py
```

- Qt runs offscreen; every test gets a temporary data folder, so your own settings and history are never touched.
- OCR tests use the real bundled Tesseract on synthetic images rendered with Qt. Do not stub the engine in OCR tests;
  if the engine is missing they are meant to fail.
- `tests/test_desktop.py` injects real keyboard and mouse input (SendInput) and is opt-in via
  `TEXTSNAP_DESKTOP_TESTS=1` (`run_tests.bat --desktop`). Never run it in CI or on a machine someone is using.
- CI (`.github/workflows/ci.yml`) runs ruff and the command above on `windows-latest`.

## Style and rules

- Lint: `.venv\Scripts\python -m ruff check .` (pycodestyle + pyflakes, 140 columns; see `ruff.toml`).
- Never log recognised text, clipboard contents, key presses or images.
- Keep the keyboard-hook callback minimal; OCR and other slow work go through `controller.jobs`, UI work stays on
  the GUI thread.
- Styling lives only in `textsnap/ui/theme.py` (no `setStyleSheet` elsewhere - a test enforces this); animation goes
  through `textsnap/ui/motion.py`.
- History, saving captures, autostart and auto-paste are opt-in; keep their defaults off.
- Never modify the vendored Tesseract binaries; rebuild them with `tools/prepare_vendor.py`.
