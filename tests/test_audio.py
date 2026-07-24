"""Audio classification overlap-detection unit tests (don't require ina/whisper)."""

from film_style_analyzer.audio_classify import _detect_overlaps, _normalize_label


def test_normalize_label():
    assert _normalize_label("male") == "speech"
    assert _normalize_label("female") == "speech"
    assert _normalize_label("speech") == "speech"
    assert _normalize_label("music") == "music"
    assert _normalize_label("noise") == "noise"
    assert _normalize_label("noEnergy") == "silence"


def test_overlap_detected_as_speech_over_music():
    music = [{"start_sec": 0.0, "end_sec": 100.0, "type": "music", "duration_sec": 100.0}]
    speech = [{"start_sec": 30.0, "end_sec": 60.0, "type": "speech", "duration_sec": 30.0}]
    out = _detect_overlaps(speech, music)
    types = [s["type"] for s in out]
    assert "music" in types
    assert "speech_over_music" in types
    overlap = next(s for s in out if s["type"] == "speech_over_music")
    assert overlap["start_sec"] == 30.0
    assert overlap["end_sec"] == 60.0


def test_no_overlap_keeps_segments_distinct():
    music = [{"start_sec": 0.0, "end_sec": 30.0, "type": "music", "duration_sec": 30.0}]
    speech = [{"start_sec": 50.0, "end_sec": 80.0, "type": "speech", "duration_sec": 30.0}]
    out = _detect_overlaps(speech, music)
    assert all(s["type"] in ("music", "speech") for s in out)


def test_first_speech_at_zero_is_reported():
    """Regression: first_speech_at=0.0 must NOT be treated as 'no speech detected'."""
    from film_style_analyzer.audio_classify import _detect_overlaps

    music = [{"start_sec": 0.0, "end_sec": 100.0, "type": "music", "duration_sec": 100.0}]
    speech = [{"start_sec": 0.0, "end_sec": 5.0, "type": "speech", "duration_sec": 5.0}]
    unified = _detect_overlaps(speech, music)
    speech_segs = [s for s in unified if s["type"] in ("speech", "speech_over_music")]
    first = speech_segs[0]["start_sec"]
    assert first == 0.0
    # Reproduce the summary computation that previously bugged out:
    pct = lambda x: round(100 * x / 100.0, 1)
    assert (pct(first) if first is not None else None) == 0.0
