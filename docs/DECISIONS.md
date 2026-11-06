# Architecture and safety decisions

## OCR engine: Tesseract 5.4 (UB Mannheim build), out of process

- **Why Tesseract**: genuine, maintained Hebrew (`heb`) and English (`eng`)
  LSTM models under Apache-2.0, runs fully offline, handles RTL reading order.
  Alternatives were rejected: Windows.Media.Ocr depends on per-machine language
  packs that cannot be bundled; EasyOCR/PaddleOCR have no maintained Hebrew
  model and pull in large ML runtimes.
- **Binary**: the official UB Mannheim Windows build, unpacked from its NSIS
  installer with 7-Zip (nothing is installed). Only `tesseract.exe` and its PE
  import closure (27 files) are kept, byte-for-byte unmodified so they keep
  their Authenticode signature. `tools/prepare_vendor.py` reproduces the folder
  from hash-pinned downloads; `MANIFEST.json` lets every build verify it.
  The 97 MB `libtesseract-5.dll` carries upstream DWARF data; stripping it
  would break the signature, so it is left alone.
- **Models**: `tessdata_best` (default, most accurate) and `tessdata_fast`
  for `heb` and `eng`. `osd` (orientation detection) was evaluated and
  dropped: on short screen snippets it reported confidence 0.2-0.4 and
  refused 90/270-degree text ("Too few characters").
- **Subprocess, not in-process bindings**: crashes or hangs cannot take the
  UI down, a timeout can kill the engine, and the mingw-built DLLs never share
  a process with Qt/Python DLLs (no DLL-name clashes such as `zlib1.dll`).
  Pixels go in through stdin as PGM; TSV comes back on stdout via
  `-c tessedit_create_tsv=1` (no config files needed, no temp files).
  `OMP_THREAD_LIMIT=1` keeps small images fast and lets thorough mode run
  variants in parallel. Cost: ~150-300 ms per call, measured.
- **Preprocessing** (numpy + Pillow only, no OpenCV): grayscale, invert
  light-on-dark, drop selection-edge lines and margins, scale so text lines
  are ~24 px (chosen by a sweep over 4 fonts x 7 sizes x 3 themes x 3 scripts;
  24 px beat 18/21/27/32 px), contrast stretch, white padding. Grayscale is
  kept: the LSTM reads anti-aliased glyphs better than forced binarisation.
  Thorough mode adds alternative scale, Sauvola threshold, best colour channel
  and deskew variants and keeps the best length-weighted confidence.
- **Mixed Hebrew/English correction**: the combined model misreads short
  Hebrew words beside English ("עם" -> "oy") and Hebrew prefixes glued to
  English ("ה-API" -> "API-0"), and the reverse. Suspicious tokens are re-read
  by the single-script model (aligned by box IoU, or by re-reading the word's
  own crop) and replaced only on confident, script-consistent readings. Mixed
  lines are re-ordered from word positions with the majority script as base
  direction, because Tesseract occasionally emits majority-Hebrew lines LTR.
- **Auto language** is real logic (script counting + single-model re-read +
  confidence comparison) and is labelled "best effort".
- Bidi control marks (LRM/RLM) that Tesseract inserts are stripped by default
  (option). Text is never reversed for display.

## Trigger: WH_KEYBOARD_LL on a dedicated thread

- `RegisterHotKey` cannot measure a hold, so a low-level hook is used. It runs
  on its own thread with its own `GetMessage` loop; the hold timer is a Win32
  thread timer on that same thread, so activation latency does not depend on
  the Qt event loop.
- The callback only classifies the event and updates a pure state machine
  (`keyboard/detector.py`, fully unit-tested with a fake clock/scheduler).
  Every event is passed on with `CallNextHookEx`; nothing is suppressed,
  logged or stored. Non-trigger keys are reported only as an anonymous
  "other input" signal.
- False-trigger guards: another key or mouse button during the hold cancels
  it (a WH_MOUSE_LL hook exists only while a hold is pending, so Ctrl+wheel
  zoom never fires); a modifier or mouse button already held blocks arming;
  AltGr's synthetic Left Ctrl is ignored; at fire time the keys must still be
  physically down (`GetAsyncKeyState`) to survive missed key-ups (secure
  desktop); a key-down after >1.5 s of silence is treated as a fresh press.
- Windows silently removes low-level hooks that time out. Python callbacks
  need the GIL, so the hook is refreshed every 2 minutes while idle. Heavy
  work never runs on the GUI thread.
- Turning the trigger off stops the thread and removes the hook entirely.
- **Spacebar (default trigger since schema 2)**: a typing key cannot be
  long-pressed without being held back, because Windows types it on key-down.
  The "dual-role key" scheme in `keyboard/intercept.py` blocks a plain Space
  press while the hold is pending and re-sends exactly what the user meant:
  a tap becomes Space down+up on release; another key or mouse button during
  the hold re-sends Space first and then that key/click (blocking and
  re-injecting the original preserves the order, which injecting from inside
  the hook could not); after activation the auto-repeats and release are
  swallowed. Space with a modifier or mouse button already held is never
  touched (Win+Space language switch). Re-sent input carries TextSnap's
  dwExtraInfo tag so its own hooks ignore it. Because a blocked key never
  reaches the async key state, the detector asks the interceptor whether the
  key is still down. Settings files still on the old default (Right Ctrl
  alone) are migrated to the Spacebar; customised triggers are kept.

