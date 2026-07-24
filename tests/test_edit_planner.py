"""Tests for Claude edit planner (mocked)."""

from __future__ import annotations

import json

import pytest

from film_style_analyzer.edit_planner import plan_edit_with_claude
from film_style_analyzer.genre_pack import load as load_genre_pack


def test_plan_edit_with_claude_api_mock(monkeypatch):
    catalog = {
        "DSC_0042": {
            "clip_id": "DSC_0042",
            "file": "/a/DSC_0042_proxy.mp4",
            "original": "/a/DSC_0042.MXF",
            "score": 90,
            "scene": "getting_ready",
            "duration_sec": 10.0,
            "trim_in_sec": 0.0,
            "trim_out_sec": 10.0,
            "usable_duration_sec": 10.0,
            "framing": "medium_close",
        }
    }
    plan_json = {
        "title": "Test wedding rough",
        "notes": "Open tender, build to ceremony.",
        "timeline": [
            {
                "clip_id": "DSC_0042",
                "trim_in_sec": 1.0,
                "trim_out_sec": 4.0,
                "timeline_duration_sec": 3.0,
                "segment": "getting_ready",
            }
        ],
    }

    class FakeBlock:
        text = json.dumps(plan_json)

    class FakeMessage:
        content = [FakeBlock()]

    class FakeMessages:
        def create(self, **kwargs):
            return FakeMessage()

    class FakeAnthropic:
        messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr("anthropic.Anthropic", lambda api_key: FakeAnthropic())

    pack = load_genre_pack("wedding")
    plan = plan_edit_with_claude(
        catalog=catalog,
        profile={"pacing": {"target_avg_clip_sec": 3.5}},
        pack=pack,
        target_duration_sec=360.0,
        structure="wedding-classic",
        backend="api",
    )
    assert plan.title == "Test wedding rough"
    assert len(plan.timeline) == 1
    assert plan.timeline[0].clip_id == "DSC_0042"


def test_plan_edit_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pack = load_genre_pack("wedding")
    with pytest.raises(Exception, match="ANTHROPIC_API_KEY"):
        plan_edit_with_claude(
            catalog={
                "A": {
                    "clip_id": "A",
                    "file": "a.mp4",
                    "original": "a.mp4",
                    "score": 1,
                    "duration_sec": 1,
                    "trim_in_sec": 0,
                    "trim_out_sec": 1,
                    "usable_duration_sec": 1,
                }
            },
            profile=None,
            pack=pack,
            backend="api",
        )
