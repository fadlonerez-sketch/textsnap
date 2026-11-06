"""TextSnap design system: tokens, typography, icons, the app style sheet and logo.

Identity: "precise graphite" - near-black graphite surfaces, fine hairlines,
one disciplined signal-cyan accent reserved for the primary action, the
selection, focus and the active state. Semantic colours (success, warning,
danger) are separate from the accent. Everything visual is derived from the
tokens below; widgets never hard-code colours or sizes of their own.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap,
)
from PySide6.QtWidgets import QApplication, QWidget

from textsnap.storage import paths


# ----------------------------------------------------------------------------- colour tokens
class C:
    BG = "#0D0F13"  # window canvas
    SIDEBAR = "#101217"
    SURFACE = "#15181E"  # cards and groups
    SURFACE_HOVER = "#1A1E25"
    RAISED = "#1C2028"  # inputs, secondary buttons
    RAISED_HOVER = "#232833"
    RAISED_PRESSED = "#2A303C"
    BORDER = "#232731"  # hairlines
    BORDER_STRONG = "#2F3541"
    TEXT = "#ECEEF2"
    TEXT_2 = "#A6ACB8"  # secondary
    TEXT_3 = "#737A87"  # tertiary / captions
    TEXT_DISABLED = "#4D5360"
    ACCENT = "#45C8EC"  # signal cyan
    ACCENT_HOVER = "#64D3F1"
    ACCENT_PRESSED = "#2FB2D7"
    ON_ACCENT = "#04212B"
    ACCENT_SOFT = "rgba(69, 200, 236, 0.11)"
    ACCENT_LINE = "rgba(69, 200, 236, 0.45)"
    SUCCESS = "#4CD68A"
    SUCCESS_SOFT = "rgba(76, 214, 138, 0.11)"
    WARNING = "#F2B84B"
    WARNING_SOFT = "rgba(242, 184, 75, 0.10)"
    DANGER = "#F06A6A"
    DANGER_SOFT = "rgba(240, 106, 106, 0.10)"
    SHADOW = "rgba(0, 0, 0, 0.55)"


# Back-compatible aliases used across the code base.
BG, SURFACE, SURFACE_2, SURFACE_3 = C.BG, C.SURFACE, C.RAISED, C.RAISED_HOVER
BORDER, TEXT, MUTED, SUBTLE = C.BORDER, C.TEXT, C.TEXT_2, C.TEXT_3
ACCENT, ACCENT_HOVER, ACCENT_PRESSED = C.ACCENT, C.ACCENT_HOVER, C.ACCENT_PRESSED
SUCCESS, WARNING, DANGER = C.SUCCESS, C.WARNING, C.DANGER

KIND_COLOR = {"info": C.ACCENT, "success": C.SUCCESS, "warning": C.WARNING, "error": C.DANGER}
KIND_SOFT = {"info": C.ACCENT_SOFT, "success": C.SUCCESS_SOFT, "warning": C.WARNING_SOFT, "error": C.DANGER_SOFT}


# ----------------------------------------------------------------------------- spacing, radii, sizes
class S:
    XS, SM, MD, LG, XL, XXL, XXXL = 4, 8, 12, 16, 20, 24, 32
    PAGE_X, PAGE_Y = 36, 30  # page content margins
    MAX_CONTENT = 860  # readable width of settings pages


class R:
    SM, MD, LG, XL = 6, 8, 10, 14


class H:  # control heights
    SM, MD, LG = 28, 32, 40


# ----------------------------------------------------------------------------- typography
def _first_family(*names: str) -> str:
    available = set(QFontDatabase.families()) if QGuiApplication.instance() else set()
    for n in names:
        if n in available:
            return n
    return names[-1]


class T:
    """Type scale in pixels (Qt scales px with the Windows display scale)."""

    CAPTION, SMALL, BODY, BODY_LG, TITLE, H2, H1, DISPLAY = 11, 12, 13, 14, 15, 18, 24, 30
    _ui = _display = _icons = _mono = None

    @classmethod
    def ui(cls) -> str:
        if cls._ui is None:
            cls._ui = _first_family("Segoe UI Variable Text", "Segoe UI")
        return cls._ui

    @classmethod
    def display(cls) -> str:
        if cls._display is None:
            cls._display = _first_family("Segoe UI Variable Display", "Segoe UI")
        return cls._display

    @classmethod
    def icons(cls) -> str:
        if cls._icons is None:
            cls._icons = _first_family("Segoe Fluent Icons", "Segoe MDL2 Assets")
        return cls._icons

    @classmethod
    def mono(cls) -> str:
        if cls._mono is None:
            cls._mono = _first_family("Cascadia Mono", "Consolas")
        return cls._mono


UI_FONT = "Segoe UI"  # legacy name; prefer T.ui()
ICON_FONT = "Segoe MDL2 Assets"


def font(px: int = T.BODY, weight: QFont.Weight = QFont.Weight.Normal, display: bool = False) -> QFont:
    f = QFont(T.display() if display else T.ui())
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def glyph_font(px: int = 16) -> QFont:
    f = QFont(T.icons())
    f.setPixelSize(px)
    return f


# Segoe Fluent Icons / MDL2 code points (one family for the whole product).
GLYPH = {
    "home": "\ue80f", "capture": "\ue722", "keyboard": "\ue765", "language": "\uf2b7",
    "history": "\ue81c", "privacy": "\ue72e", "advanced": "\ue9e9", "about": "\ue946",
    "copy": "\ue8c8", "save": "\ue74e", "refresh": "\ue72c", "clear": "\ue894", "expand": "\ue740",
    "collapse": "\ue73f", "search": "\ue721", "link": "\ue71b", "mail": "\ue715", "close": "\ue8bb",
    "check": "\ue73e", "pin": "\ue718", "unpin": "\ue77a", "delete": "\ue74d", "edit": "\ue70f",
    "region": "\uf407", "window": "\ue737", "monitor": "\ue7f4", "desktop": "\ue7f8",
    "warning": "\ue7ba", "info": "\ue946", "error": "\uea39", "success": "\ue930", "image": "\ueb9f",
    "paste": "\ue77f", "pdf": "\uea90", "folder": "\ue8b7", "qr": "\ued14", "clean": "\ue8c6",
    "repeat": "\ue8ee", "play": "\ue768", "export": "\uede1", "shield": "\uea18", "chevron": "\ue76c",
    "more": "\ue712", "text": "\ue8d2", "sparkle": "\ue945", "power": "\ue7e8", "test": "\ue9d9",
    "lock": "\ue72e", "clipboard": "\ue77f", "cpu": "\ue950", "open": "\ue8a7", "back": "\ue72b",
}

STATE_GLYPH = {"info": GLYPH["info"], "success": GLYPH["success"], "warning": GLYPH["warning"],
               "error": GLYPH["error"]}


def _dpr() -> float:
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app else None
    return max(1.0, screen.devicePixelRatio()) if screen else 1.0


@lru_cache(maxsize=256)
def _glyph_pixmap(glyph: str, color: str, px: int, dpr: float) -> QPixmap:
    pm = QPixmap(round(px * dpr), round(px * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setPen(QColor(color))
    p.setFont(glyph_font(px))
    p.drawText(QRectF(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    return pm


def icon(name: str, color: str = C.TEXT_2, px: int = 16, disabled_color: str = C.TEXT_DISABLED) -> QIcon:
    """A crisp QIcon from the icon font (normal + disabled states)."""
    glyph = GLYPH.get(name, name)
    dpr = _dpr()
    ic = QIcon()
    ic.addPixmap(_glyph_pixmap(glyph, color, px, dpr), QIcon.Mode.Normal)
    ic.addPixmap(_glyph_pixmap(glyph, color, px, dpr), QIcon.Mode.Active)
    ic.addPixmap(_glyph_pixmap(glyph, disabled_color, px, dpr), QIcon.Mode.Disabled)
    return ic


def polish(widget: QWidget) -> None:
    """Re-evaluate the style sheet after an objectName/property change."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


