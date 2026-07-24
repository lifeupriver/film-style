"""Analyzer orchestration tests with mocked media pipeline."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from film_style_analyzer.analyzer import analyze_film
from film_style_analyzer.genre_pack import load as load_genre_pack
from film_style_analyzer.schemas import Clip


@pytest.fixture
def pack():
    return load_genre_pack("wedding")


def _clip(i: int) -> Clip:
    return Clip(
        index=i,
        start_sec=float(i * 3),
        end_sec=float(i * 3 + 3),
        duration_sec=3.0,
        transition_in="hard_cut",
        transition_out="hard_cut",
    )


def test_analyze_film_minimal_pipeline(tmp_path, pack):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()

    fake_meta = {
        "filename": "clip.mp4",
        "path": str(video),
        "duration_sec": 10.0,
        "resolution": "1920x1080",
        "frame_rate": 24.0,
        "codec": "h264",
    }
    clips = [_clip(0), _clip(1)]

    with (
        patch("film_style_analyzer.analyzer.probe", return_value=fake_meta),
        patch("film_style_analyzer.analyzer.detect_clips", return_value=clips),
        patch("film_style_analyzer.analyzer.extract_thumbs"),
        patch("film_style_analyzer.analyzer.group_chapters", return_value=[]),
    ):
        result = analyze_film(
            video,
            thumbs,
            pack,
            skip_audio=True,
            skip_color=True,
            skip_music=True,
        )
    assert result.cuts.total == 2
    assert result.film.duration_sec == 10.0
