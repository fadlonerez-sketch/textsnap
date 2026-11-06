"""Text assembly, bidi ordering and cleanup helpers (no OCR engine needed)."""

from __future__ import annotations

from textsnap.ocr import text as tx
from textsnap.ocr.engine import Word, encode_pnm, parse_tsv


def w(text, left, top=0, width=40, height=12, block=1, par=1, line=1, conf=90.0):
    return Word(text, conf, left, top, width, height, block, par, line, 0)


def test_strip_bidi_controls_keeps_text():
    s = "הפגישה \u200eMicrosoft\u200f תתקיים"
    assert tx.strip_bidi_controls(s) == "הפגישה Microsoft תתקיים"


def test_assemble_lines_and_paragraphs():
    words = [w("Hello", 0, 0, line=1), w("world", 50, 0, line=1),
             w("Second", 0, 18, line=2),
             w("New", 0, 60, par=2, line=1), w("para", 50, 60, par=2, line=1)]
    assert tx.assemble(words) == "Hello world\nSecond\n\nNew para"
    assert tx.assemble(words, preserve_line_breaks=False) == "Hello world Second\n\nNew para"


def test_assemble_tight_paragraph_does_not_gain_blank_line():
    words = [w("a", 0, 0, par=1), w("b", 0, 16, par=2)]
    assert tx.assemble(words) == "a\nb"


def test_order_rtl_line_with_latin_run():
    # Visual (left to right): Microsoft | עם | הפגישה  -> logical: הפגישה עם Microsoft
    words = [w("Microsoft", 0), w("עם", 60), w("הפגישה", 100)]
    assert [x.text for x in tx.order_line(words, rtl=True)] == ["הפגישה", "עם", "Microsoft"]


def test_order_rtl_line_keeps_ltr_run_internal_order():
    # Visual: Google Drive | ל-  ... logical: ל- Google Drive
    words = [w("Google", 0), w("Drive", 50), w("ל-", 100), w("שלחתי", 140)]
    out = [x.text for x in tx.order_line(words, rtl=True)]
    assert out == ["שלחתי", "ל-", "Google", "Drive"]
    assert tx.join_words(out) == "שלחתי ל-Google Drive"


def test_order_ltr_line_with_hebrew_run():
    words = [w("Hello", 0), w("עולם", 50), w("שלום", 90), w("there", 140)]
    assert [x.text for x in tx.order_line(words, rtl=False)] == ["Hello", "שלום", "עולם", "there"]


def test_neutral_between_latin_joins_latin_run():
    words = [w("A", 0), w("-", 20), w("B", 40), w("שלום", 80)]
    assert [x.text for x in tx.order_line(words, rtl=True)] == ["שלום", "A", "-", "B"]


def test_reorder_mixed_lines_only_touches_mixed_lines():
    english = [w("one", 0, line=1), w("two", 50, line=1)]
    # Mostly Hebrew -> RTL line: read right to left, Latin run kept intact.
    mixed = [w("OK", 0, 20, line=2), w("שלום", 80, 20, line=2), w("עולם", 130, 20, line=2)]
    out = tx.reorder_mixed_lines(english + list(reversed(mixed)))
    assert [x.text for x in out] == ["one", "two", "עולם", "שלום", "OK"]
    # Mostly Latin -> LTR line.
    latin = [w("Microsoft", 0, 20, line=2), w("שלום", 80, 20, line=2)]
    assert [x.text for x in tx.reorder_mixed_lines(list(reversed(latin)))] == ["Microsoft", "שלום"]


def test_line_direction_by_majority():
    assert tx.line_is_rtl([w("שלום", 0), w("עולם", 50), w("OK", 100)])
    assert not tx.line_is_rtl([w("Hello", 0), w("world", 50), w("שלום", 100)])


def test_join_words_attaches_hebrew_prefix():
    assert tx.join_words(["לגבי", "ה-", "API"]) == "לגבי ה-API"
    assert tx.join_words(["a", "-", "b"]) == "a - b"


def test_text_direction():
    assert tx.text_direction("שלום עולם") == "rtl"
    assert tx.text_direction("hello") == "ltr"
    assert tx.text_direction("שלום hello") == "mixed"
    assert tx.text_direction("123 !!") == "none"


def test_clean_text_preserves_content():
    raw = "  Line   one  \n\n\n\nLine\ttwo  three\r\n 123,45 !  "
    cleaned = tx.clean_text(raw)
    assert cleaned == "Line one\n\nLine\ttwo three\n123,45 !"  # a single tab may separate columns
    # nothing meaningful was dropped
    for token in ["Line", "one", "two", "three", "123,45", "!"]:
        assert token in cleaned


def test_clean_text_keeps_hebrew_and_punctuation():
    assert tx.clean_text("שלום,   עולם!\n\n\n\nמה  נשמע?") == "שלום, עולם!\n\nמה נשמע?"


def test_join_lines():
    assert tx.join_lines("first line\nsecond line\n\nnext para") == "first line second line\n\nnext para"


def test_find_urls_and_emails():
    text = "Visit https://example.com/path?q=1, or www.test.org. Mail me: dev.team+x@mail.co.il!"
    assert tx.find_urls(text) == ["https://example.com/path?q=1", "https://www.test.org"]
    assert tx.find_emails(text) == ["dev.team+x@mail.co.il"]
    assert tx.find_urls("no links here, file.txt") == []
    assert tx.find_urls("javascript:alert(1)") == []


def test_url_stops_at_hebrew():
    assert tx.find_urls("ראו https://example.com/a שם") == ["https://example.com/a"]


def test_parse_tsv():
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "1\t1\t0\t0\t0\t0\t0\t0\t100\t50\t-1\t\n"
           "5\t1\t1\t1\t1\t1\t10\t5\t30\t12\t91.5\tשלום\n"
           "5\t1\t1\t1\t1\t2\t50\t5\t30\t12\t88\tworld\n"
           "5\t1\t1\t1\t1\t3\t90\t5\t3\t12\t95\t \n")
    words = parse_tsv(tsv)
    assert [(x.text, x.conf, x.left) for x in words] == [("שלום", 91.5, 10), ("world", 88.0, 50)]


def test_encode_pnm():
    import numpy as np
    gray = np.zeros((2, 3), np.uint8)
    assert encode_pnm(gray).startswith(b"P5\n3 2\n255\n") and len(encode_pnm(gray)) == 11 + 6
    rgb = np.zeros((2, 3, 3), np.uint8)
    assert encode_pnm(rgb).startswith(b"P6\n3 2\n255\n")
