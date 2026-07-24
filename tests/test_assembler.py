"""Tests for assemble pipeline (greedy + export, no Claude)."""

from __future__ import annotations

import json
from pathlib import Path

from film_style_analyzer.assembler import assemble, export_plan_to_fcpxml


def _write_scores(path: Path, clips: list[dict]) -> None:
    path.write_text(json.dumps({"clips": clips}))


def test_assemble_greedy_writes_fcpxml_and_plan(tmp_path: Path):
    clip = tmp_path / "DSC_0001_proxy.mp4"
    clip.write_bytes(b"fake")
    scores_path = tmp_path / "clip-scores.json"
    _write_scores(
        scores_path,
        [
            {
                "file": str(clip),
                "original": str(clip),
                "score": 90,
                "scene": "montage",
                "duration_sec": 6.0,
                "trim": {"trim_in_sec": 0.0, "trim_out_sec": 6.0, "usable_duration_sec": 6.0},
                "analysis": {"framing": "medium"},
            },
            {
                "file": str(tmp_path / "DSC_0002_proxy.mp4"),
                "original": str(tmp_path / "DSC_0002_proxy.mp4"),
                "score": 85,
                "scene": "montage",
                "duration_sec": 5.0,
                "trim": {"trim_in_sec": 0.0, "trim_out_sec": 5.0, "usable_duration_sec": 5.0},
                "analysis": {"framing": "wide"},
            },
        ],
    )
    (tmp_path / "DSC_0002_proxy.mp4").write_bytes(b"fake2")

    out_fcpx = tmp_path / "rough.fcpxml"
    plan_out = tmp_path / "rough.edit-plan.json"
    result = assemble(
        clip_scores_path=scores_path,
        output_fcpxml=out_fcpx,
        plan_output=plan_out,
        planner="greedy",
        structure="montage",
        target_duration_sec=8.0,
        min_score=50,
    )
    assert out_fcpx.is_file()
    assert plan_out.is_file()
    assert result["clip_count"] >= 1
    assert "fcpxml" in out_fcpx.read_text()


def test_export_plan_to_fcpxml(tmp_path: Path):
    clip = tmp_path / "A_proxy.mp4"
    clip.write_bytes(b"x")
    scores_path = tmp_path / "scores.json"
    _write_scores(
        scores_path,
        [
            {
                "file": str(clip),
                "original": str(clip),
                "score": 80,
                "duration_sec": 4.0,
                "trim": {"trim_in_sec": 0.0, "trim_out_sec": 4.0, "usable_duration_sec": 4.0},
                "analysis": {},
            }
        ],
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "title": "Manual plan",
                "timeline": [
                    {
                        "clip_id": "A",
                        "trim_in_sec": 0.0,
                        "trim_out_sec": 3.0,
                        "timeline_duration_sec": 3.0,
                    }
                ],
            }
        )
    )
    out = tmp_path / "out.fcpxml"
    result = export_plan_to_fcpxml(
        plan_path=plan_path,
        clip_scores_path=scores_path,
        output_fcpxml=out,
    )
    assert result["clip_count"] == 1
    assert out.is_file()
