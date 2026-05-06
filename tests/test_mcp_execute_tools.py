"""MCP execute-tools (analyze_films / generate_guide / import_vimeo /
corpus_report) — pure-function tests with mocks for the heavy parts."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def fixture_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib
    from film_style_analyzer import mcp_server
    importlib.reload(mcp_server)
    mcp_server.ANALYSES_DIR.mkdir(parents=True, exist_ok=True)
    return tmp_path, mcp_server


def _write_synthetic_analysis(mcp_server, stem):
    payload = {
        "version": "1.0",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "analyzer_version": "test",
        "film": {"filename": f"{stem}.mp4", "path": f"/tmp/{stem}.mp4",
                 "duration_sec": 120.0, "resolution": "1920x1080",
                 "frame_rate": 24.0, "codec": "h264"},
        "cuts": {"total": 2, "timestamps_sec": [0.0, 5.0],
                 "clips": [
                     {"index": 0, "start_sec": 0.0, "end_sec": 5.0, "duration_sec": 5.0,
                      "transition_in": "fade_in", "transition_out": "hard_cut"},
                     {"index": 1, "start_sec": 5.0, "end_sec": 120.0,
                      "duration_sec": 115.0, "transition_in": "hard_cut",
                      "transition_out": "fade_out"},
                 ]},
        "pacing": {"avg_clip_duration_sec": 60.0, "median_clip_duration_sec": 60.0,
                   "std_dev_sec": 55.0, "min_clip_sec": 5.0, "max_clip_sec": 115.0,
                   "clip_duration_histogram": {}, "pacing_curve_by_quartile": {},
                   "pacing_curve_by_decile": [60.0] * 10},
        "transitions": {"hard_cut": 1, "dissolve": 0, "fade_in": 1, "fade_out": 1,
                        "dissolve_positions_pct": [],
                        "avg_dissolve_duration_sec": 0.0},
        "chapters": [{"index": 0, "start_clip": 0, "end_clip": 1,
                      "start_sec": 0, "end_sec": 120, "duration_sec": 120,
                      "clip_count": 2, "avg_clip_sec": 60,
                      "representative_thumbnail": None, "label": None}],
        "structure": {"opening": {"first_cut_at_sec": 5.0,
                                   "first_5_clips_avg_duration_sec": 60},
                      "closing": {"last_cut_at_sec": 120,
                                   "last_5_clips_avg_duration_sec": 60,
                                   "fade_to_black": True, "fade_duration_sec": 2.0}},
        "metadata": {},
    }
    (mcp_server.ANALYSES_DIR / f"{stem}.json").write_text(json.dumps(payload))


def test_corpus_report_empty(fixture_home):
    _, mcp_server = fixture_home
    out = mcp_server.tool_corpus_report()
    assert out["status"] == "empty"
    assert out["film_count"] == 0
    assert "next_step" in out


def test_corpus_report_ready(fixture_home):
    _, mcp_server = fixture_home
    for s in ("a", "b", "c"):
        _write_synthetic_analysis(mcp_server, s)
    out = mcp_server.tool_corpus_report()
    assert out["status"] == "ready"
    assert out["film_count"] == 3
    assert "aggregate_stats" in out
    assert "coverage" in out
    # Outliers should appear once we hit 3+ films.
    assert "outliers" in out
    assert len(out["outliers"]) == 3


def test_corpus_report_coverage_counts(fixture_home):
    _, mcp_server = fixture_home
    _write_synthetic_analysis(mcp_server, "a")
    out = mcp_server.tool_corpus_report()
    cov = out["coverage"]
    assert cov["color"] == "0/1"
    assert cov["audio"] == "0/1"
    assert cov["metadata"] == "0/1"


def test_expand_video_paths_rejects_missing(fixture_home):
    _, mcp_server = fixture_home
    with pytest.raises(mcp_server.MCPServerError):
        mcp_server._expand_video_paths(["/nonexistent/path"])


def test_expand_video_paths_rejects_unsupported(fixture_home, tmp_path):
    _, mcp_server = fixture_home
    bad = tmp_path / "thing.txt"
    bad.write_text("hi")
    with pytest.raises(mcp_server.MCPServerError):
        mcp_server._expand_video_paths([str(bad)])


def test_expand_video_paths_walks_folders(fixture_home, tmp_path):
    _, mcp_server = fixture_home
    folder = tmp_path / "videos"
    folder.mkdir()
    (folder / "a.mp4").touch()
    (folder / "b.mov").touch()
    (folder / "ignore.txt").touch()
    files = mcp_server._expand_video_paths([str(folder)])
    assert len(files) == 2
    assert all(f.suffix.lower() in (".mp4", ".mov") for f in files)


def test_analyze_films_skips_existing(fixture_home, tmp_path):
    """If an analysis already exists, analyze_films should skip without
    invoking the heavy pipeline."""
    _, mcp_server = fixture_home
    _write_synthetic_analysis(mcp_server, "demo")
    folder = tmp_path / "videos"
    folder.mkdir()
    (folder / "demo.mp4").touch()

    # Patch analyze_film so this test never actually runs scene detection.
    from film_style_analyzer import analyzer as analyzer_mod
    with patch.object(analyzer_mod, "analyze_film") as mock_run:
        out = mcp_server.tool_analyze_films([str(folder)])
        # Should not have called the heavy pipeline because analysis exists.
        mock_run.assert_not_called()
    assert out["skipped"] == 1
    assert out["succeeded"] == 0


def test_analyze_films_returns_failure_when_underlying_raises(fixture_home, tmp_path):
    _, mcp_server = fixture_home
    folder = tmp_path / "videos"
    folder.mkdir()
    (folder / "demo.mp4").touch()

    from film_style_analyzer import analyzer as analyzer_mod
    with patch.object(analyzer_mod, "analyze_film",
                       side_effect=RuntimeError("ffprobe failed")):
        out = mcp_server.tool_analyze_films([str(folder)])
    assert out["failed"] == 1
    assert "ffprobe failed" in out["results"][0]["error"]


def test_generate_guide_requires_analyses(fixture_home):
    _, mcp_server = fixture_home
    with pytest.raises(mcp_server.MCPServerError):
        mcp_server.tool_generate_guide()


def test_generate_guide_writes_profile(fixture_home):
    _, mcp_server = fixture_home
    _write_synthetic_analysis(mcp_server, "a")

    # Stub out the Claude API call for the markdown guide.
    from film_style_analyzer import guide_writer as gw
    with patch.object(gw, "write_guide", return_value="# Test guide\n\nBody."):
        out = mcp_server.tool_generate_guide()

    assert mcp_server.PROFILE_PATH.is_file()
    assert mcp_server.GUIDE_PATH.is_file()
    assert out["film_count"] == 1
    assert out["rule_count"] >= 1


def test_generate_guide_handles_guide_writer_failure(fixture_home):
    """Profile should still be written even if the guide-writer Anthropic
    call fails — the profile is the durable, deterministic artifact."""
    _, mcp_server = fixture_home
    _write_synthetic_analysis(mcp_server, "a")

    from film_style_analyzer import guide_writer as gw
    with patch.object(gw, "write_guide", side_effect=RuntimeError("api down")):
        out = mcp_server.tool_generate_guide()

    assert mcp_server.PROFILE_PATH.is_file()
    assert "failed" in out["guide_status"]
