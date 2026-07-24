"""Tests for FCPXML timeline export."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from film_style_analyzer.fcpxml_writer import write_fcpxml


def test_write_fcpxml_video_spine(tmp_path: Path):
    clip_a = tmp_path / "a.mp4"
    clip_b = tmp_path / "b.mp4"
    clip_a.write_bytes(b"x")
    clip_b.write_bytes(b"y")

    timeline = [
        {
            "clip_id": "a",
            "name": "a.mp4",
            "source_path": str(clip_a),
            "trim_in_sec": 1.0,
            "trim_out_sec": 4.0,
            "timeline_duration_sec": 3.0,
            "timeline_offset_sec": 0.0,
            "source_duration_sec": 10.0,
        },
        {
            "clip_id": "b",
            "name": "b.mp4",
            "source_path": str(clip_b),
            "trim_in_sec": 0.5,
            "trim_out_sec": 2.5,
            "timeline_duration_sec": 2.0,
            "timeline_offset_sec": 3.0,
            "source_duration_sec": 8.0,
        },
    ]
    xml_text = write_fcpxml(timeline, title="Test rough", fps=24)
    assert xml_text.startswith("<?xml")
    body = xml_text.split("?>", 1)[1]
    if "<!DOCTYPE" in body:
        body = body.split("\n", 2)[2]
    root = ET.fromstring(body)
    assert root.tag == "fcpxml"
    clips = [e for e in root.iter() if e.tag.split("}")[-1] == "asset-clip"]
    assert len(clips) == 2
    assert clips[0].attrib["duration"] == "3000/1000s"
    assert clips[1].attrib["offset"] == "3000/1000s"
