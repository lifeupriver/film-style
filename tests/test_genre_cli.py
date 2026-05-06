"""Tests for the `film-style genre` command group."""

from __future__ import annotations

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
