"""Key names, virtual-key codes, trigger presets and conflict hints.

Left and right modifiers are distinct keys. The low-level hook reports sided
virtual-key codes (VK_LCONTROL/VK_RCONTROL ...); :func:`normalize_vk` handles
the rare sources that send the generic VK_CONTROL/VK_SHIFT/VK_MENU instead.
"""

from __future__ import annotations

from dataclasses import dataclass

VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU = 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5
VK_LWIN, VK_RWIN, VK_APPS = 0x5B, 0x5C, 0x5D
VK_LBUTTON, VK_RBUTTON, VK_MBUTTON, VK_XBUTTON1, VK_XBUTTON2 = 0x01, 0x02, 0x04, 0x05, 0x06

LLKHF_EXTENDED = 0x01
RIGHT_SHIFT_SCANCODE = 0x36
# AltGr is delivered as a synthetic Left Ctrl (scan code 0x21D) followed by Right Alt.
ALTGR_FAKE_CTRL_SCANCODE = 0x21D


@dataclass(frozen=True)
class KeyDef:
    name: str
    vk: int
    label: str
    modifier: bool = False


def _build() -> dict[str, KeyDef]:
    keys = [
        KeyDef("RCtrl", VK_RCONTROL, "Right Ctrl", True),
        KeyDef("LCtrl", VK_LCONTROL, "Left Ctrl", True),
        KeyDef("RShift", VK_RSHIFT, "Right Shift", True),
        KeyDef("LShift", VK_LSHIFT, "Left Shift", True),
        KeyDef("RAlt", VK_RMENU, "Right Alt", True),
        KeyDef("LAlt", VK_LMENU, "Left Alt", True),
        KeyDef("LWin", VK_LWIN, "Left Windows", True),
        KeyDef("RWin", VK_RWIN, "Right Windows", True),
        KeyDef("Menu", VK_APPS, "Menu key"),
        KeyDef("CapsLock", 0x14, "Caps Lock"),
        KeyDef("ScrollLock", 0x91, "Scroll Lock"),
        KeyDef("Pause", 0x13, "Pause"),
        KeyDef("Insert", 0x2D, "Insert"),
        KeyDef("Space", VK_SPACE, "Spacebar"),
    ]
    keys += [KeyDef(f"F{i}", 0x70 + i - 1, f"F{i}") for i in range(1, 25)]
    keys += [KeyDef(chr(c), c, chr(c)) for c in range(ord("A"), ord("Z") + 1)]
    keys += [KeyDef(str(d), 0x30 + d, str(d)) for d in range(10)]
    return {k.name: k for k in keys}


KEYS: dict[str, KeyDef] = _build()
MODIFIER_NAMES = [k.name for k in KEYS.values() if k.modifier]
MAIN_KEY_NAMES = [k.name for k in KEYS.values() if not k.modifier]
DEFAULT_TRIGGER = ["Space"]

PRESETS: list[tuple[str, list[str]]] = [
    ("Spacebar (default)", ["Space"]),
    ("Right Ctrl", ["RCtrl"]),
    ("Left Ctrl", ["LCtrl"]),
    ("Right Alt", ["RAlt"]),
    ("Right Shift", ["RShift"]),
    ("Left Ctrl + Left Shift", ["LCtrl", "LShift"]),
    ("Menu key", ["Menu"]),
]

# Modifiers checked at arming time: if one of these (or a mouse button) is
# already held, the user is performing a shortcut, not a long-press.
GUARD_VKS = (
    VK_LBUTTON, VK_RBUTTON, VK_MBUTTON, VK_XBUTTON1, VK_XBUTTON2,
    VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU, VK_LWIN, VK_RWIN,
)


def normalize_vk(vk: int, scan_code: int, flags: int) -> int:
    """Map generic modifier codes to their sided equivalents."""
    if vk == VK_CONTROL:
        return VK_RCONTROL if flags & LLKHF_EXTENDED else VK_LCONTROL
    if vk == VK_MENU:
        return VK_RMENU if flags & LLKHF_EXTENDED else VK_LMENU
    if vk == VK_SHIFT:
        return VK_RSHIFT if scan_code == RIGHT_SHIFT_SCANCODE else VK_LSHIFT
    return vk


