"""claude_cli wrapper + guide_writer backend routing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from film_style_analyzer import claude_cli, genre_pack
from film_style_analyzer.guide_writer import write_guide


def test_is_available_when_binary_present(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    assert claude_cli.is_available() is True


def test_is_available_when_binary_missing(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: None)
    assert claude_cli.is_available() is False


def test_complete_extracts_result_field(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/fake/claude")
    fake_proc = MagicMock(returncode=0, stdout=json.dumps({"result": "GUIDE BODY"}), stderr="")
    monkeypatch.setattr(claude_cli.subprocess, "run", lambda *a, **kw: fake_proc)
    out = claude_cli.complete("hello", system="be helpful")
    assert out == "GUIDE BODY"


def test_complete_extracts_messages_envelope(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/fake/claude")
    payload = {"messages": [{"content": [{"type": "text", "text": "WRAPPED"}]}]}
    fake_proc = MagicMock(returncode=0, stdout=json.dumps(payload), stderr="")
    monkeypatch.setattr(claude_cli.subprocess, "run", lambda *a, **kw: fake_proc)
    assert claude_cli.complete("x") == "WRAPPED"


def test_complete_raises_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/fake/claude")
    fake_proc = MagicMock(returncode=2, stdout="", stderr="something broke")
    monkeypatch.setattr(claude_cli.subprocess, "run", lambda *a, **kw: fake_proc)
    with pytest.raises(claude_cli.ClaudeCLIError, match="something broke"):
        claude_cli.complete("x")


def test_complete_raises_when_binary_missing(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: None)
    with pytest.raises(claude_cli.ClaudeCLIError, match="not found on PATH"):
        claude_cli.complete("x")


def test_write_guide_routes_through_cli_backend(monkeypatch):
    """When backend='cli', write_guide must NOT touch the Anthropic SDK
    even if ANTHROPIC_API_KEY is unset."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    captured = {}

    def fake_complete(prompt, system=None, **kw):
        captured["prompt"] = prompt
        captured["system"] = system
        return "# Mock guide\n\nBody."

    monkeypatch.setattr("film_style_analyzer.claude_cli.complete", fake_complete)
    pack = genre_pack.load("wedding")
    out = write_guide({"film_count": 3}, pack, backend="cli")
    assert out.startswith("# Mock guide")
    assert "wedding filmmaker" in captured["system"].lower()
    assert "3 wedding films" in captured["prompt"]


def test_write_guide_api_backend_demands_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pack = genre_pack.load("wedding")
    with pytest.raises(RuntimeError, match="claude_backend"):
        write_guide({"film_count": 1}, pack, backend="api")
