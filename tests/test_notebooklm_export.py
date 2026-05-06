"""NotebookLM export — markdown brief generation."""

from datetime import datetime, timezone

from film_style_analyzer import genre_pack
from film_style_analyzer.notebooklm_export import _gather_top_transcript_excerpts, export_brief
from film_style_analyzer.schemas import (
    Clip, Cuts, FilmAnalysis, FilmMeta, Pacing, Structure, Transitions,
)

PACK = genre_pack.load("wedding")


def _mk(filename, *, transcript=None, metadata=None):
    n = 5
    avg = 3.0
    clips = [
        Clip(index=i, start_sec=i * avg, end_sec=(i + 1) * avg, duration_sec=avg,
             transition_in="hard_cut" if i else "fade_in", transition_out="hard_cut")
        for i in range(n)
    ]
    return FilmAnalysis(
        analyzed_at=datetime.now(timezone.utc),
        analyzer_version="test",
        film=FilmMeta(filename=filename, path=f"/tmp/{filename}",
                      duration_sec=avg * n, resolution="1920x1080",
                      frame_rate=24.0, codec="h264"),
        cuts=Cuts(total=n, timestamps_sec=[c.start_sec for c in clips], clips=clips),
        pacing=Pacing(avg_clip_duration_sec=avg, median_clip_duration_sec=avg,
                      std_dev_sec=0.5, min_clip_sec=avg, max_clip_sec=avg,
                      clip_duration_histogram={}, pacing_curve_by_quartile={},
                      pacing_curve_by_decile=[avg] * 10),
        transitions=Transitions(hard_cut=n - 1, fade_in=1, fade_out=1),
        structure=Structure(
            opening={"first_cut_at_sec": avg, "first_5_clips_avg_duration_sec": avg},
            closing={"last_cut_at_sec": avg * n, "last_5_clips_avg_duration_sec": avg,
                     "fade_to_black": True, "fade_duration_sec": 2.0},
        ),
        transcript=transcript,
        metadata=metadata or {},
    )


def test_export_brief_basic():
    profile = {
        "rules": ["Target avg clip 3.4s.", "Lean warm in grade."],
        "pacing": {"decile_curve": [5, 4, 3, 3, 3, 3, 3, 3, 4, 5]},
        "transitions": {"hard_cut_pct": 93, "dissolve_pct": 6, "fade_pct": 1,
                        "avg_dissolves_per_film": 6},
        "audio": {"present": True, "first_speech_at_pct_target": 16,
                  "first_speech_at_sec_target": 60,
                  "speech_over_music_pct_target": 25,
                  "avg_speech_segment_sec_target": 30,
                  "longest_speech_segment_sec_target": 40},
        "color": {"present": True, "mean_warm_cool": 0.18,
                  "mean_luminance": 120, "mean_contrast": 50,
                  "dominant_palette": [{"hex": "#aa6622", "weight": 0.4}],
                  "tone_labels_seen": {"mid-key · warm": 5}},
        "structure": {"opening": {"first_cut_at_sec_target": 5.0},
                      "closing": {"fade_to_black_ratio": 0.8}},
    }
    md = export_brief([_mk("a.mp4"), _mk("b.mp4")], profile, PACK)
    # Headlines all present.
    for header in ("Binding Rules", "Pacing Curve", "Transitions",
                   "Audio Design", "Color & Grade",
                   "Opening & Closing", "Source Films"):
        assert header in md
    # Rules render.
    assert "Target avg clip 3.4s." in md
    # Pacing table renders.
    assert "0–10%" in md
    # Source films listed.
    assert "a.mp4" in md and "b.mp4" in md


def test_export_brief_includes_inspirations():
    profile = {"rules": []}
    inspirations = [{
        "url": "https://www.youtube.com/watch?v=abc",
        "added_at": "2026-05-06T10:00:00+00:00",
        "analysis": {
            "pacing": "Slow, lingering opens.",
            "shot_selection": "Heavy on wide aerials.",
            "distinctive_choices": ["Long static holds", "No music drops"],
            "relevance": "Translate the slow opens to your getting-ready scenes.",
        },
    }]
    md = export_brief([_mk("a.mp4")], profile, PACK, inspirations=inspirations)
    assert "YouTube Inspirations" in md
    assert "youtube.com/watch?v=abc" in md
    assert "Long static holds" in md
    assert "Translate the slow opens" in md


def test_export_brief_describes_pacing_shape():
    profile = {
        "rules": [],
        "pacing": {"decile_curve": [6, 6, 4, 3, 2.5, 2.5, 3, 3, 4, 5]},
    }
    md = export_brief([_mk("a.mp4")], profile, PACK)
    # Should detect "opens slowly" and "accelerates through the middle".
    assert "Shape:" in md


def test_gather_excerpts_picks_longest():
    f = _mk("a.mp4", transcript={
        "segments": [
            {"start_sec": 0, "end_sec": 5, "text": "short"},
            {"start_sec": 10, "end_sec": 60, "text": "the long one we want"},
            {"start_sec": 70, "end_sec": 80, "text": "medium"},
        ],
    })
    out = _gather_top_transcript_excerpts([f], max_per_film=1)
    assert len(out) == 1
    assert out[0]["text"] == "the long one we want"


def test_gather_excerpts_handles_no_transcript():
    f = _mk("a.mp4")  # no transcript
    assert _gather_top_transcript_excerpts([f]) == []


def test_export_brief_marks_metadata():
    f = _mk("a.mp4", metadata={"venue": "outdoor", "season": "summer"})
    md = export_brief([f], {"rules": []}, PACK)
    assert "venue: outdoor" in md
    assert "season: summer" in md
