"""Regression: thumbnail path must round-trip through DATA_ROOT cleanly."""

from pathlib import Path

from film_style_analyzer.schemas import Clip


def test_thumbnail_path_is_relative_to_data_root(tmp_path: Path):
    """Simulate the path math thumbnails.extract performs."""
    data_root = tmp_path
    thumbs_root = data_root / "thumbs"
    out_dir = thumbs_root / "sarah-and-mike"
    out_dir.mkdir(parents=True)
    out = out_dir / "clip_007.jpg"
    out.write_bytes(b"fake-jpeg")

    rel = out.relative_to(out_dir.parent.parent)
    # Resolve back through DATA_ROOT and confirm it points to the actual file.
    assert (data_root / rel).resolve() == out.resolve()
    assert str(rel) == "thumbs/sarah-and-mike/clip_007.jpg"


def test_clip_thumbnail_field_assignable():
    c = Clip(index=0, start_sec=0, end_sec=3, duration_sec=3,
             transition_in="fade_in", transition_out="hard_cut")
    c.thumbnail = "thumbs/foo/clip_000.jpg"
    assert c.thumbnail == "thumbs/foo/clip_000.jpg"
