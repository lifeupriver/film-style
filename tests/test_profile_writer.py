"""build_profile produces a typed, addressable contract for downstream tools."""

from datetime import datetime, timezone

from film_style_analyzer import genre_pack
from film_style_analyzer.aggregator import aggregate
from film_style_analyzer.profile_writer import build_profile

PACK = genre_pack.load("wedding")
from film_style_analyzer.schemas import (
    ChapterRecord,
    Clip,
    Cuts,
    FilmAnalysis,
    FilmMeta,
    Pacing,
    Structure,
    Transitions,
)


def _mk(
    filename, dur, clip_specs, *, color=None, music=None, audio=None, chapters=None, shot_sizes=None
):
    clips = []
    for i, (a, b, t_out) in enumerate(clip_specs):
        c = Clip(
            index=i,
            start_sec=a,
            end_sec=b,
            duration_sec=b - a,
            transition_in="hard_cut" if i > 0 else "fade_in",
            transition_out=t_out,
        )
        if shot_sizes and i < len(shot_sizes):
            c.shot_size = shot_sizes[i]
        clips.append(c)
    durations = [c.duration_sec for c in clips]
    avg = sum(durations) / len(durations)
    return FilmAnalysis(
        analyzed_at=datetime.now(timezone.utc),
        analyzer_version="test",
        film=FilmMeta(
            filename=filename,
            path=f"/tmp/{filename}",
            duration_sec=dur,
            resolution="1920x1080",
            frame_rate=24.0,
            codec="h264",
        ),
        cuts=Cuts(total=len(clips), timestamps_sec=[c.start_sec for c in clips], clips=clips),
        pacing=Pacing(
            avg_clip_duration_sec=avg,
            median_clip_duration_sec=avg,
            std_dev_sec=0.5,
            min_clip_sec=min(durations),
            max_clip_sec=max(durations),
            clip_duration_histogram={},
            pacing_curve_by_quartile={},
            pacing_curve_by_decile=[avg] * 10,
        ),
        transitions=Transitions(
            hard_cut=sum(1 for c in clips if c.transition_out == "hard_cut"),
            dissolve=sum(1 for c in clips if c.transition_out == "dissolve"),
        ),
        chapters=chapters or [],
        structure=Structure(
            opening={"first_cut_at_sec": 5.0, "first_5_clips_avg_duration_sec": avg},
            closing={
                "last_cut_at_sec": 0.0,
                "last_5_clips_avg_duration_sec": avg,
                "fade_to_black": True,
                "fade_duration_sec": 2.0,
            },
        ),
        audio=audio,
        color=color,
        music=music,
    )


def test_profile_includes_pacing_rules():
    f = _mk(
        "a.mp4",
        360,
        [(0, 3, "hard_cut"), (3, 6, "hard_cut"), (6, 9, "hard_cut"), (9, 12, "hard_cut")],
    )
    profile = build_profile([f], aggregate([f]), pack=PACK)
    assert profile["film_count"] == 1
    assert profile["pacing"]["target_avg_clip_sec"] is not None
    # Should produce at least one rule.
    assert len(profile["rules"]) > 0
    assert any("clip" in r.lower() for r in profile["rules"])


def test_profile_with_color_emits_grade_rule():
    color = {
        "mean_luminance": 110.0,
        "mean_contrast": 50.0,
        "mean_warm_cool": 0.35,
        "mean_saturation": 100.0,
        "tone_label": "mid-key · warm",
        "dominant_palette": [{"hex": "#aa6622", "weight": 0.4}],
    }
    f = _mk("a.mp4", 360, [(0, 3, "hard_cut"), (3, 6, "hard_cut")], color=color)
    profile = build_profile([f], aggregate([f]), pack=PACK)
    assert profile["color"]["present"] is True
    assert profile["color"]["mean_warm_cool"] == 0.35
    assert any("warm" in r.lower() for r in profile["rules"])


def test_profile_with_music_emits_tempo_range():
    music = {
        "has_music": True,
        "tempo_bpm": 105.0,
        "key": "G",
        "beats": [],
        "energy_curve_per_sec": [],
    }
    f = _mk("a.mp4", 360, [(0, 3, "hard_cut")], music=music)
    profile = build_profile([f], aggregate([f]), pack=PACK)
    assert profile["music"]["present"] is True
    assert profile["music"]["target_tempo_range_bpm"] == [105.0, 105.0]
    assert any("BPM" in r for r in profile["rules"])


def test_profile_with_shot_sizes_emits_mix_rule():
    f = _mk(
        "a.mp4",
        360,
        [(0, 3, "hard_cut"), (3, 6, "hard_cut"), (6, 9, "hard_cut"), (9, 12, "hard_cut")],
        shot_sizes=["wide", "medium", "close_up", "wide"],
    )
    profile = build_profile([f], aggregate([f]), pack=PACK)
    assert profile["shot_mix"]["labeled_clips"] == 4
    assert profile["shot_mix"]["dominant"] == "wide"
    assert any("shot mix" in r.lower() for r in profile["rules"])


def test_profile_with_scene_breakdown():
    chapters = [
        ChapterRecord(
            index=0,
            start_clip=0,
            end_clip=0,
            start_sec=0,
            end_sec=10,
            duration_sec=10,
            clip_count=1,
            avg_clip_sec=10.0,
            label="ceremony",
        ),
        ChapterRecord(
            index=1,
            start_clip=1,
            end_clip=1,
            start_sec=10,
            end_sec=20,
            duration_sec=10,
            clip_count=1,
            avg_clip_sec=2.0,
            label="dancing",
        ),
    ]
    f = _mk("a.mp4", 20, [(0, 10, "hard_cut"), (10, 12, "hard_cut")], chapters=chapters)
    profile = build_profile([f], aggregate([f]), pack=PACK)
    assert "ceremony" in profile["scenes"]
    assert "dancing" in profile["scenes"]
    # Pacing-by-scene rule should appear.
    assert any("ceremony" in r.lower() and "dancing" in r.lower() for r in profile["rules"])


def test_profile_empty():
    profile = build_profile([], {}, pack=PACK)
    assert profile["film_count"] == 0
    assert profile["rules"] == []