# ----------------------------------------------------------------------------- asset images for QSS
_ASSETS: dict[str, str] = {}


def _asset(name: str, svg: str) -> str:
    """Write a tiny SVG into the per-user cache once and return a QSS-safe path."""
    if name not in _ASSETS:
        folder = paths.data_dir() / "cache" / "ui"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}.svg"
        if not path.exists() or path.read_text(encoding="utf-8") != svg:
            path.write_text(svg, encoding="utf-8")
        _ASSETS[name] = str(path).replace("\\", "/")
    return _ASSETS[name]


def _chevron(color: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
            f'<path d="M2.5 4.5 L6 8 L9.5 4.5" fill="none" stroke="{color}" stroke-width="1.5" '
            f'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def _check(color: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
            f'<path d="M2.5 6.2 L5 8.6 L9.6 3.6" fill="none" stroke="{color}" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round"/></svg>')


# ----------------------------------------------------------------------------- style sheet
def rgba(color: str, alpha: float) -> str:
    """A '#RRGGBB' token as a QSS rgba() with the given alpha."""
    q = QColor(color)
    return f"rgba({q.red()}, {q.green()}, {q.blue()}, {alpha:g})"


# State colours shared by banners, pills, dialog badges, toasts and status chips.
STATE_COLOR = {"info": C.ACCENT, "question": C.ACCENT, "success": C.SUCCESS, "ok": C.SUCCESS,
               "warning": C.WARNING, "error": C.DANGER, "danger": C.DANGER, "busy": C.ACCENT}
