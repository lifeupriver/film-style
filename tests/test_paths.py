"""Tests for workspace path resolution."""

from __future__ import annotations

import json

from film_style_analyzer import paths


def test_paths_for_genre_explicit():
    gp = paths.paths_for_genre("commercial")
    assert gp.genre == "commercial"
    assert gp.analyses_dir == paths.data_root() / "commercial" / "analyses"


def test_paths_for_genre_from_config(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "isolated-home" / ".film-style-analyzer"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({"default_genre": "documentary"}))
    monkeypatch.setenv("HOME", str(tmp_path / "isolated-home"))
    monkeypatch.setattr(
        "film_style_analyzer.config.CONFIG_PATH",
        cfg_dir / "config.json",
    )
    gp = paths.paths_for_genre(None)
    assert gp.genre == "documentary"


def test_legacy_layout_present(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert not paths.legacy_layout_present()
    (home / ".film-style-analyzer" / "analyses").mkdir(parents=True)
    assert paths.legacy_layout_present()
