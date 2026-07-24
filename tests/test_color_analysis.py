"""Color analysis: pure-function tests using synthetic frames."""

import importlib

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

color = importlib.import_module("film_style_analyzer.color_analysis")


def _solid(rgb):
    """Build a 32x32 BGR frame with a solid color."""
    r, g, b = rgb
    frame = np.zeros((32, 32, 3), dtype=np.uint8)
    frame[..., 0] = b
    frame[..., 1] = g
    frame[..., 2] = r
    return frame


def test_kmeans_palette_returns_dominant_color_first():
    # 75% red + 25% blue.
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    frame[:, :30, 2] = 200  # red region (R high)
    frame[:, 30:, 0] = 200  # blue region (B high)
    palette = color._kmeans_palette(frame, k=2)
    weights = sorted([p["weight"] for p in palette], reverse=True)
    assert weights[0] > weights[1]
    # Top palette entry should weight ≈ 0.75
    assert palette[0]["weight"] > 0.6


def test_warm_cool_index_warm_image_positive():
    warm = _solid((255, 120, 30))
    assert color._warm_cool_index(warm) > 0.4


def test_warm_cool_index_cool_image_negative():
    cool = _solid((30, 60, 200))
    assert color._warm_cool_index(cool) < -0.4


def test_tone_label_low_key_warm_desaturated():
    label = color._tone_label(wc=0.4, lum=50, sat=40)
    assert "low-key" in label
    assert "warm" in label
    assert "desaturated" in label


def test_aggregate_palette_combines_weights():
    a = color.ClipColor(
        palette=[{"hex": "#aa0000", "weight": 0.6}, {"hex": "#0000aa", "weight": 0.4}],
        mean_luminance=120,
        luminance_std=30,
        warm_cool=0.2,
        saturation=80,
    )
    b = color.ClipColor(
        palette=[{"hex": "#aa0000", "weight": 0.5}, {"hex": "#00aa00", "weight": 0.5}],
        mean_luminance=120,
        luminance_std=30,
        warm_cool=0.2,
        saturation=80,
    )
    out = color._aggregate_palette([a, b], top=3)
    assert out[0]["hex"] == "#aa0000"  # appears in both
    # Weights should sum to 1.0 after normalization.
    assert abs(sum(p["weight"] for p in out) - 1.0) < 1e-6