TONE_COLOR = {"default": C.TEXT, "muted": C.TEXT_2, "subtle": C.TEXT_3, "accent": C.ACCENT, "danger": C.DANGER,
              "success": C.SUCCESS, "warning": C.WARNING}


GLYPH_SIZES = (12, 14, 16, 18, 20, 22, 24, 26, 28)  # sizes glyph() labels may use


def _state_rules() -> str:
    """Rules for components whose colour follows a ``kind`` (or ``tone``/``px``) property."""
    icons = T.icons()
    out = [f'QLabel#glyphIcon {{ font-family: "{icons}"; font-size: 16px; color: {C.TEXT_2}; }}']
    out += [f'QLabel#glyphIcon[tone="{tone}"] {{ color: {color}; }}' for tone, color in TONE_COLOR.items()]
    out += [f'QLabel#glyphIcon[px="{px}"] {{ font-size: {px}px; }}' for px in GLYPH_SIZES]
    for kind, color in STATE_COLOR.items():
        out.append(f'QFrame#banner[kind="{kind}"] {{ background: {rgba(color, 0.08)}; '
                   f'border: 1px solid {rgba(color, 0.28)}; }}')
        out.append(f'QLabel#bannerIcon[kind="{kind}"], QLabel#pillDot[kind="{kind}"] {{ color: {color}; }}')
        out.append(f'QLabel#pillDot[kind="{kind}"] {{ background: {color}; }}')
        out.append(f'QLabel#dialogBadge[kind="{kind}"], QLabel#toastIcon[kind="{kind}"] '
                   f'{{ color: {color}; background: {rgba(color, 0.13)}; }}')
        out.append(f'QLabel#statusChip[kind="{kind}"] {{ color: {color}; background: {rgba(color, 0.10)}; }}')
    return "\n".join(out)


