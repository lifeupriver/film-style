"""Music characterization helpers — pure-function tests (no librosa needed)."""

from film_style_analyzer.music_analyze import (
    _nearest,
    _project_beats_to_timeline,
    _seconds_per_beat,
    score_cut_beat_alignment,
)


def test_seconds_per_beat():
    assert _seconds_per_beat(120.0) == 0.5
    assert _seconds_per_beat(0) == 0.0


def test_nearest_finds_closest():
    assert _nearest([1.0, 2.0, 3.0], 2.4) == 2.0
    assert _nearest([1.0, 2.0, 3.0], 2.6) == 3.0
    assert _nearest([1.0, 2.0, 3.0], -1.0) == 1.0
    assert _nearest([1.0, 2.0, 3.0], 100.0) == 3.0


def test_project_beats_to_timeline_with_gap():
    """Beats computed on concatenated music must map back to original timeline,
    skipping the speech-only gap between music segments."""
    music_segs = [
        {"type": "music", "start_sec": 0, "end_sec": 10, "duration_sec": 10},
        {"type": "music", "start_sec": 30, "end_sec": 40, "duration_sec": 10},
    ]
    # Beats computed on concatenated music: 4 evenly spaced.
    beats_local = [1.0, 6.0, 11.0, 16.0]  # 11s and 16s land in the second segment
    projected = _project_beats_to_timeline(beats_local, music_segs)
    # 1.0 → 1.0; 6.0 → 6.0; 11.0 → 31.0 (segment 2 starts at 30, beat is at 1s into it);
    # 16.0 → 36.0
    assert projected == [1.0, 6.0, 31.0, 36.0]


def test_score_cut_beat_alignment_on_beat():
    cuts = [1.0, 2.0, 3.0, 4.0]
    beats = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    out = score_cut_beat_alignment(cuts, beats, tolerance_sec=0.06)
    assert out["on_beat_pct"] == 100.0
    assert out["off_beat_pct"] == 0.0
    assert out["avg_distance_to_nearest_beat_sec"] == 0.0


def test_score_cut_beat_alignment_off_beat():
    # Cuts halfway between beats — none land on a beat.
    cuts = [1.5, 2.5, 3.5]
    beats = [1.0, 2.0, 3.0, 4.0]
    out = score_cut_beat_alignment(cuts, beats, tolerance_sec=0.06)
    assert out["on_beat_pct"] == 0.0
    assert out["off_beat_pct"] == 100.0


def test_score_cut_beat_alignment_partial():
    cuts = [1.0, 1.5, 2.0]
    beats = [1.0, 2.0, 3.0]
    out = score_cut_beat_alignment(cuts, beats, tolerance_sec=0.06)
    assert out["on_beat_pct"] == 66.7
    assert out["off_beat_pct"] == 33.3


def test_score_cut_beat_alignment_empty():
    out = score_cut_beat_alignment([], [1.0, 2.0])
    assert out["on_beat_pct"] == 0.0
    assert out["avg_distance_to_nearest_beat_sec"] is None
