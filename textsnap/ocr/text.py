"""Turning recognised words into text, plus text helpers.

All text stays in logical (reading) order, exactly as Unicode expects. RTL
display is the job of the text widget's bidi algorithm; nothing here ever
reverses a Hebrew string for display.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from textsnap.ocr.engine import Word

# Directional formatting characters Tesseract inserts around runs (LRM/RLM,
# embeddings, isolates). Invisible, but they break searches and code.
BIDI_CONTROLS = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u061c"))


def strip_bidi_controls(text: str) -> str:
    return text.translate(BIDI_CONTROLS)


def is_hebrew_char(ch: str) -> bool:
    return "֐" <= ch <= "׿" or "יִ" <= ch <= "ﭏ"


def is_latin_letter(ch: str) -> bool:
    return ch.isascii() and ch.isalpha() or ("À" <= ch <= "ɏ" and ch.isalpha())


def script_counts(text: str) -> tuple[int, int]:
    """(Hebrew letters, Latin letters)."""
    heb = sum(1 for c in text if is_hebrew_char(c) and unicodedata.category(c).startswith("L"))
    lat = sum(1 for c in text if is_latin_letter(c))
    return heb, lat


def text_direction(text: str) -> str:
    """'rtl', 'ltr', 'mixed' or 'none' - used for display hints only."""
    heb, lat = script_counts(text)
    if not heb and not lat:
        return "none"
    if heb and lat:
        if heb >= lat * 4:
            return "rtl"
        if lat >= heb * 4:
            return "ltr"
        return "mixed"
    return "rtl" if heb else "ltr"


def word_class(text: str) -> str:
    """'R' (Hebrew), 'L' (Latin letters or digits) or 'N' (neutral)."""
    t = strip_bidi_controls(text)
    if any(is_hebrew_char(c) for c in t):
        return "R"
    if any(is_latin_letter(c) or c.isdigit() for c in t):
        return "L"
    return "N"


def order_line(words: list[Word], rtl: bool) -> list[Word]:
    """Logical order for one line from word positions (two-level bidi).

    For an RTL line words are read right to left, but each run of LTR words
    (Latin, digits) keeps its internal left-to-right order. Neutral words
    between two LTR words join the LTR run; otherwise they follow the line
    direction. The LTR case is the mirror image.
    """
    if not words:
        return []
    visual = sorted(words, key=lambda w: w.left)  # left to right
    classes = [word_class(w.text) for w in visual]
    strong_line = "R" if rtl else "L"
    strong_other = "L" if rtl else "R"
    resolved = []
    for i, c in enumerate(classes):
        if c != "N":
            resolved.append(c)
            continue
        prev = next((classes[j] for j in range(i - 1, -1, -1) if classes[j] != "N"), None)
        nxt = next((classes[j] for j in range(i + 1, len(classes)) if classes[j] != "N"), None)
        resolved.append(strong_other if prev == nxt == strong_other else strong_line)
    # Group visual runs of the same resolved direction.
    runs: list[tuple[str, list[Word]]] = []
    for w, c in zip(visual, resolved):
        if runs and runs[-1][0] == c:
            runs[-1][1].append(w)
        else:
            runs.append((c, [w]))
    if rtl:
        runs.reverse()  # rightmost run is read first
    out: list[Word] = []
    for c, run in runs:
        out.extend(reversed(run) if c == "R" else run)
    return out


def line_is_rtl(words: list[Word]) -> bool:
    """Base direction of a line: the script with more letters wins (ties: RTL)."""
    heb, lat = script_counts(" ".join(w.text for w in words))
    return heb >= lat and heb > 0


def reorder_mixed_lines(words: list[Word]) -> list[Word]:
    """Re-derive logical order for lines that mix Hebrew and Latin/digits.

    Tesseract sometimes emits a mostly-Hebrew line in left-to-right order.
    Single-script lines are left exactly as recognised.
    """
    out: list[Word] = []
    for line in group_lines(words):
        classes = {word_class(w.text) for w in line.words}
        if {"R", "L"} <= classes:
            out.extend(order_line(line.words, line_is_rtl(line.words)))
        else:
            out.extend(line.words)
    return out


@dataclass
class Line:
    words: list[Word]
    block: int
    par: int

    @property
    def top(self) -> int:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> int:
        return max(w.bottom for w in self.words)

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def text(self, strip_bidi: bool) -> str:
        return join_words([w.text for w in self.words], strip_bidi)


# A Hebrew prefix with a hyphen ("ה-", "ול-") attaches to the next word.
_PREFIX_HYPHEN = re.compile(r"^[בהוכלמש]{1,3}-$")


def join_words(words: list[str], strip_bidi: bool = True) -> str:
    out = ""
    for raw in words:
        word = raw.strip()
        if not word:
            continue
        if out and not _PREFIX_HYPHEN.match(strip_bidi_controls(out.rsplit(" ", 1)[-1])):
            out += " "
        out += word
    return strip_bidi_controls(out) if strip_bidi else out


def group_lines(words: list[Word]) -> list[Line]:
    lines: dict[tuple[int, int, int], Line] = {}
    for w in words:
        key = (w.block, w.par, w.line)
        if key not in lines:
            lines[key] = Line([], w.block, w.par)
        lines[key].words.append(w)
    return list(lines.values())


def assemble(words: list[Word], preserve_line_breaks: bool = True, strip_bidi: bool = True) -> str:
    """Words (in Tesseract reading order) -> text with lines and paragraphs.

    Lines are separated by newlines. A blank line marks a new block, or a new
    paragraph that is also visually separated by a gap larger than ~0.8 of
    the line height, so tightly set paragraphs do not gain blank lines.
    With ``preserve_line_breaks`` off, lines within a paragraph are joined.
    """
    lines = group_lines(words)
    if not lines:
        return ""
    heights = sorted(line.height for line in lines)
    typical = max(1, heights[len(heights) // 2])
    paragraphs: list[list[str]] = [[]]
    prev: Line | None = None
    for line in lines:
        text = line.text(strip_bidi)
        if not text:
            continue
        if prev is not None:
            new_block = line.block != prev.block
            gap = line.top - prev.bottom
            new_par = line.par != prev.par and gap > typical * 0.8
            if new_block or new_par or gap > typical * 1.6:
                paragraphs.append([])
        paragraphs[-1].append(text)
        prev = line
    joiner = "\n" if preserve_line_breaks else " "
    return "\n\n".join(joiner.join(p) for p in paragraphs if p)


# ---------------------------------------------------------------- cleanup
_MULTISPACE = re.compile(r"[ \t\u00a0]{2,}")  # spaces, tabs, no-break spaces
_BLANKS = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Remove excess whitespace; keep every character, line and paragraph break."""
    lines = [_MULTISPACE.sub(" ", line).strip() for line in text.replace("\r\n", "\n").split("\n")]
    out = "\n".join(lines).strip("\n")
    return _BLANKS.sub("\n\n", out)


def join_lines(text: str) -> str:
    """Re-flow hard-wrapped lines into paragraphs (blank lines separate paragraphs)."""
    paragraphs = re.split(r"\n\s*\n", clean_text(text))
    return "\n\n".join(" ".join(p.split("\n")) for p in paragraphs if p.strip())


# ---------------------------------------------------------------- detection
_URL = re.compile(r"\b((?:https?://|www\.)[^\s<>\"'א-ת]+)", re.IGNORECASE)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}\b")
_TRAILING = ".,;:!?)]}'\""


def find_urls(text: str) -> list[str]:
    found: list[str] = []
    for m in _URL.finditer(strip_bidi_controls(text)):
        url = m.group(1).rstrip(_TRAILING)
        if url.lower().startswith("www."):
            url = "https://" + url
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme in ("http", "https") and "." in host and not host.startswith(".") and url not in found:
            found.append(url)
    return found


def find_emails(text: str) -> list[str]:
    found: list[str] = []
    for m in _EMAIL.finditer(strip_bidi_controls(text)):
        if m.group(0) not in found:
            found.append(m.group(0))
    return found
