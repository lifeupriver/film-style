import json
from pathlib import Path

import pytest

from film_style_analyzer.compare import build_report, shot_deviations
from film_style_analyzer.fcpxml_parser import parse as parse_fcpxml
from film_style_analyzer.otio_parser import parse as parse_otio
from film_style_analyzer.timeline import (
    flatten_visible,
    load_timeline,
    load_timeline_content,
)


def _rt(sec, rate=24):
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": sec * rate}


def _clip(name, sec):
    return {"OTIO_SCHEMA": "Clip.2", "name": name,
            "source_range": {"OTIO_SCHEMA": "TimeRange.1",
                             "start_time": _rt(0), "duration": _rt(sec)}}


def _gap(sec):
    return {"OTIO_SCHEMA": "Gap.1",
            "source_range": {"OTIO_SCHEMA": "TimeRange.1",
                             "start_time": _rt(0), "duration": _rt(sec)}}


def _otio(video_tracks, audio_tracks=(), transitions=0):
    tracks = []
    for children in video_tracks:
        tracks.append({"OTIO_SCHEMA": "Track.1", "kind": "Video", "children": children})
    for children in audio_tracks:
        tracks.append({"OTIO_SCHEMA": "Track.1", "kind": "Audio", "name": "Music",
                       "children": children})
    if transitions:
        first = tracks[0]["children"]
        first.insert(1, {"OTIO_SCHEMA": "Transition.1",
                         "transition_type": "SMPTE_Dissolve",
                         "in_offset": _rt(0.5), "out_offset": _rt(0.5)})
    return {"OTIO_SCHEMA": "Timeline.1", "name": "cut",
            "tracks": {"OTIO_SCHEMA": "Stack.1", "children": tracks}}


def test_flatten_upper_layer_wins():
    out = flatten_visible([
        {"start": 0, "end": 10, "layer": 0, "name": "aroll"},
        {"start": 4, "end": 6, "layer": 1, "name": "broll"},
    ])
    assert [(c["name"], c["start_sec"], c["end_sec"]) for c in out] == [
        ("aroll", 0, 4), ("broll", 4, 6), ("aroll", 6, 10)]
    assert [c["index"] for c in out] == [0, 1, 2]


def test_otio_single_track():
    cut = parse_otio(_otio([[_clip("a", 2), _clip("b", 3), _gap(1), _clip("c", 4)]],
                           audio_tracks=[[_clip("song", 10)]], transitions=1))
    assert cut["format"] == "otio"
    assert cut["clip_durations"] == [2, 3, 4]
    assert cut["visible_clips"][2]["start_sec"] == 6
    assert cut["dissolves"] == 1
    assert cut["audio"]["has_audio"] and cut["audio"]["audio_roles"] == ["music"]


def test_otio_broll_track_splits_visible_shots():
    cut = parse_otio(_otio([[_clip("interview", 10)], [_gap(4), _clip("rings", 2)]]))
    assert [c["name"] for c in cut["visible_clips"]] == ["interview", "rings", "interview"]
    assert cut["clip_count"] == 3


def test_otio_rejects_non_timeline():
    with pytest.raises(ValueError):
        parse_otio({"OTIO_SCHEMA": "Clip.2"})


FCPXML = """<?xml version="1.0"?>
<fcpxml version="1.10">
  <resources>
    <asset id="v1" hasVideo="1" hasAudio="1"/>
    <asset id="m1" hasVideo="0" hasAudio="1"/>
  </resources>
  <library><event><project><sequence><spine>
    <asset-clip ref="v1" name="vows" offset="0s" start="100s" duration="10s">
      <asset-clip ref="v1" name="rings" lane="1" offset="104s" duration="2s"/>
      <asset-clip ref="m1" name="song" lane="-1" offset="100s" duration="10s"/>
    </asset-clip>
    <asset-clip ref="v1" name="kiss" offset="10s" duration="3s"/>
  </spine></sequence></project></event></library>
</fcpxml>"""


def test_fcpxml_visible_clips_place_connected_broll(tmp_path: Path):
    p = tmp_path / "cut.fcpxml"
    p.write_text(FCPXML)
    cut = parse_fcpxml(p)
    names = [(c["name"], c["start_sec"], c["end_sec"]) for c in cut["visible_clips"]]
    assert names == [("vows", 0, 4), ("rings", 4, 6), ("vows", 6, 10), ("kiss", 10, 13)]


def test_load_timeline_dispatch(tmp_path: Path):
    f = tmp_path / "cut.fcpxml"
    f.write_text(FCPXML)
    o = tmp_path / "cut.otio"
    o.write_text(json.dumps(_otio([[_clip("a", 2)]])))
    assert load_timeline(f)["format"] == "fcpxml"
    assert load_timeline(o)["format"] == "otio"
    assert load_timeline_content(o.read_text())["format"] == "otio"
    assert load_timeline_content(FCPXML)["format"] == "fcpxml"
    bad = tmp_path / "cut.edl"
    bad.write_text("")
    with pytest.raises(ValueError):
        load_timeline(bad)


def test_shot_deviations_flags_long_and_short():
    cut = parse_otio(_otio([[_clip(f"s{i}", d) for i, d in
                             enumerate([3, 3, 9, 3, 3, 1, 3, 3, 3, 3])]]))
    devs = shot_deviations(cut, [3.0] * 10)
    by_name = {d["name"]: d for d in devs}
    assert set(by_name) == {"s2", "s5"}
    assert by_name["s2"]["action"] == "trim" and by_name["s2"]["by_sec"] == 6
    assert by_name["s5"]["action"] == "extend"
    assert devs[0]["name"] == "s2"


def test_build_report_includes_shot_deviations():
    cut = parse_otio(_otio([[_clip("a", 3), _clip("b", 12)]]))
    profile = {"film_count": 3,
               "duration": {"min_sec": 10, "max_sec": 20},
               "clip_counts": {"avg": 2},
               "pacing": {"avg_clip_sec": 3, "avg_deciles": [3.0] * 10},
               "transitions": {"avg_dissolves_per_film": 0}}
    report = build_report(cut, profile)
    assert report["shot_deviations"][0]["name"] == "b"
    assert report["deltas"]["duration_in_range"] is True