def is_altgr_fake_ctrl(vk: int, scan_code: int) -> bool:
    return vk == VK_LCONTROL and scan_code == ALTGR_FAKE_CTRL_SCANCODE


def validate_trigger(names: list[str]) -> str | None:
    """Return an error message, or None when the trigger is usable."""
    if not names:
        return "choose at least one key"
    if len(names) > 4:
        return "use at most four keys"
    unknown = [n for n in names if n not in KEYS]
    if unknown:
        return f"unknown key(s): {', '.join(unknown)}"
    if len(set(names)) != len(names):
        return "a key is listed twice"
    if sum(1 for n in names if not KEYS[n].modifier) > 1:
        return "use at most one non-modifier key"
    return None


def trigger_vks(names: list[str]) -> frozenset[int]:
    error = validate_trigger(names)
    if error:
        raise ValueError(error)
    return frozenset(KEYS[n].vk for n in names)


def ordered(names: list[str]) -> list[str]:
    """Modifiers first (in a stable order), then the main key."""
    order = {n: i for i, n in enumerate(KEYS)}
    return sorted(names, key=lambda n: (not KEYS[n].modifier, order.get(n, 999)))


def describe_trigger(names: list[str]) -> str:
    if validate_trigger(names):
        return "(invalid trigger)"
    return " + ".join(KEYS[n].label for n in ordered(names))


def conflict_warnings(names: list[str], hold_back: bool = True) -> list[str]:
    """Known interactions worth warning about. Not exhaustive by design.

    ``hold_back`` is the "hold back the Spacebar" setting (see intercept.py).
    """
    if validate_trigger(names):
        return []
    s = set(names)
    mods = {n for n in s if KEYS[n].modifier}
    main = [n for n in s if not KEYS[n].modifier]
    warnings: list[str] = []
    if main and not mods:
        key = main[0]
        if key == "Space" and hold_back:
            warnings.append("A quick tap still types a space, but the space is sent when you release "
                            "the key, and holding Space no longer repeats spaces.")
            warnings.append("Apps that use a held Spacebar (games, Space+drag panning in design apps, "
                            "hold-to-scroll) lose that behaviour while the trigger is on. Turn the trigger "
                            "off from the tray, or choose another key, when you use them.")
        elif key == "Space":
            warnings.append("Without hold-back, every long press first types a space, and holds longer than "
                            "your keyboard repeat delay type repeated spaces.")
        elif len(key) == 1:
            warnings.append("Holding a character key types repeated characters in the focused app.")
        if key == "CapsLock":
            warnings.append("Caps Lock will still toggle each time you press it.")
        if key == "ScrollLock":
            warnings.append("Scroll Lock will still toggle each time you press it.")
        if key == "Menu":
            warnings.append("The Menu key opens a context menu in the focused app when released.")
        if key in ("Insert",):
            warnings.append("Insert toggles overwrite mode in many editors.")
        if key.startswith("F") and key[1:].isdigit() and int(key[1:]) <= 12:
            warnings.append(f"{key} is used by many applications (for example F1 opens help).")
    if main and mods:
        warnings.append("Applications may react to this combination as a shortcut while you hold it.")
    if s & {"LAlt", "RAlt"} and not main:
        warnings.append("Alt activates menu bars in some applications when released; "
                        "Right Alt acts as AltGr on some keyboard layouts.")
    if s & {"LWin", "RWin"}:
        warnings.append("Releasing the Windows key alone opens the Start menu.")
    if "LCtrl" in s and len(s) == 1:
        warnings.append("Left Ctrl is part of many shortcuts. TextSnap cancels the hold when "
                        "another key or mouse button is pressed, but long Ctrl holds "
                        "(for example while zooming) may still trigger it.")
    if s & {"LShift", "RShift"} and len(s) == 1:
        warnings.append("Shift is held for long periods while typing capitals and selecting text.")
    return warnings
