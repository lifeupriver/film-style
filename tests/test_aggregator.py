from datetime import datetime, timezone

from film_style_analyzer.aggregator import aggregate
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
    filename: str,
    duration: float,
    clip_specs: list[tuple[float, float, str]],
    chapters: list[ChapterRecord] | None = None,
    audio: dict | None = None,
) -> FilmAnalysis:
    clips = []
    for i, (start, end, t_out) in enumerate(clip_specs):
        clips.append(
            Clip(
                index=i,
                start_sec=start,
                end_sec=end,
                duration_sec=end - start,
                transition_in="hard_cut" if i > 0 else "fade_in",
                transition_out=t_out,
            )
        )
    durations = [c.duration_sec for c in clips]
    avg = sum(durations) / len(durations) if durations else 0.0
    return FilmAnalysis(
        analyzed_at=datetime.now(timezone.utc),
        analyzer_version="test",
        film=FilmMeta(
            filename=filename,
            path=f"/tmp/{filename}",
            duration_sec=duration,
            resolution="1920x1080",
            frame_rate=24.0,
            codec="h264",
        ),
        cuts=Cuts(total=len(clips), timestamps_sec=[c.start_sec for c in clips], clips=clips),
        pacing=Pacing(
            avg_clip_duration_sec=avg,
            median_clip_duration_sec=avg,
            std_dev_sec=0.0,
            min_clip_sec=min(durations) if durations else 0,
            max_clip_sec=max(durations) if durations else 0,
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
            opening={
                "first_cut_at_sec": clip_specs[0][1] if clip_specs else 0,
                "first_5_clips_avg_duration_sec": avg,
            },
            closing={
                "last_cut_at_sec": clip_specs[-1][0] if clip_specs else 0,
                "last_5_clips_avg_duration_sec": avg,
                "fade_to_black": True,
                "fade_duration_sec": 2.0,
            },
        ),
        audio=audio,
    )


def test_aggregate_basic_counts():
    f1 = _mk("a.mp4", 60.0, [(0, 3, "hard_cut"), (3, 6, "hard_cut")])
    f2 = _mk("b.mp4", 90.0, [(0, 4, "hard_cut"), (4, 9, "dissolve"), (9, 12, "hard_cut")])
    s = aggregate([f1, f2])
    assert s["film_count"] == 2
    assert s["clip_counts"]["min"] == 2
    assert s["clip_counts"]["max"] == 3
    assert s["transitions"]["dissolve_pct"] > 0


def test_aggregate_scene_breakdown():
    chapters = [
        ChapterRecord(
            index=0,
            start_clip=0,
            end_clip=1,
            start_sec=0,
            end_sec=10,
            duration_sec=10,
            clip_count=2,
            avg_clip_sec=5.0,
            label="ceremony",
        ),
        ChapterRecord(
            index=1,
            start_clip=2,
            end_clip=3,
            start_sec=10,
            end_sec=20,
            duration_sec=10,
            clip_count=2,
            avg_clip_sec=5.0,
            label="dancing",
        ),
    ]
    f = _mk(
        "a.mp4",
        20.0,
        [(0, 5, "hard_cut"), (5, 10, "dissolve"), (10, 15, "hard_cut"), (15, 20, "hard_cut")],
        chapters=chapters,
    )
    s = aggregate([f])
    labels = {x["label"] for x in s["scene_breakdown"]}
    assert labels == {"ceremony", "dancing"}


def test_aggregate_audio_summary():
    audio = {
        "summary": {
            "music_only_pct": 60.0,
            "speech_over_music_pct": 25.0,
            "speech_only_pct": 5.0,
            "ambient_pct": 10.0,
            "first_speech_at_pct": 16.0,
            "first_speech_at_sec": 60.0,
            "avg_speech_segment_sec": 30.0,
            "longest_speech_segment_sec": 40.0,
            "speech_segment_count": 3,
        }
    }
    f = _mk("a.mp4", 360.0, [(0, 5, "hard_cut")], audio=audio)
    s = aggregate([f])
    assert s["audio"]["films_with_audio"] == 1
    assert s["audio"]["music_only_pct_avg"] == 60.0


def test_aggregate_empty():
    assert aggregate([]) == {}


def test_short_film_does_not_pollute_decile_curve():
    """Films with < 10 clips have padded-zero deciles — must be excluded."""
    short_film = _mk("short.mp4", 30.0, [(i, i + 3, "hard_cut") for i in range(0, 12, 3)])
    # short_film has 4 clips → 6 zero-padded deciles. Force the field to zeros.
    short_film.pacing.pacing_curve_by_decile = [3.0] * 4 + [0.0] * 6

    full_film = _mk("full.mp4", 60.0, [(i, i + 5, "hard_cut") for i in range(0, 60, 5)])
    full_film.pacing.pacing_curve_by_decile = [5.0] * 10

    s = aggregate([short_film, full_film])
    # Only full_film (>= 10 clips) should contribute; deciles all 5.0, no zeros.
    assert s["pacing"]["avg_deciles"] == [5.0] * 10