def stylesheet() -> str:
    ui, disp, mono = T.ui(), T.display(), T.mono()
    chevron = _asset("chevron", _chevron(C.TEXT_2))
    chevron_off = _asset("chevron-off", _chevron(C.TEXT_DISABLED))
    check = _asset("check", _check(C.ON_ACCENT))
    states = _state_rules()
    icons = T.icons()
    return f"""
* {{ font-family: "{ui}"; font-size: {T.BODY}px; color: {C.TEXT}; outline: 0; }}
QWidget#appRoot, QDialog {{ background: {C.BG}; }}
QWidget {{ background: transparent; }}
QToolTip {{ background: {C.RAISED_HOVER}; color: {C.TEXT}; border: 1px solid {C.BORDER_STRONG};
            padding: 6px 9px; border-radius: {R.SM}px; font-size: {T.SMALL}px; }}

/* ---------- text roles ---------- */
QLabel#display {{ font-family: "{disp}"; font-size: {T.DISPLAY}px; font-weight: 600; }}
QLabel#pageTitle {{ font-family: "{disp}"; font-size: {T.H1}px; font-weight: 600; }}
QLabel#h2 {{ font-family: "{disp}"; font-size: {T.H2}px; font-weight: 600; }}
QLabel#sectionTitle {{ font-size: {T.TITLE}px; font-weight: 600; }}
QLabel#overline {{ font-size: {T.CAPTION}px; font-weight: 600; color: {C.TEXT_3}; }}
QLabel#body {{ font-size: {T.BODY}px; color: {C.TEXT}; }}
QLabel#muted {{ color: {C.TEXT_2}; }}
QLabel#hint, QLabel#subtle {{ color: {C.TEXT_3}; font-size: {T.SMALL}px; }}
QLabel#warning {{ color: {C.WARNING}; }}
QLabel#error {{ color: {C.DANGER}; }}
QLabel#ok {{ color: {C.SUCCESS}; }}
QLabel#mono {{ font-family: "{mono}"; font-size: {T.SMALL}px; color: {C.TEXT_2}; }}
QLabel#glyph {{ font-family: "{T.icons()}"; font-size: 16px; color: {C.TEXT_2}; }}
QLabel#keycap {{ background: {C.RAISED}; border: 1px solid {C.BORDER_STRONG}; border-bottom: 2px solid #0A0C0F;
                 border-radius: {R.SM}px; padding: 2px 9px; font-size: {T.SMALL}px; font-weight: 600;
                 color: {C.TEXT}; min-height: 18px; }}
QLabel#keycapLarge {{ background: {C.RAISED}; border: 1px solid {C.BORDER_STRONG}; border-bottom: 3px solid #0A0C0F;
                 border-radius: {R.MD}px; padding: 4px 14px; font-size: {T.BODY_LG}px; font-weight: 600; }}
QLabel#link {{ color: {C.ACCENT}; }}
QLabel#value, QLabel#tileTitle, QLabel#strong {{ font-weight: 600; }}
QLabel#dangerTitle {{ font-size: {T.TITLE}px; font-weight: 600; color: #FF9B9B; }}

/* ---------- components (state via dynamic properties) ---------- */
QFrame#banner {{ border-radius: {R.MD}px; }}
QLabel#bannerIcon {{ font-family: "{icons}"; font-size: 16px; padding-top: 1px; }}
QLabel#bannerText {{ color: {C.TEXT}; }}
QFrame#statusPill {{ background: {C.RAISED}; border: 1px solid {C.BORDER}; border-radius: 13px; }}
QLabel#pillDot {{ background: {C.TEXT_3}; border-radius: 4px; }}
QLabel#pillText {{ font-size: {T.SMALL}px; color: {C.TEXT}; }}
QLabel#savedIndicator {{ font-size: {T.SMALL}px; background: {C.RAISED}; border: 1px solid {C.BORDER};
                         border-radius: 12px; padding: 0 11px; color: {C.TEXT_2}; }}
QLabel#tileBadge, QLabel#sourceBadge {{ background: {C.RAISED}; border: 1px solid {C.BORDER}; border-radius: {R.MD}px;
                                        color: {C.ACCENT}; font-family: "{icons}"; font-size: 16px; }}
QLabel#sourceBadge {{ background: {C.ACCENT_SOFT}; border: none; }}
QLabel#choiceBadge {{ background: {C.ACCENT_SOFT}; color: {C.ACCENT}; border-radius: 9px; padding: 0 8px;
                      font-size: {T.CAPTION}px; font-weight: 600; }}
QLabel#choiceMark {{ border: 2px solid #3A4150; border-radius: 9px; background: transparent; }}
QLabel#choiceMark[selected="true"] {{ border: 5px solid {C.ACCENT}; background: {C.ON_ACCENT}; }}
QLabel#stepNumber {{ background: {C.ACCENT_SOFT}; color: {C.ACCENT}; border-radius: 12px; font-weight: 700;
                     font-size: {T.SMALL}px; }}
QLabel#dialogBadge {{ font-family: "{icons}"; font-size: 18px; border-radius: 20px; }}
QLabel#dialogTitle {{ font-size: {T.TITLE + 1}px; font-weight: 600; }}
QLabel#statusChip {{ border-radius: 12px; padding: 0 10px; font-size: {T.SMALL}px; font-weight: 600;
                     color: {C.TEXT_2}; background: {C.RAISED}; }}
QPushButton#chip {{ background: {C.RAISED}; border: 1px solid {C.BORDER}; border-radius: 14px; min-height: 26px;
                    padding: 0 12px; font-size: {T.SMALL}px; color: {C.TEXT}; }}
QPushButton#chip:hover {{ background: {C.RAISED_HOVER}; border-color: {C.BORDER_STRONG}; }}
QPushButton#chip:focus {{ border: 1px solid {C.ACCENT_LINE}; }}
QFrame#inset {{ background: {C.BG}; border: 1px solid {C.BORDER}; border-radius: {R.LG}px; }}

/* ---------- toast ---------- */
QFrame#toastCard {{ background: {C.SURFACE}; border: 1px solid {C.BORDER_STRONG}; border-radius: {R.XL - 2}px; }}
QLabel#toastTitle {{ font-weight: 600; font-size: {T.BODY}px; color: {C.TEXT}; }}
QLabel#toastBody {{ color: {C.TEXT_2}; font-size: {T.SMALL}px; }}
QLabel#toastIcon {{ font-family: "{icons}"; font-size: 15px; border-radius: 15px; }}
QPushButton#toastAction {{ background: {C.RAISED}; border: 1px solid {C.BORDER_STRONG}; color: {C.TEXT};
                           padding: 0 10px; min-height: 24px; border-radius: {R.SM}px;
                           font-size: {T.SMALL}px; font-weight: 600; }}
QPushButton#toastAction:hover {{ background: {C.RAISED_HOVER}; }}
QPushButton#toastClose {{ background: transparent; border: none; color: {C.TEXT_3}; min-height: 20px;
                          padding: 0 4px; font-family: "{icons}"; font-size: 10px; }}
QPushButton#toastClose:hover {{ color: {C.TEXT}; }}

/* ---------- capture overlay toolbar ---------- */
QWidget#overlayToolbar {{ background: rgba(16, 18, 23, 240); border: 1px solid {C.BORDER_STRONG};
                          border-radius: {R.XL}px; }}
QWidget#overlayToolbar QToolButton {{ color: {C.TEXT_2}; padding: 5px 11px; border-radius: {R.MD}px; border: none;
                                      font-size: {T.SMALL + 1}px; }}
QWidget#overlayToolbar QToolButton:hover {{ background: {C.RAISED_HOVER}; color: {C.TEXT}; }}
QWidget#overlayToolbar QToolButton:checked {{ background: {C.ACCENT_SOFT}; color: {C.ACCENT}; font-weight: 600; }}
QWidget#overlayToolbar QLabel {{ color: {C.TEXT_3}; font-size: {T.CAPTION + 1}px; }}
QWidget#overlaySep {{ background: {C.BORDER_STRONG}; }}

{states}

/* ---------- navigation ---------- */
QFrame#sidebar {{ background: {C.SIDEBAR}; border-right: 1px solid {C.BORDER}; }}
QPushButton#navItem {{ background: transparent; border: none; border-radius: {R.MD}px; text-align: left;
                       padding: 0 12px; min-height: 34px; color: {C.TEXT_2}; font-size: {T.BODY}px; }}
QPushButton#navItem:hover {{ background: {C.SURFACE_HOVER}; color: {C.TEXT}; }}
QPushButton#navItem:checked {{ color: {C.TEXT}; font-weight: 600; }}
QPushButton#navItem:checked:hover {{ background: transparent; }}
QPushButton#navItem:focus {{ border: 1px solid {C.ACCENT_LINE}; }}
QWidget#navIndicator {{ background: {C.RAISED}; border-radius: {R.MD}px; border: 1px solid {C.BORDER}; }}
QWidget#navMarker {{ background: {C.ACCENT}; border-radius: 1px; }}

/* ---------- surfaces ---------- */
QFrame#card {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; border-radius: {R.LG}px; }}
QFrame#hero {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #151C24, stop:1 #12161C);
               border: 1px solid #22303A; border-radius: {R.XL}px; }}
QFrame#dangerCard {{ background: {C.SURFACE}; border: 1px solid rgba(240, 106, 106, 0.35); border-radius: {R.LG}px; }}
QFrame#divider {{ background: {C.BORDER}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#tile {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; border-radius: {R.LG}px; }}
QFrame#tile:hover {{ background: {C.SURFACE_HOVER}; border-color: {C.BORDER_STRONG}; }}
QFrame#tile:focus, QFrame#choice:focus {{ border: 1px solid {C.ACCENT}; }}
QFrame#choice {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; border-radius: {R.LG}px; }}
QFrame#choice:hover {{ border-color: {C.BORDER_STRONG}; background: {C.SURFACE_HOVER}; }}
QFrame#choice[selected="true"] {{ border: 1px solid {C.ACCENT_LINE}; background: {C.ACCENT_SOFT}; }}
QFrame#codeBox {{ background: #0A0C10; border: 1px solid {C.BORDER}; border-radius: {R.MD}px; }}

/* ---------- buttons ---------- */
QPushButton {{ background: {C.RAISED}; border: 1px solid {C.BORDER_STRONG}; border-radius: {R.MD}px;
               padding: 0 14px; min-height: {H.MD - 2}px; color: {C.TEXT}; font-weight: 500; }}
QPushButton:hover {{ background: {C.RAISED_HOVER}; border-color: #3A4150; }}
QPushButton:pressed {{ background: {C.RAISED_PRESSED}; }}
QPushButton:focus {{ border: 1px solid {C.ACCENT}; }}
QPushButton:disabled {{ color: {C.TEXT_DISABLED}; background: {C.SURFACE}; border-color: {C.BORDER}; }}
QPushButton#primary, QPushButton#hero {{ background: {C.ACCENT}; border: 1px solid {C.ACCENT}; color: {C.ON_ACCENT};
                                          font-weight: 600; }}
QPushButton#primary:hover, QPushButton#hero:hover {{ background: {C.ACCENT_HOVER}; border-color: {C.ACCENT_HOVER}; }}
QPushButton#primary:pressed, QPushButton#hero:pressed {{ background: {C.ACCENT_PRESSED}; }}
QPushButton#primary:focus, QPushButton#hero:focus {{ border: 1px solid #C9F1FC; }}
QPushButton#primary:disabled, QPushButton#hero:disabled {{ background: {C.RAISED}; color: {C.TEXT_DISABLED};
                                                            border-color: {C.BORDER}; }}
QPushButton#hero {{ min-height: {H.LG}px; padding: 0 22px; font-size: {T.BODY_LG}px; border-radius: {R.LG}px; }}
QPushButton#ghost, QPushButton#link {{ background: transparent; border: 1px solid transparent; }}
QPushButton#ghost {{ color: {C.TEXT_2}; padding: 0 10px; }}
QPushButton#ghost:hover {{ background: {C.RAISED}; color: {C.TEXT}; }}
QPushButton#ghost:pressed {{ background: {C.RAISED_HOVER}; }}
QPushButton#link {{ color: {C.ACCENT}; padding: 0 2px; min-height: 22px; font-weight: 500; }}
QPushButton#link:hover {{ color: {C.ACCENT_HOVER}; }}
QPushButton#link:focus, QPushButton#ghost:focus {{ border: 1px solid {C.ACCENT_LINE}; }}
QPushButton#danger {{ background: {C.DANGER_SOFT}; border: 1px solid rgba(240, 106, 106, 0.45); color: #FF9B9B; }}
QPushButton#danger:hover {{ background: rgba(240, 106, 106, 0.18); border-color: {C.DANGER}; color: #FFC2C2; }}
QPushButton#danger:pressed {{ background: rgba(240, 106, 106, 0.26); }}
QPushButton#danger:focus {{ border: 1px solid {C.DANGER}; }}
QPushButton#danger:disabled {{ background: transparent; border-color: {C.BORDER}; color: {C.TEXT_DISABLED}; }}
QPushButton#ghost:disabled, QPushButton#link:disabled {{ background: transparent; border-color: transparent;
                                                         color: {C.TEXT_DISABLED}; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: {R.SM}px; padding: 4px 8px;
               color: {C.TEXT_2}; }}
QToolButton:hover {{ background: {C.RAISED}; color: {C.TEXT}; }}
QToolButton:pressed {{ background: {C.RAISED_HOVER}; }}
QToolButton:checked {{ background: {C.ACCENT_SOFT}; color: {C.ACCENT}; }}
QToolButton:focus {{ border: 1px solid {C.ACCENT_LINE}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {C.RAISED}; border: 1px solid {C.BORDER_STRONG};
    border-radius: {R.MD}px; padding: 0 10px; min-height: {H.MD - 2}px; selection-background-color: {C.ACCENT};
    selection-color: {C.ON_ACCENT}; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: #3A4150; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QComboBox:on {{ border: 1px solid {C.ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {C.TEXT_DISABLED};
    background: {C.SURFACE}; border-color: {C.BORDER}; }}
QLineEdit[readOnly="true"] {{ background: {C.SURFACE}; color: {C.TEXT_2}; }}
QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url("{chevron_off}"); }}
QComboBox QAbstractItemView {{ background: {C.RAISED}; border: 1px solid {C.BORDER_STRONG}; border-radius: {R.MD}px;
    padding: 4px; selection-background-color: {C.RAISED_HOVER}; selection-color: {C.TEXT}; outline: 0; }}
QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 0 8px; border-radius: {R.SM}px; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 6px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button
    {{ width: 0; border: none; }}

QPlainTextEdit, QTextEdit, QListWidget {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; border-radius: {R.LG}px;
    padding: 6px; selection-background-color: rgba(69, 200, 236, 0.35); selection-color: {C.TEXT}; }}
QPlainTextEdit:focus, QTextEdit:focus, QListWidget:focus {{ border: 1px solid {C.ACCENT_LINE}; }}
QListWidget#historyList {{ padding: 4px; }}
QPlainTextEdit#mono {{ font-family: "{mono}"; font-size: {T.SMALL}px; color: {C.TEXT_2}; background: #0A0C10; }}
QListWidget#historyList::item {{ padding: 10px 10px; border-radius: {R.MD}px; margin: 1px 0; color: {C.TEXT}; }}
QListWidget#historyList::item:hover {{ background: {C.SURFACE_HOVER}; }}
QListWidget#historyList::item:selected {{ background: {C.ACCENT_SOFT}; color: {C.TEXT}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; background: {C.RAISED};
                        border: 1px solid #3A4150; }}
QCheckBox::indicator:hover {{ border-color: {C.ACCENT_LINE}; }}
QCheckBox::indicator:checked {{ background: {C.ACCENT}; border-color: {C.ACCENT}; image: url("{check}"); }}
QCheckBox::indicator:disabled {{ background: {C.SURFACE}; border-color: {C.BORDER}; }}
QCheckBox:focus {{ color: {C.TEXT}; }}
QRadioButton {{ spacing: 10px; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; background: {C.RAISED};
                           border: 1px solid #3A4150; }}
QRadioButton::indicator:checked {{ background: {C.ON_ACCENT}; border: 4px solid {C.ACCENT}; width: 8px; height: 8px; }}

QSlider {{ min-height: 22px; }}
QSlider::groove:horizontal {{ height: 4px; background: {C.RAISED_HOVER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {C.ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #F4F6F9; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
                              border: 1px solid #0A0C0F; }}
QSlider::handle:horizontal:hover {{ background: #FFFFFF; border: 2px solid {C.ACCENT}; }}
QSlider:focus {{ border: none; }}
QSlider::handle:horizontal:focus {{ border: 2px solid {C.ACCENT}; }}
QProgressBar {{ background: {C.RAISED_HOVER}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px;
                color: transparent; }}
QProgressBar::chunk {{ background: {C.ACCENT}; border-radius: 3px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {C.RAISED_HOVER}; border-radius: 4px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: #3A4150; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: {C.RAISED_HOVER}; border-radius: 4px; min-width: 36px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {C.RAISED}; border: 1px solid {C.BORDER_STRONG}; border-radius: {R.LG}px; padding: 6px; }}
QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: {R.SM}px; color: {C.TEXT}; }}
QMenu::item:selected {{ background: {C.RAISED_HOVER}; }}
QMenu::item:disabled {{ color: {C.TEXT_DISABLED}; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::separator {{ height: 1px; background: {C.BORDER}; margin: 5px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 8px; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in [
        (QPalette.ColorRole.Window, C.BG), (QPalette.ColorRole.Base, C.SURFACE),
        (QPalette.ColorRole.AlternateBase, C.RAISED), (QPalette.ColorRole.Text, C.TEXT),
        (QPalette.ColorRole.WindowText, C.TEXT), (QPalette.ColorRole.Button, C.RAISED),
        (QPalette.ColorRole.ButtonText, C.TEXT), (QPalette.ColorRole.Highlight, C.ACCENT),
        (QPalette.ColorRole.HighlightedText, C.ON_ACCENT), (QPalette.ColorRole.ToolTipBase, C.RAISED_HOVER),
        (QPalette.ColorRole.ToolTipText, C.TEXT), (QPalette.ColorRole.PlaceholderText, C.TEXT_3),
        (QPalette.ColorRole.Link, C.ACCENT), (QPalette.ColorRole.Mid, C.BORDER),
    ]:
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(C.TEXT_DISABLED))
    app.setPalette(pal)
    app.setFont(font(T.BODY))
    app.setStyleSheet(stylesheet())
    app.setWindowIcon(app_icon())


# ----------------------------------------------------------------------------- logo
def paint_logo(size: int) -> QPixmap:
    """The TextSnap mark: cyan selection brackets around a white T on a graphite tile."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(s * 0.03, s * 0.03, s * 0.94, s * 0.94), s * 0.24, s * 0.24)
    p.fillPath(tile, QColor("#151A21"))
    if size >= 24:
        p.setPen(QPen(QColor("#2C3642"), max(1.0, s * 0.02)))
        p.drawPath(tile)
    pen = QPen(QColor(C.ACCENT), max(1.4, s * 0.075))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    a, b, c = s * 0.22, s * 0.78, s * 0.17
    for x, y, dx, dy in [(a, a, 1, 1), (b, a, -1, 1), (a, b, 1, -1), (b, b, -1, -1)]:
        path = QPainterPath(QPointF(x + dx * c, y))
        path.lineTo(QPointF(x, y))
        path.lineTo(QPointF(x, y + dy * c))
        p.drawPath(path)
    pen = QPen(QColor("#F3F6F9"), max(1.6, s * 0.09))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(s * 0.38, s * 0.40), QPointF(s * 0.62, s * 0.40))
    p.drawLine(QPointF(s * 0.5, s * 0.40), QPointF(s * 0.5, s * 0.63))
    p.end()
    return pm


_icon: QIcon | None = None


def app_icon() -> QIcon:
    global _icon
    if _icon is None:
        ico = paths.assets_dir() / "textsnap.ico"
        if ico.exists():
            _icon = QIcon(str(ico))
        else:
            _icon = QIcon()
            for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
                _icon.addPixmap(paint_logo(size))
    return _icon


def logo_pixmap(px: int) -> QPixmap:
    dpr = _dpr()
    pm = paint_logo(round(px * dpr))
    pm.setDevicePixelRatio(dpr)
    return pm


def icon_size(px: int = 16) -> QSize:
    return QSize(px, px)
