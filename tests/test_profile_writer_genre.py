"""Profile_writer should record genre + branch on audio_emphasis."""

from __future__ import annotations

from datetime import datetime, timezone

from film_style_analyzer import genre_pack
from film_style_analyzer.profile_writer import build_profile
from film_style_analyzer.schemas import (
    Clip, Cuts, FilmAnalysis, FilmMeta, Pacing, Structure, Transitions,
)


def _mk_minimal_film(filename="a.mp4"):
    clips = [
        Clip(index=0, start_sec=0, end_sec=3, duration_sec=3,
             transition_in="fade_in", transition_out="hard_cut"),
        Clip(index=1, start_sec=3, end_sec=6, duration_sec=3,
             transition_in="hard_cut", transition_out="hard_cut"),
    ]
    return FilmAnalysis(
        analyzed_at=datetime.now(timezone.utc),
        analyzer_version="test",
        film=FilmMeta(filename=filename, path=f"/tmp/{filename}",
                      duration_sec=6, resolution="1920x1080",
                      frame_rate=24.0, codec="h264"),
        cuts=Cuts(total=2, timestamps_sec=[0, 3], clips=clips),
        pacing=Pacing(avg_clip_duration_sec=3.0, median_clip_duration_sec=3.0,
                      std_dev_sec=0.0, min_clip_sec=3.0, max_clip_sec=3.0,
                      clip_duration_histogram={}, pacing_curve_by_quartile={},
                      pacing_curve_by_decile=[3.0] * 10),
        transitions=Transitions(hard_cut=2, fade_in=1),
        structure=Structure(
            opening={"first_cut_at_sec": 3.0, "first_5_clips_avg_duration_sec": 3.0},
            closing={"last_cut_at_sec": 6.0, "last_5_clips_avg_duration_sec": 3.0,
                     "fade_to_black": False, "fade_duration_sec": 0.0},
        ),
    )


def test_profile_records_genre_top_level():
    pack = genre_pack.load("wedding")
    profile = build_profile([], {}, pack=pack)
    assert profile["genre"] == "wedding"
    assert profile["genre_display_name"] == "wedding film"


def test_profile_includes_genre_extensions_key():
    pack = genre_pack.load("wedding")
    profile = build_profile([], {}, pack=pack)
    assert "genre_extensions" in profile
    assert isinstance(profile["genre_extensions"], dict)


def test_wedding_emits_music_first_and_still_hold_rules():
    pack = genre_pack.load("wedding")
    aggregated = {
        "transitions": {
            "hard_cut_pct": 80,
            "dissolve_pct": 15,
            "still_hold_pct": 5,
            "avg_dissolves_per_film": 8,
            "avg_still_holds_per_film": 3,
        },
        "audio": {
            "first_speech_at_pct_avg": 20,
            "first_speech_at_sec_avg": 60,
            "speech_over_music_pct_avg": 30,
        },
    }
    profile = build_profile([_mk_minimal_film()], aggregated, pack=pack)
    rules = " ".join(profile.get("rules", []))
    assert "still-hold" in rules
    assert "Hold music alone" in rules
