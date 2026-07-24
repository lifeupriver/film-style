"""HTTP dashboard API tests."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

import pytest

from film_style_analyzer import server as srv


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = home / ".film-style-analyzer" / "wedding"
    (root / "analyses").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        "film_style_analyzer.paths.data_root", lambda: home / ".film-style-analyzer"
    )
    srv._set_active_paths("wedding")
    httpd = srv._ThreadingServer(("127.0.0.1", 0), srv._make_handler())
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield port, root
    httpd.shutdown()


def _get(port: int, path: str) -> tuple[int, dict | str]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers={"Accept": "application/json"})
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    if "json" in resp.getheader("Content-Type", ""):
        return resp.status, json.loads(body)
    return resp.status, body


def test_api_films_empty(dashboard):
    port, _ = dashboard
    status, data = _get(port, "/api/films")
    assert status == 200
    assert data["films"] == []


def test_api_config_includes_genre(dashboard):
    port, _ = dashboard
    status, data = _get(port, "/api/config")
    assert status == 200
    assert data["active_genre"] == "wedding"
    assert "genre_display_name" in data


def test_api_film_detail(dashboard):
    from datetime import datetime, timezone

    port, root = dashboard
    payload = {
        "version": "1.0",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "analyzer_version": "test",
        "film": {
            "filename": "demo.mp4",
            "path": "/tmp/demo.mp4",
            "duration_sec": 60.0,
            "resolution": "1920x1080",
            "frame_rate": 24.0,
            "codec": "h264",
        },
        "cuts": {"total": 1, "timestamps_sec": [0.0], "clips": []},
        "pacing": {
            "avg_clip_duration_sec": 3.0,
            "median_clip_duration_sec": 3.0,
            "std_dev_sec": 0.0,
            "histogram": {},
            "quartile_avgs": {},
            "decile_avgs": [],
        },
        "transitions": {
            "hard_cut": 1,
            "dissolve": 0,
            "fade_in": 0,
            "fade_out": 0,
            "still_hold": 0,
        },
        "chapters": [],
        "structure": {"opening_fade_sec": 0.0, "closing_fade_sec": 0.0},
    }
    (root / "analyses" / "demo.json").write_text(json.dumps(payload))
    status, _ = _get(port, "/api/films/demo")
    assert status == 200
