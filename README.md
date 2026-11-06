# TextSnap

Hold a key, drag over any text on your screen, paste it anywhere.

TextSnap is a Windows 10/11 tray utility that turns any visible screen area into
plain Unicode text with **offline OCR** for **Hebrew, English and mixed
Hebrew/English**. Nothing leaves your computer: no cloud OCR, no account, no
network access, no telemetry.

## Quick start

1. Start `TextSnap.exe` (portable build) or `run.bat` (from source).
   A TextSnap icon appears in the notification area.
2. **Hold the Spacebar for half a second.** The screen dims and freezes.
   (A normal tap of Space still types a space - see "The Spacebar trigger" below.)
3. Let go of the key, then **drag a rectangle** over the text and release the mouse.
4. The text is already on the clipboard - **paste with Ctrl+V**.

A small confirmation appears in the corner ("Text copied - paste with
Ctrl+V"). It never takes keyboard focus, and TextSnap hands focus back to the
app you were using, so you can paste immediately. Click **View** on the
confirmation (or **Show last result** in the tray) to see, edit, re-run or save
the text.

In the overlay: **Esc** or **right-click** cancels, **R / W / M / A** switch
between region, window, screen and all-screens modes, and **Enter** repeats
the previous area. A magnifier next to the cursor helps with precise edges.

## Installation

### Portable builds (no Python installation needed)

`build_exe.bat` produces two equivalent portable folders; copy either one
anywhere (for example `%LOCALAPPDATA%\Programs\TextSnap`) and keep it together:

| Folder | Start with | Notes |
|---|---|---|
| `dist\TextSnap` | `TextSnap.exe` | PyInstaller build, 260 MB. |
| `dist\TextSnap-Portable` | `TextSnap.bat` | Same app on the official Python runtime, 303 MB. Use this one if Windows **Smart App Control** (or another application-control policy) blocks `TextSnap.exe` with "An Application Control policy has blocked this file". |

Why two: Smart App Control refuses unsigned executables that have no
reputation, and every freshly built `TextSnap.exe` is such a file (on this
development PC it blocked one build and allowed the next). The portable folder
contains no newly built executable at all - it runs on the PSF-signed
`pythonw.exe`, the unmodified PyPI wheel binaries and the UB Mannheim-signed
Tesseract - so nothing needs to be unblocked and no protection has to be
turned off. `TextSnap.bat` briefly flashes a console window while it starts
`pythonw.exe`.

TextSnap does not install itself, change startup settings or need
administrator rights. The OCR engine and language models live in
`_internal\vendor\tesseract` (EXE build) or `app\vendor\tesseract` (portable).

### From source

Requirements: Windows 10/11 64-bit and Python 3.11+ (developed on 3.14).

```bat
run.bat                 :: creates .venv on first run, then starts TextSnap
run_tests.bat           :: automated tests
run_tests.bat --desktop :: also the desktop tests that inject real keyboard/mouse input
build_exe.bat           :: builds dist\TextSnap and dist\TextSnap-Portable, runs both self-tests
```

The OCR engine is checked into `vendor\tesseract`. To rebuild that folder from
the official downloads (hash-pinned): `.venv\Scripts\python tools\prepare_vendor.py`.

### Command line

| Option | Effect |
|---|---|
| `--minimized` | start in the tray only (used by the optional autostart) |
| `--show` | open the dashboard |
| `--capture` | start a region capture |
| `--capture-desktop` | recognise all screens |
| `--ocr-clipboard` | recognise the image on the clipboard |
| `--quit` | close the running TextSnap |
| `--data-dir PATH` | use another folder for settings, history and logs |
| `--self-test REPORT.json` | verify the engine, models, overlay and hook; writes a report |

If TextSnap is already running, these commands are forwarded to it; only one
instance ever runs per user session.

## Features

- **Long-press trigger** (default: Spacebar, 0.5 s). Other keys or
  combinations can be chosen (Right Ctrl, Left Ctrl, Right Alt, Left Ctrl +
  Left Shift, ...), hold time 0.2-3 s, on/off switch, live test, conflict hints
  and one-click defaults. A quick press keeps its normal meaning; pressing
  another key or a mouse button (including the wheel) while holding cancels,
  so typing and shortcuts such as Ctrl+wheel zoom never open the overlay. Left
  and right modifiers are distinct.
- **Freeze-frame overlay** across all monitors with correct coordinates for
  any scaling (100-250 %), mixed DPI and monitors left of or above the primary.
  Region, window (click a window), screen and all-screens modes, size label,
  magnifier, optional crosshair, minimum size with a re-select hint. An
  "Active window" default mode reads the focused window immediately, without
  the overlay.
- **OCR**: Tesseract 5.4 with Hebrew and English `tessdata_best` (accurate,
  default) and `tessdata_fast` models. Languages: Hebrew + English (default),
  Hebrew, English, or Auto-detect (best effort - see below). Fast mode makes
  one pass; Thorough mode tries several image preparations and keeps the best.
- **Results**: automatic copy (default), confirmation toast, result window with
  editing, copy variants (cleaned, trimmed, joined paragraphs, original,
  selection), Clean text, Run again with another language or Thorough mode,
  Save as .txt, larger editor, clickable links and e-mail addresses (links open
  only after you confirm), web search for the text on request, optional QR-code
  detection, optional automatic paste (off by default, asks for confirmation).
- **Other sources**: clipboard image, image files (PNG, JPEG, BMP, TIFF, GIF,
  WebP; drag them onto the dashboard), PDF files (page ranges, progress,
  embedded text used when present), repeat last area, all screens.
- **History** (off by default): search, copy, open, pin, snippets, delete,
  export, clear (pinned entries kept), clear pinned, retention 1 day-forever.
- **Privacy & storage**: optional saving of capture images to a folder you
  choose (off by default), keep results out of Win+V clipboard history,
  log level, reset settings, opt-in Start with Windows.

### The Spacebar trigger

Windows types a space the moment Space goes down and repeats it while the key
is held, so a long-press on Space cannot be detected without holding the key
back. With **Hold back the Spacebar** (Keyboard trigger page, on by default):

| You do | What happens |
|---|---|
| Tap Space | One space is typed - when you **release** the key (a few tens of milliseconds later than usual). |
| Type fast (next key pressed before Space is released) | Space is sent first, then that key, in the original order. No overlay. |
| Hold Space for 0.5 s | The overlay opens once. **No space is typed** and nothing repeats. Releasing Space does not close the overlay. |
| Space + mouse click or wheel | Space is sent first, then the click/wheel; the hold is cancelled. |
| Win+Space, Ctrl+Space, Shift+Space, Alt+Space (any modifier or mouse button already held) | Passed through untouched: input-language switching and other shortcuts work as before. No overlay. |

Unavoidable consequences (Windows offers no way around them for a global
long-press on a typing key):

- **Holding Space no longer auto-repeats spaces** while the trigger is on.
- Apps that act on a **held** Spacebar lose that behaviour: games (jump/charge),
  Space+drag panning in design apps (the click is re-ordered correctly, but a
  hold longer than 0.5 s before clicking opens the overlay), hold-to-scroll in
  browsers, push-to-talk. Turn the trigger off from the tray menu while using
  them, or choose another trigger key.
- The space of a tap reaches the app on release instead of on press; apps that
  react to the key-down moment (play/pause, buttons) react slightly later.
- Re-sent keys are synthetic input. TextSnap's own hook ignores them; other
  low-level keyboard tools may see them as injected.
- While an app running as administrator is focused, Windows does not show its
  keys to TextSnap at all, so Space behaves normally there and the trigger
  does nothing (use the tray menu).

With hold-back turned off, Space is never blocked, but every long press first
types a space (and more spaces once your keyboard repeat delay passes).
Settings saved with the previous default (Right Ctrl alone) are moved to the
Spacebar on first start; a different, customised trigger is kept.

### Mixed Hebrew and English

Text is produced in logical (reading) order as Unicode expects; nothing is
ever reversed for display. TextSnap adds two corrections on top of Tesseract:

- **Mixed-script check**: with both models loaded, Tesseract sometimes reads a
  short Hebrew word next to an English one as Latin letters ("עם Microsoft" ->
  "oy Microsoft"), or a Hebrew prefix glued to an English word as junk
  ("ה-API" -> "API-0"). Suspicious words are re-read with the single-language
  model and replaced only when that reading is confident and of the right script.
- **Line order**: lines that mix scripts are re-ordered from the word
  positions, using the majority script as the line direction.

A line such as "Version 3.2 של המערכת" can be legitimately stored in two
logical orders that look the same on screen; TextSnap uses the order implied
by the line's majority script.

**Auto-detect (best effort)** reads with both models, counts Hebrew and Latin
letters, and when only one script is present re-reads with that model alone,
keeping the higher-confidence result. It only chooses between Hebrew and
English.

### Interface, motion and accessibility

- **First run**: a three-step tour (hold the trigger, drag, paste) with a
  privacy note. Skip, Got it or Try it now; it is shown once and can be
  reopened from **Home > Quick tour** or **About**. Installs that already had
  settings do not see it.
- **Motion** is short and functional: page cross-fades (180 ms), sidebar
  indicator, toggles, toasts that slide in with a countdown line and pause
  while the pointer is over them, a brief accent pulse around the captured
  area, button labels that confirm in place ("Copied"). Nothing animates while
  TextSnap is idle.
- **Reduce motion**: **Advanced > Motion & accessibility** turns animations
  into instant changes. TextSnap also follows Windows' *Animation effects*
  setting (Settings > Accessibility > Visual effects) automatically.
- **Keyboard**: every control is reachable with Tab; focus rings appear for
  keyboard focus, not after mouse clicks. Action tiles and option cards react
  to Enter and Space.

## Settings and data

Everything is stored per user in `%LOCALAPPDATA%\TextSnap`:

| File | Content |
|---|---|
| `settings.json` | settings (invalid values fall back to defaults individually; a corrupt file is renamed and replaced) |
| `history.db` | only exists after you turn History on |
| `logs\textsnap.log` | diagnostics: events, timings and sizes - never recognised text |

Reset everything from **Privacy & storage > Reset all settings**, or quit
TextSnap and delete the folder.

## Privacy

- OCR runs locally in a separate `tesseract.exe` process. Pixels are streamed
  to it through a pipe and the text comes back the same way - no temporary files.
- The screenshot exists only in memory. The latest crop is kept for up to
  10 minutes so **Run again** works (or until you press Clear), then dropped.
  Images are written to disk only when you turn on "Save captured images".
- Recognised text goes to the clipboard, and into the history database only
  if you enabled History. Logs never contain text, clipboard data, key presses
  or images.
- The keyboard hook looks only for the configured trigger key(s) and records
  nothing. Keys are passed through unchanged, except that with the Spacebar
  trigger a plain Space press is held back until the hold is decided and then
  re-sent (in order, together with a key or click that arrived meanwhile) or,
  after the overlay opened, dropped. Turning the trigger off removes the hook. TextSnap never opens links or runs commands it finds in text.
- No network access at all, except the web search and links you explicitly click.

## Troubleshooting

| Problem | What to do |
|---|---|
| Holding Space types spaces instead of opening the overlay | Turn on "Hold back the Spacebar" (Keyboard trigger page), and make sure no modifier key is held. |
| A game or design app misbehaves with Space | Turn the trigger off from the tray menu while using it, or pick another trigger key. |
| Holding the key does nothing | Check the tray tooltip / Keyboard page status. Use **Test** on the Keyboard page. While an app running **as administrator** is in front, Windows does not deliver its keys to TextSnap - use the tray menu instead, or run that app normally. |
| The overlay opens by accident | Raise the hold time, or pick another trigger (Keyboard page). |
| Selected area is black | Protected content (DRM video, some games in exclusive full-screen, secure desktop) cannot be captured. This is Windows' protection and is not bypassed. |
| Wrong or missing characters | Select a little more context, try **Run again > Thorough**, or choose the language explicitly. Very small serif text (under ~11 px) is the hardest case. |
| "OCR engine unavailable" | The `vendor\tesseract` (`_internal\vendor\tesseract` in the portable build) folder is incomplete; copy the full TextSnap folder again. A custom Tesseract folder can be set on the Languages page. |
| "Language data not found" | The named `.traineddata` file is missing from the engine folder. TextSnap never silently falls back to English. |
| Clipboard error | Another program held the clipboard. Click **Copy** in the result window to retry. |
| No tray icon | TextSnap then keeps the dashboard open; `TextSnap.exe --capture` also starts a capture. |
| Two copies running? | Not possible: a second launch hands its command to the running instance and exits. |

Diagnostics (no user text) are on **About & diagnostics**; logs are in
`%LOCALAPPDATA%\TextSnap\logs`.

## Known limitations

- A region selection stays within one monitor (window, screen and all-screens
  modes cover several).
- Keys pressed while an elevated (administrator) window has focus are not
  seen by the trigger (Windows UIPI). The tray menu still works.
- OCR accuracy depends on the source: anti-aliased screen text at 12 px or
  more is read reliably; tiny serif fonts and stylised text less so.
- The interface uses one dark theme. It does not switch with Windows light
  mode and does not adopt Windows High Contrast colours.
- The bundled `libtesseract-5.dll` contains the upstream build's debug
  information (~97 MB); it is kept unmodified to preserve the publisher's signature.

## License notices

TextSnap bundles Tesseract OCR, its language models and libraries, Qt/PySide6
and other components under their own licenses. See `THIRD_PARTY_NOTICES.md`
and the `licenses` folder.
