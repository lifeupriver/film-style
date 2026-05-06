"""Vimeo import: command-build tests, no actual network."""

from pathlib import Path

import pytest

from film_style_analyzer.vimeo_import import (
    VimeoImportError,
    _build_command,
    _ensure_yt_dlp,
)


def test_build_command_defaults(tmp_path: Path):
    cmd = _build_command(
        yt_dlp="/usr/local/bin/yt-dlp",
        url="https://vimeo.com/12345",
        output_dir=tmp_path,
        cookies_browser=None,
        quality="best",
        archive_path=None,
    )
    assert cmd[0] == "/usr/local/bin/yt-dlp"
    assert "https://vimeo.com/12345" in cmd
    assert "--format" in cmd
    assert "--cookies-from-browser" not in cmd
    assert "--download-archive" not in cmd


def test_build_command_with_cookies_and_archive(tmp_path: Path):
    archive = tmp_path / "arc.txt"
    cmd = _build_command(
        yt_dlp="yt-dlp",
        url="https://vimeo.com/showcase/9",
        output_dir=tmp_path,
        cookies_browser="safari",
        quality="best",
        archive_path=archive,
    )
    assert "--cookies-from-browser" in cmd
    assert "safari" in cmd
    assert "--download-archive" in cmd
    assert str(archive) in cmd


def test_ensure_yt_dlp_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *_: None)
    with pytest.raises(VimeoImportError):
        _ensure_yt_dlp()
