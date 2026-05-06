"""Footage matchmaker — vector building + similarity ranking."""

from datetime import datetime, timezone

import pytest

from film_style_analyzer.matchmaker import (
    biggest_differences,
    build_vector,
    cosine_similarity,
    find_similar,
)
from film_style_analyzer.schemas import (
    Clip, Cuts, FilmAnalysis, FilmMeta, Pacing, Structure, Transitions,
)


def _mk(filename, *, avg=3.5, hard=80, dissolve=20, music_pct=70.0,
        warm_cool=0.0, tempo=None, shot_sizes=None):
    n = 10
    clips = []
    for i in range(n):
        c = Clip(index=i, start_sec=i * avg, end_sec=(i + 1) * avg, duration_sec=avg,
                 transition_in="hard_cut" if i > 0 else "fade_in",
                 transition_out="dissolve" if i % 5 == 4 else "hard_cut")
        if shot_sizes and i < len(shot_sizes):
            c.shot_size = shot_sizes[i]
        clips.append(c)
    return FilmAnalysis(
        analyzed_at=datetime.now(timezone.utc),
        analyzer_version="test",
        film=FilmMeta(filename=filename, path=f"/tmp/{filename}", duration_sec=avg * n,
                      resolution="1920x1080", frame_rate=24.0, codec="h264"),
        cuts=Cuts(total=n, timestamps_sec=[c.start_sec for c in clips], clips=clips),
        pacing=Pacing(avg_clip_duration_sec=avg, median_clip_duration_sec=avg,
                      std_dev_sec=0.5, min_clip_sec=avg, max_clip_sec=avg,
                      clip_duration_histogram={}, pacing_curve_by_quartile={},
                      pacing_curve_by_decile=[avg] * 10),
        transitions=Transitions(hard_cut=hard, dissolve=dissolve, fade_in=1, fade_out=1),
        structure=Structure(
            opening={"first_cut_at_sec": avg, "first_5_clips_avg_duration_sec": avg},
            closing={"last_cut_at_sec": avg * n, "last_5_clips_avg_duration_sec": avg,
                     "fade_to_black": True, "fade_duration_sec": 2.0},
        ),
        audio={"summary": {"music_only_pct": music_pct, "speech_over_music_pct": 25.0,
                            "ambient_pct": 5.0, "first_speech_at_pct": 16.0}},
        color={"mean_luminance": 120.0, "mean_contrast": 50.0,
               "mean_warm_cool": warm_cool, "mean_saturation": 100.0},
        music={"has_music": True, "tempo_bpm": tempo} if tempo else None,
    )


def test_build_vector_dimensions_in_unit_range():
    v = build_vector(_mk("a.mp4", avg=3.5, music_pct=60))
    for k, val in v.dimensions.items():
        assert 0.0 <= val <= 1.0, f"{k} out of range: {val}"


def test_cosine_self_similarity_is_one():
    v = build_vector(_mk("a.mp4"))
    assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-9)


def test_similar_films_rank_higher_than_dissimilar():
    target = _mk("target.mp4", avg=3.5, music_pct=70.0, warm_cool=0.2, tempo=110)
    near   = _mk("near.mp4",   avg=3.6, music_pct=68.0, warm_cool=0.18, tempo=112)
    far    = _mk("far.mp4",    avg=7.0, music_pct=20.0, warm_cool=-0.5, tempo=60)

    matches = find_similar(target, [near, far], top_n=2)
    assert matches[0]["filename"] == "near.mp4"
    assert matches[1]["filename"] == "far.mp4"
    assert matches[0]["similarity"] > matches[1]["similarity"]


def test_self_excluded_from_results():
    target = _mk("a.mp4")
    matches = find_similar(target, [_mk("a.mp4"), _mk("b.mp4")], top_n=5)
    assert all(m["filename"] != "a.mp4" for m in matches)


def test_biggest_differences_ranks_dimensions():
    a = _mk("a.mp4", avg=2.0, warm_cool=0.5)
    b = _mk("b.mp4", avg=7.0, warm_cool=-0.5)
    diffs = biggest_differences(a, b, top_n=3)
    # Pacing.avg should be one of the top dimensions.
    keys = [d["dimension"] for d in diffs]
    assert "pacing.avg" in keys
