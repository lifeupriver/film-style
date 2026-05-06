"""Test the legacy → genre-subfolder migration."""

from __future__ import annotations

from click.testing import CliRunner

from film_style_analyzer import cli as cli_mod


def test_migrate_moves_legacy_files(tmp_path, monkeypatch):
    fake_root = tmp_path / ".film-style-analyzer"
    fake_root.mkdir()
    # Lay down legacy files.
    (fake_root / "analyses").mkdir()
    (fake_root / "analyses" / "fake.json").write_text("{}")
    (fake_root / "thumbs").mkdir()
    (fake_root / "thumbs" / "fake").mkdir()
    (fake_root / "style-profile.json").write_text("{}")
    (fake_root / "inspirations.json").write_text("[]")

    monkeypatch.setattr(cli_mod, "DATA_ROOT", fake_root)

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["migrate", "--to", "wedding"])
    assert result.exit_code == 0, result.output
    assert (fake_root / "wedding" / "analyses" / "fake.json").exists()
    assert (fake_root / "wedding" / "style-profile.json").exists()
    assert (fake_root / "wedding" / "inspirations.json").exists()
    assert not (fake_root / "analyses").exists()
    assert not (fake_root / "style-profile.json").exists()


def test_migrate_no_legacy_errors(tmp_path, monkeypatch):
    fake_root = tmp_path / ".film-style-analyzer"
    fake_root.mkdir()
    monkeypatch.setattr(cli_mod, "DATA_ROOT", fake_root)

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["migrate", "--to", "wedding"])
    assert result.exit_code != 0
    assert "no legacy" in result.output.lower()
