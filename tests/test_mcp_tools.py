"""MCP tool implementations — tested as pure functions against fixture data."""

import json
from datetime import datetime, timezone

import pytest


@pytest.fixture
def fixture_home(tmp_path, monkeypatch):
    """Point HOME at a temp directory and reload mcp_server to pick up the
    new DATA_ROOT."""
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from film_style_analyzer import mcp_server

    importlib.reload(mcp_server)
    mcp_server.ANALYSES_DIR.mkdir(parents=True, exist_ok=True)
    return tmp_path, mcp_server


def _write_analysis(
    mcp_server,
    stem,
    *,
    dur=120.0,
    avg=3.0,
    music_pct=70.0,
    chapters=None,
    color=None,
    music=None,
    metadata=None,
):
    n = max(1, int(dur / avg))
    payload = {
        "version": "1.0",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "analyzer_version": "test",
        "film": {
            "filename": f"{stem}.mp4",
            "path": f"/tmp/{stem}.mp4",
            "duration_sec": dur,
            "resolution": "1920x1080",
            "frame_rate": 24.0,
            "codec": "h264",
        },
        "cuts": {
            "total": n,
            "timestamps_sec": [i * avg for i in range(n)],
            "clips": [
                {
                    "index": i,
                    "start_sec": i * avg,
                    "end_sec": (i + 1) * avg,
                    "duration_sec": avg,
                    "transition_in": "hard_cut" if i else "fade_in",
                    "transition_out": "hard_cut",
                }
                for i in range(n)
            ],
        },
        "pacing": {
            "avg_clip_duration_sec": avg,
            "median_clip_duration_sec": avg,
            "std_dev_sec": 0.5,
            "min_clip_sec": avg,
            "max_clip_sec": avg,
            "clip_duration_histogram": {},
            "pacing_curve_by_quartile": {},
            "pacing_curve_by_decile": [avg] * 10,
        },
        "transitions": {
            "hard_cut": n - 1,
            "dissolve": 0,
            "fade_in": 1,
            "fade_out": 1,
            "dissolve_positions_pct": [],
            "avg_dissolve_duration_sec": 0.0,
        },
        "chapters": chapters
        or [
            {
                "index": 0,
                "start_clip": 0,
                "end_clip": n - 1,
                "start_sec": 0,
                "end_sec": dur,
                "duration_sec": dur,
                "clip_count": n,
                "avg_clip_sec": avg,
                "representative_thumbnail": None,
                "label": None,
            },
        ],
        "structure": {
            "opening": {"first_cut_at_sec": avg, "first_5_clips_avg_duration_sec": avg},
            "closing": {
                "last_cut_at_sec": dur,
                "last_5_clips_avg_duration_sec": avg,
                "fade_to_black": True,
                "fade_duration_sec": 2.0,
            },
        },
        "audio": {
            "summary": {
                "music_only_pct": music_pct,
                "speech_over_music_pct": 25.0,
                "ambient_pct": 5.0,
                "first_speech_at_pct": 16.0,
                "music_only_sec": 70,
                "speech_over_music_sec": 25,
                "speech_only_sec": 0,
                "ambient_sec": 5,
                "first_speech_at_sec": 19.2,
                "speech_segment_count": 1,
                "avg_speech_segment_sec": 25,
                "longest_speech_segment_sec": 25,
                "total_speech_duration_sec": 25,
            },
            "segments": [],
        },
        "color": color,
        "music": music,
        "metadata": metadata or {},
    }
    (mcp_server.ANALYSES_DIR / f"{stem}.json").write_text(json.dumps(payload))


def test_list_films_empty(fixture_home):
    _, mcp_server = fixture_home
    out = mcp_server.tool_list_films()
    assert out["film_count"] == 0
    assert out["films"] == []


def test_list_films_returns_summaries(fixture_home):
    _, mcp_server = fixture_home
    _write_analysis(mcp_server, "demo-a")
    _write_analysis(mcp_server, "demo-b", dur=240.0, avg=4.0)
    out = mcp_server.tool_list_films()
    assert out["film_count"] == 2
    stems = {f["stem"] for f in out["films"]}
    assert stems == {"demo-a", "demo-b"}


def test_get_film_returns_full_payload(fixture_home):
    _, mcp_server = fixture_home
    _write_analysis(mcp_server, "demo-a")
    out = mcp_server.tool_get_film("demo-a")
    assert out["film"]["filename"] == "demo-a.mp4"
    assert "cuts" in out and "chapters" in out


