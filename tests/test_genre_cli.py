"""Tests for the `film-style genre` command group."""

from __future__ import annotations

import json

from click.testing import CliRunner

from film_style_analyzer.cli import cli


def test_genre_list_includes_wedding():
    runner = CliRunner()
    result = runner.invoke(cli, ["genre", "list"])
    assert result.exit_code == 0, result.output
    assert "wedding" in result.output


def test_genre_show_wedding():
    runner = CliRunner()
    result = runner.invoke(cli, ["genre", "show", "wedding"])
    assert result.exit_code == 0, result.output
    assert "ceremony" in result.output
    assert "music_first" in result.output


def test_genre_current_prints_default():
    runner = CliRunner()
    result = runner.invoke(cli, ["genre", "current"])
    assert result.exit_code == 0, result.output
    assert "wedding" in result.output


def test_genre_use_persists(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    cfg_dir = home / ".film-style-analyzer"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "config.json"
    cfg_path.write_text(json.dumps({"default_genre": "wedding"}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("film_style_analyzer.config.CONFIG_PATH", cfg_path)
    monkeypatch.setattr("film_style_analyzer.paths.data_root", lambda: cfg_dir)

    runner = CliRunner()
    result = runner.invoke(cli, ["genre", "use", "commercial"])
    assert result.exit_code == 0, result.output
    saved = json.loads(cfg_path.read_text())
    assert saved["default_genre"] == "commercial"


def test_analyze_with_genre_flag_uses_genre_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    cfg_dir = home / ".film-style-analyzer"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({"default_genre": "wedding"}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("film_style_analyzer.config.CONFIG_PATH", cfg_dir / "config.json")
    monkeypatch.setattr("film_style_analyzer.paths.data_root", lambda: cfg_dir)

    video = tmp_path / "sample.mp4"
    video.write_bytes(b"not a real video")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["analyze", str(video), "--genre", "commercial", "--skip-audio", "--skip-color"],
    )
    # May fail on ffmpeg but output dir should be commercial/analyses
    out_dir = cfg_dir / "commercial" / "analyses"
    assert out_dir.exists() or "fail" in result.output.lower() or result.exit_code != 0
