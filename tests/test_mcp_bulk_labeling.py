"""Tests for the MCP bulk labeling + image-returning tool functions."""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone

import pytest


@pytest.fixture
def fixture_home(tmp_path, monkeypatch):
    """Point HOME at a temp dir, reload mcp_server so paths repoint."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from film_style_analyzer import mcp_server
    importlib.reload(mcp_server)
    mcp_server.ANALYSES_DIR.mkdir(parents=True, exist_ok=True)
    mcp_server.THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    return tmp_path, mcp_server


def _write_film(mcp_server, stem, *, n_chapters=4, n_clips=10):
    """Write a fixture analysis with n_chapters chapters and n_clips clips,
    plus stub thumbnail JPEGs. Each chapter's representative_thumbnail and
    each clip's thumbnail point to a real file on disk so the tools can
    return actual paths."""
    thumbs = mcp_server.THUMBS_DIR / stem
    thumbs.mkdir(parents=True, exist_ok=True)
    for i in range(n_clips):
        # Minimal valid JPEG header so file exists; content is irrelevant
        # because the tool functions only return paths, not bytes.
        (thumbs / f"clip_{i:03d}.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    payload = {
        "version": "1.0",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "analyzer_version": "test",
        "film": {"filename": f"{stem}.mp4", "path": f"/tmp/{stem}.mp4",
                 "duration_sec": 60.0, "resolution": "1920x1080",
                 "frame_rate": 24.0, "codec": "h264"},
        "cuts": {
            "total": n_clips,
            "timestamps_sec": [i * 6.0 for i in range(n_clips)],
            "clips": [
                {"index": i, "start_sec": i*6.0, "end_sec": (i+1)*6.0,
                 "duration_sec": 6.0, "transition_in": "hard_cut",
                 "transition_out": "hard_cut",
                 "thumbnail": f"thumbs/{stem}/clip_{i:03d}.jpg"}
                for i in range(n_clips)
            ],
        },
        "pacing": {"avg_clip_duration_sec": 6.0, "median_clip_duration_sec": 6.0,
                   "std_dev_sec": 0.0, "min_clip_sec": 6.0, "max_clip_sec": 6.0,
                   "clip_duration_histogram": {}, "pacing_curve_by_quartile": {},
                   "pacing_curve_by_decile": [6.0]*10},
        "transitions": {"hard_cut": n_clips - 1, "fade_in": 1, "fade_out": 1},
        "chapters": [
            {"index": i, "start_clip": i, "end_clip": i,
             "start_sec": i*6.0, "end_sec": (i+1)*6.0,
             "duration_sec": 6.0, "clip_count": 1, "avg_clip_sec": 6.0,
             "representative_thumbnail": f"thumbs/{stem}/clip_{i:03d}.jpg",
             "label": None}
            for i in range(n_chapters)
        ],
        "structure": {"opening": {}, "closing": {}},
    }
    (mcp_server.ANALYSES_DIR / f"{stem}.json").write_text(json.dumps(payload))


def test_get_unlabeled_chapter_thumbnails_returns_paths(fixture_home):
    _, mcp_server = fixture_home
    _write_film(mcp_server, "alpha", n_chapters=5)
    out = mcp_server.tool_get_unlabeled_chapter_thumbnails("alpha", max_chapters=3)
    assert out["stem"] == "alpha"
    assert len(out["chapters"]) == 3
    assert out["remaining_after_batch"] == 2
    for ch in out["chapters"]:
        assert ch["thumbnail_path"].endswith(".jpg")
        # Path must resolve into the test's HOME, not the real one.
        from pathlib import Path
        assert str(Path.home()) in ch["thumbnail_path"]
    assert "ceremony" in out["valid_labels"]


def test_set_chapter_labels_bulk_writes_file(fixture_home):
    _, mcp_server = fixture_home
    _write_film(mcp_server, "alpha", n_chapters=4)
    res = mcp_server.tool_set_chapter_labels_bulk(
        "alpha", {"0": "getting_ready", "1": "ceremony", "2": "first_dance"}
    )
    assert res["labels_applied"] == 3
    assert res["skipped"] == []
    assert res["remaining_unlabeled"] == 1

    on_disk = json.loads(
        (mcp_server.ANALYSES_DIR / "alpha.json").read_text()
    )
    labels = [c["label"] for c in on_disk["chapters"]]
    assert labels == ["getting_ready", "ceremony", "first_dance", None]


def test_set_chapter_labels_bulk_rejects_invalid(fixture_home):
    _, mcp_server = fixture_home
    _write_film(mcp_server, "alpha", n_chapters=3)
    res = mcp_server.tool_set_chapter_labels_bulk(
        "alpha",
        {"0": "ceremony", "1": "totally_not_a_label", "2": "details", "99": "ceremony"},
    )
    assert res["labels_applied"] == 2
    reasons = sorted(s["reason"] for s in res["skipped"])
    assert any("invalid label" in r for r in reasons)
    assert any("out of range" in r for r in reasons)


def test_set_chapter_labels_bulk_clears_with_none(fixture_home):
    _, mcp_server = fixture_home
    _write_film(mcp_server, "alpha", n_chapters=2)
    mcp_server.tool_set_chapter_labels_bulk("alpha", {"0": "ceremony"})
    res = mcp_server.tool_set_chapter_labels_bulk("alpha", {"0": None})
    assert res["labels_applied"] == 1
    on_disk = json.loads((mcp_server.ANALYSES_DIR / "alpha.json").read_text())
    assert on_disk["chapters"][0]["label"] is None


def test_get_unlabeled_clip_thumbnails_paginates(fixture_home):
    _, mcp_server = fixture_home
    _write_film(mcp_server, "alpha", n_chapters=2, n_clips=10)
    first = mcp_server.tool_get_unlabeled_clip_thumbnails("alpha", batch_size=4)
    assert len(first["clips"]) == 4
    assert [c["clip_index"] for c in first["clips"]] == [0, 1, 2, 3]
    assert first["remaining_after_batch"] == 6

    second = mcp_server.tool_get_unlabeled_clip_thumbnails("alpha", start_index=4, batch_size=4)
    assert [c["clip_index"] for c in second["clips"]] == [4, 5, 6, 7]
    assert "extreme_wide" in second["valid_shot_labels"]


def test_set_shot_sizes_bulk_writes_file(fixture_home):
    _, mcp_server = fixture_home
    _write_film(mcp_server, "alpha", n_chapters=2, n_clips=5)
    res = mcp_server.tool_set_shot_sizes_bulk(
        "alpha",
        {"0": "wide", "1": "medium", "2": "close_up", "3": "insert", "4": "aerial"},
    )
    assert res["sizes_applied"] == 5
    assert res["remaining_unlabeled"] == 0
    on_disk = json.loads((mcp_server.ANALYSES_DIR / "alpha.json").read_text())
    sizes = [c["shot_size"] for c in on_disk["cuts"]["clips"]]
    assert sizes == ["wide", "medium", "close_up", "insert", "aerial"]


def test_set_shot_sizes_bulk_rejects_invalid(fixture_home):
    _, mcp_server = fixture_home
    _write_film(mcp_server, "alpha", n_chapters=1, n_clips=3)
    res = mcp_server.tool_set_shot_sizes_bulk(
        "alpha", {"0": "wide", "1": "potato", "2": "close_up"},
    )
    assert res["sizes_applied"] == 2
    assert any("invalid shot label" in s["reason"] for s in res["skipped"])


def test_get_undescribed_clip_thumbnails_returns_schema_hint(fixture_home):
    _, mcp_server = fixture_home
    _write_film(mcp_server, "alpha", n_clips=4)
    out = mcp_server.tool_get_undescribed_clip_thumbnails("alpha", batch_size=2)
    assert out["stem"] == "alpha"
    assert len(out["clips"]) == 2
    assert out["remaining_after_batch"] == 2
    assert "subjects" in out["schema_hint"]
    assert "bride" in out["schema_hint"]["subjects"]
    assert "tender" in out["schema_hint"]["mood"]


def test_set_clip_descriptions_bulk_writes_structured(fixture_home):
    _, mcp_server = fixture_home
    _write_film(mcp_server, "alpha", n_clips=3)
    res = mcp_server.tool_set_clip_descriptions_bulk("alpha", {
        "0": {
            "subjects": ["bride", "groom"],
            "action": "embracing",
            "setting": "lawn",
            "lighting": "golden_hour",
            "camera": "slight_handheld",
            "mood": "tender",
            "description": "Bride leaning into groom's chest, both eyes closed.",
        },
        "1": {"subjects": ["details_only"], "action": "ring close-up"},
    })
    assert res["descriptions_applied"] == 2
    assert res["skipped"] == []
    assert res["remaining_undescribed"] == 1

    on_disk = json.loads((mcp_server.ANALYSES_DIR / "alpha.json").read_text())
    sd0 = on_disk["cuts"]["clips"][0]["shot_description"]
    assert sd0["subjects"] == ["bride", "groom"]
    assert sd0["action"] == "embracing"
    assert sd0["mood"] == "tender"
    assert "Bride leaning" in sd0["description"]


def test_set_clip_descriptions_bulk_clears_with_none(fixture_home):
    _, mcp_server = fixture_home
    _write_film(mcp_server, "alpha", n_clips=2)
    mcp_server.tool_set_clip_descriptions_bulk("alpha", {
        "0": {"subjects": ["bride"], "mood": "tender"},
    })
    res = mcp_server.tool_set_clip_descriptions_bulk("alpha", {"0": None})
    assert res["descriptions_applied"] == 1
    on_disk = json.loads((mcp_server.ANALYSES_DIR / "alpha.json").read_text())
    assert on_disk["cuts"]["clips"][0]["shot_description"] is None


def test_set_clip_descriptions_bulk_rejects_garbage(fixture_home):
    _, mcp_server = fixture_home
    _write_film(mcp_server, "alpha", n_clips=2)
    # `subjects` must be a list, not a string — pydantic rejects this.
    res = mcp_server.tool_set_clip_descriptions_bulk("alpha", {
        "0": {"subjects": "bride", "mood": "tender"},
        "1": {"action": "embracing"},
    })
    assert res["descriptions_applied"] == 1  # only clip 1 wrote
    assert any("invalid payload" in s["reason"] for s in res["skipped"])