def test_get_film_rejects_traversal(fixture_home):
    _, mcp_server = fixture_home
    with pytest.raises(mcp_server.MCPServerError):
        mcp_server.tool_get_film("../etc/passwd")


def test_get_style_profile_missing(fixture_home):
    _, mcp_server = fixture_home
    with pytest.raises(mcp_server.MCPServerError):
        mcp_server.tool_get_style_profile()


def test_get_style_profile_reads_file(fixture_home):
    home, mcp_server = fixture_home
    mcp_server.PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    mcp_server.PROFILE_PATH.write_text(json.dumps({"film_count": 5, "rules": ["a"]}))
    out = mcp_server.tool_get_style_profile()
    assert out["film_count"] == 5


def test_set_film_metadata_persists(fixture_home):
    _, mcp_server = fixture_home
    _write_analysis(mcp_server, "demo-a")
    out = mcp_server.tool_set_film_metadata("demo-a", {"venue": "outdoor", "season": "summer"})
    assert out["metadata"] == {"venue": "outdoor", "season": "summer"}
    # Reload and confirm.
    out2 = mcp_server.tool_get_film("demo-a")
    assert out2["metadata"]["venue"] == "outdoor"


def test_set_film_metadata_null_deletes(fixture_home):
    _, mcp_server = fixture_home
    _write_analysis(mcp_server, "demo-a", metadata={"venue": "indoor"})
    out = mcp_server.tool_set_film_metadata("demo-a", {"venue": None})
    assert "venue" not in out["metadata"]


def test_set_chapter_label_persists(fixture_home):
    _, mcp_server = fixture_home
    _write_analysis(mcp_server, "demo-a")
    out = mcp_server.tool_set_chapter_label("demo-a", 0, "Ceremony")
    assert out["label"] == "ceremony"  # normalized


def test_set_chapter_label_clears(fixture_home):
    _, mcp_server = fixture_home
    _write_analysis(
        mcp_server,
        "demo-a",
        chapters=[
            {
                "index": 0,
                "start_clip": 0,
                "end_clip": 0,
                "start_sec": 0,
                "end_sec": 10,
                "duration_sec": 10,
                "clip_count": 1,
                "avg_clip_sec": 10,
                "representative_thumbnail": None,
                "label": "ceremony",
            }
        ],
    )
    out = mcp_server.tool_set_chapter_label("demo-a", 0, None)
    assert out["label"] is None


def test_set_chapter_label_out_of_range(fixture_home):
    _, mcp_server = fixture_home
    _write_analysis(mcp_server, "demo-a")
    with pytest.raises(mcp_server.MCPServerError):
        mcp_server.tool_set_chapter_label("demo-a", 99, "ceremony")


def test_find_similar_films(fixture_home):
    _, mcp_server = fixture_home
    _write_analysis(mcp_server, "demo-a", avg=3.5, music_pct=70.0)
    _write_analysis(mcp_server, "demo-b", avg=3.6, music_pct=68.0)
    _write_analysis(mcp_server, "demo-c", avg=8.0, music_pct=20.0)
    out = mcp_server.tool_find_similar_films("demo-a", top=2)
    # Closest match should not be self; demo-b is closer than demo-c.
    filenames = [m["filename"] for m in out["matches"]]
    assert "demo-a.mp4" not in filenames
    assert filenames[0] == "demo-b.mp4"


def test_resource_profile_handles_missing(fixture_home):
    _, mcp_server = fixture_home
    raw = mcp_server.resource_profile()
    parsed = json.loads(raw)
    assert "error" in parsed


def test_compare_fcpxml_via_content(fixture_home):
    _, mcp_server = fixture_home
    _write_analysis(mcp_server, "demo-a")
    fcpxml = """<?xml version="1.0"?>
<fcpxml version="1.10">
  <library><event><project><sequence><spine>
    <asset-clip duration="72000/24000s" offset="0s"/>
    <asset-clip duration="72000/24000s" offset="72000/24000s"/>
  </spine></sequence></project></event></library>
</fcpxml>"""
    out = mcp_server.tool_compare_fcpxml(fcpxml_content=fcpxml)
    assert out["empty_profile"] is False
    assert "deltas" in out
    assert "pacing_diff" in out


def test_compare_fcpxml_requires_one_arg(fixture_home):
    _, mcp_server = fixture_home
    with pytest.raises(mcp_server.MCPServerError):
        mcp_server.tool_compare_fcpxml()


def test_predict_cuts_validates_song_exists(fixture_home):
    _, mcp_server = fixture_home
    with pytest.raises(mcp_server.MCPServerError):
        mcp_server.tool_predict_cuts("/nonexistent/path/song.mp3")
