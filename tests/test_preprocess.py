from __future__ import annotations

import numpy as np
import pytest

from textsnap.ocr import preprocess as pp
from textsnap.ocr import samples


def test_to_gray_and_otsu():
    rgb = np.zeros((10, 10, 3), np.uint8)
    rgb[:, 5:] = 255
    g = pp.to_gray(rgb)
    assert g.dtype == np.uint8 and g.shape == (10, 10)
    t = pp.otsu_threshold(g)
    assert int((g <= t).sum()) == 50  # splits the two halves exactly


def test_blank_detection():
    assert pp.is_blank(np.full((100, 100), 240, np.uint8))
    img = np.full((100, 300), 255, np.uint8)
    img[40:52, 10:60] = 0  # one small word in a large area must not count as blank
    assert not pp.is_blank(img)


def test_dark_background_is_inverted(render):
    rgb = render(samples.ENGLISH, fg=(230, 230, 230), bg=(20, 20, 20))
    prepared = pp.prepare(rgb)
    assert prepared.inverted
    assert np.median(prepared.image) > 200  # light background after inversion
    assert not pp.prepare(render(samples.ENGLISH)).inverted


def test_line_height_and_scale(render):
    lh, lines = pp.estimate_line_height(pp.to_gray(render(samples.ENGLISH, px=10)))
    assert lines == 2 and 6 <= lh <= 16
    assert pp.choose_scale(lh) >= 1.5
    assert pp.choose_scale(30) == 1.0
    assert pp.choose_scale(None) == 1.0
    assert pp.choose_scale(400) < 1.0  # huge text is reduced


def test_small_text_upscaled(render):
    prepared = pp.prepare(render(samples.ENGLISH, px=10))
    assert prepared.scale >= 1.5
    assert prepared.image.shape[0] > render(samples.ENGLISH, px=10).shape[0]


def test_edge_lines_and_margins_removed():
    img = np.full((60, 200), 255, np.uint8)
    img[0, :] = 0  # border line hugging the selection edge
    img[:, -1] = 0
    img[25:35, 50:150] = 0  # "text"
    out = pp.trim_margins(pp.remove_edge_lines(img))
    assert out[0].mean() > 200 and out[:, -1].mean() > 200
    assert out.shape[0] < 30 and out.shape[1] < 120


def test_preprocessing_off_keeps_pixels():
    img = np.full((40, 80, 3), 90, np.uint8)
    img[10:20, 10:30] = 255
    prepared = pp.prepare(img, strength="off")
    inner = prepared.image[pp.PAD_PX:-pp.PAD_PX, pp.PAD_PX:-pp.PAD_PX]
    assert inner.shape == (40, 80) and not prepared.inverted
    assert np.array_equal(inner, pp.to_gray(img))


def test_sauvola_output_binary(render):
    out = pp.sauvola(pp.to_gray(render(samples.ENGLISH)))
    assert set(np.unique(out)) <= {0, 255}


@pytest.mark.parametrize("angle", [3.0, -2.5])
def test_deskew_estimate_and_correction(render, angle):
    gray = pp.to_gray(render(samples.ENGLISH * 3, px=18))
    tilted = pp.rotate(gray, angle)
    est = pp.deskew_angle(tilted)
    assert abs(abs(est) - abs(angle)) < 0.6
    straightened = pp.rotate(tilted, -est)
    assert abs(pp.deskew_angle(straightened)) < 0.5


def test_best_channel_for_colored_text():
    rgb = np.zeros((40, 120, 3), np.uint8)
    rgb[...] = (40, 160, 40)  # green background
    rgb[15:25, 20:100] = (200, 60, 40)  # red text with similar luminance
    ch = pp.best_channel(rgb)
    assert ch is not None


def test_thorough_variants(render):
    variants = pp.thorough_variants(render(samples.ENGLISH))
    names = [v.name for v in variants]
    assert names[0] == "standard" and "adaptive threshold" in names and len(variants) >= 3
    for v in variants:
        assert v.image.dtype == np.uint8 and v.image.ndim == 2