## Capture: freeze-frame GDI copy, one overlay per monitor

- The virtual desktop is copied once (BitBlt + CAPTUREBLT for layered windows)
  when the trigger fires; the overlay displays that frozen image. The crop is
  exactly what the user saw, video frames hold still, and no second capture
  races with the overlay closing. Pixels live only in memory.
- Each monitor gets its own top-level window, matched to its physical
  rectangle via `QWindowsScreen.handle()` (HMONITOR) - Qt 6's `QScreen.name()`
  is a friendly name, not `\\.\DISPLAYn`. Positions are converted with that
  monitor's own scale factor (`physical = origin + round(local * dpr)`), so
  mixed DPI and negative coordinates work. Rounding policy is PassThrough.
- A region drag is limited to one monitor (window/screen/all modes span
  several). Protected surfaces are not bypassed.
- The overlay takes focus with the documented `AttachThreadInput` technique
  so Esc works; the hook also watches Esc while the overlay is open. After the
  selection, focus is returned to the previously active window so Ctrl+V
  works immediately; the toast never activates.

## Privacy

- No network code. History (SQLite, `secure_delete=ON`) is opt-in and the
  file is created only when enabled. Images are never stored in history.
  Capture images are saved only with an explicit setting and folder.
- Logs contain events, timings, sizes and error types only; a test asserts
  recognised text never reaches the log file.
- The last crop stays in memory for "Run again" for at most 10 minutes.
- Optional: CF "CanIncludeInClipboardHistory"/"CanUploadToCloudClipboard" = 0
  keeps results out of Win+V history and cloud clipboard.
- Autostart (HKCU Run value) and auto-paste (one tagged Ctrl+V via SendInput)
  are off by default and require confirmation.

## Interface: one design system, styled centrally

- Tokens live in `ui/theme.py` (colours `C`, spacing `S`, radii `R`, control
  heights `H`, type scale `T`). The application style sheet is generated from
  them once; components set an object name and a dynamic property (`kind`,
  `tone`, `selected`) and call `widgets.set_prop`, which re-polishes. No widget
  owns a style sheet (`test_styles_live_only_in_the_theme`), so a colour change
  happens in one place and nothing parses per-widget style sheets at runtime.
- One accent (cyan `#45C8EC`) on graphite. State colours (success, warning,
  error) are used only for state, never for decoration.
- Icons come from the Windows icon font (Segoe Fluent Icons, falling back to
  Segoe MDL2 Assets) rendered into cached pixmaps: no image assets to ship and
  icons stay sharp at every scale. Text uses Segoe UI Variable when present.
- Qt ignores a corner radius larger than half a widget's height, so pills have
  fixed heights that match their radius.
- Dashboard pages are built on first use. Polishing a page against the
  application style sheet dominated the dashboard's cost (~0.9 s for eight
  pages); building Home alone takes ~0.15-0.2 s, later pages ~0.1 s on first
  visit.

## Motion

- `ui/motion.py` owns every animation: three durations (120/180/260 ms),
  ease-out curves, one running animation per (object, property) - a new one
  replaces the old - and animations delete themselves when they stop. Effects
  used for fades are removed afterwards so idle widgets paint normally.
- Reduced motion (user setting or Windows "Animation effects" off) makes
  every animation jump to its end state through the same API, so behaviour is
  identical with and without motion.
- Timers exist only while something is visible (spinner, toast countdown);
  `perf` checks found no running animations or widget timers when idle.
- Delayed UI callbacks pass their widget as the timer context so they are
  dropped if the widget is deleted first.

## Process lifecycle

- One instance per user session: a named mutex decides; a QLocalServer in the
  primary receives `show`/`capture`/`quit` from later launches.
- Closing the dashboard with its title-bar button hides it to the tray (a
  spontaneous close event). Programmatic closes are accepted: Qt 6 quits, and
  Windows logoff ends the session, by closing every window and cancels if one
  refuses. Without a tray icon, closing the window exits.
- Exit: cancel overlay, stop hook thread (unhook), cancel jobs and wait for the
  pool, close history, release the mutex.

## Packaging

- PyInstaller one-folder (fast start, OCR files stay plain files). PyInstaller 6
  analyses binaries inside data folders and would duplicate Tesseract's DLLs
  into `_internal`; the spec filters those, plus unused Qt pieces
  (`opengl32sw.dll`, translations, TLS plugins). Result: ~270 MB, of which
  ~150 MB is the unmodified Tesseract build.
- Smart App Control (enforcing on the development PC) blocks unsigned
  executables without reputation, and a fresh PyInstaller bootloader is one;
  it blocked one build and allowed the next. Turning the protection off is not
  an option, and code signing needs a trusted certificate, so a second layout,
  `TextSnap-Portable`, runs the same code on the official PSF-signed Python
  embeddable runtime (pinned SHA-256 and signature checked at build time),
  with PySide6 trimmed to Core/Gui/Widgets/Network/Svg. No newly built
  executable exists in that folder.
- `TextSnap.exe --self-test report.json` verifies the bundled resources,
  engine version, Hebrew and English recognition with both model sets, the
  overlay and the hook, inside the frozen build.
