"""Tests for edit plan validation and greedy assembly."""

from __future__ import annotations

from film_style_analyzer.edit_plan import (
    EditPlan,
    TimelineClip,
    build_clip_catalog,
    clip_id_from_path,
    greedy_plan,
    validate_and_resolve_plan,
)


def _sample_scores() -> dict:
    return {
        "clips": [
            {
                "file": "/proj/02-proxies/DSC_0042_proxy.mp4",
                "original": "/proj/01-camera-originals/DSC_0042.MXF",
                "score": 88,
                "scene": "getting_ready",
                "duration_sec": 12.0,
                "trim": {"trim_in_sec": 1.0, "trim_out_sec": 10.0, "usable_duration_sec": 9.0},
                "analysis": {"framing": "medium_close", "has_person": True},
                "emotion": {"peak_score": 0.8},
            },
            {
                "file": "/proj/02-proxies/DSC_0043_proxy.mp4",
                "original": "/proj/01-camera-originals/DSC_0043.MXF",
                "score": 72,
                "scene": "ceremony",
                "duration_sec": 8.0,
                "trim": {"trim_in_sec": 0.5, "trim_out_sec": 7.0, "usable_duration_sec": 6.5},
                "analysis": {"framing": "wide", "has_person": True},
                "emotion": {"peak_score": 0.5},
            },
            {
                "file": "/proj/02-proxies/reject_proxy.mp4",
                "original": "/proj/01-camera-originals/reject.MXF",
                "score": 0,
                "rejection": "severely_underexposed",
                "duration_sec": 5.0,
                "analysis": {},
            },
        ]
    }


def test_clip_id_from_path_strips_proxy_suffix():
    assert clip_id_from_path("/a/DSC_0042_proxy.mp4") == "DSC_0042"


def test_build_clip_catalog_filters_rejects_and_min_score():
    catalog = build_clip_catalog(_sample_scores(), min_score=50)
    assert set(catalog.keys()) == {"DSC_0042", "DSC_0043"}


def test_validate_and_resolve_plan():
    catalog = build_clip_catalog(_sample_scores(), min_score=1)
    plan = EditPlan(
        timeline=[
            TimelineClip(
                clip_id="DSC_0042",
                trim_in_sec=1.0,
                trim_out_sec=5.0,
                timeline_duration_sec=3.0,
                segment="getting_ready",
            )
        ]
    )
    resolved = validate_and_resolve_plan(plan, catalog)
    assert len(resolved.timeline) == 1
    assert resolved.timeline[0].timeline_duration_sec == 3.0


def test_greedy_plan_fills_target_duration():
    catalog = build_clip_catalog(_sample_scores(), min_score=1)
    plan = greedy_plan(catalog, target_duration_sec=12.0, min_clip_sec=2.0, max_clip_sec=4.0)
    assert plan.timeline
    total = sum(c.timeline_duration_sec or 0 for c in plan.timeline)
    assert 8.0 <= total <= 14.0
