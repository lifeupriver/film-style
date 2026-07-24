"""Music-aware cut prediction: test the snapping/decile-walk logic without librosa."""

from pathlib import Path

from film_style_analyzer.predict_cuts import (
    _nearest_beat,
    _target_duration_at,
    to_fcpxml_markers,
)


def test_target_duration_at_uses_correct_decile():
    deciles = [5.0, 4.5, 4.0, 3.5, 3.0, 3.0, 3.5, 4.0, 4.5, 5.0]
    # 0% → first decile
    assert _target_duration_at(0.0, 100, deciles) == 5.0
    # 50% → 5th index (0-based)
    assert _target_duration_at(50.0, 100, deciles) == 3.0
    # 99% → last decile
    assert _target_duration_at(99.0, 100, deciles) == 5.0


def test_target_duration_fallback_when_empty():
    assert _target_duration_at(50.0, 100, []) == 3.5


def test_nearest_beat_picks_closest():
    beats = [1.0, 2.0, 3.0]
    assert _nearest_beat(beats, 1.4) == 1.0
    assert _nearest_beat(beats, 1.6) == 2.0
    assert _nearest_beat(beats, 100.0) == 3.0
    assert _nearest_beat([], 1.0) is None


def test_to_fcpxml_markers_produces_valid_xml(tmp_path: Path):
    prediction = {
        "song": str(tmp_path / "song.mp3"),
        "song_duration_sec": 60.0,
        "song_tempo_bpm": 120.0,
        "snap_tolerance_sec": 0.12,
        "predicted_cut_count": 3,
        "on_beat_pct": 100.0,
        "cuts": [
            {
                "time_sec": 5.0,
                "ideal_target_sec": 5.0,
                "target_clip_dur_sec": 5.0,
                "snapped_to_beat": True,
                "decile": 0,
            },
            {
                "time_sec": 12.0,
                "ideal_target_sec": 12.0,
                "target_clip_dur_sec": 7.0,
                "snapped_to_beat": False,
                "decile": 2,
            },
            {
                "time_sec": 30.0,
                "ideal_target_sec": 30.0,
                "target_clip_dur_sec": 18.0,
                "snapped_to_beat": True,
                "decile": 5,
            },
        ],
    }
    xml_text = to_fcpxml_markers(prediction)
    assert xml_text.startswith("<?xml")
    # Valid XML — should round-trip through ET.fromstring without error.
    import xml.etree.ElementTree as ET

    # Strip the DOCTYPE which ET does not handle.
    body = xml_text.split("?>", 1)[1]
    if "<!DOCTYPE" in body:
        body = body.split("\n", 2)[2]
    root = ET.fromstring(body)
    assert root.tag == "fcpxml"
    markers = list(root.iter("marker"))
    assert len(markers) == 3
    assert "Cut 001" in markers[0].attrib["value"]
    # On-beat cuts are tagged in the marker label.
    assert "on beat" in markers[0].attrib["value"]
