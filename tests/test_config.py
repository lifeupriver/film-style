import json
from pathlib import Path

from film_style_analyzer.config import Config, load, write_default


def test_load_defaults_when_missing(tmp_path: Path):
    cfg = load(tmp_path / "missing.json")
    assert cfg.whisper_model == "large-v3"
    assert cfg.scene_detect_threshold is None


def test_load_overrides(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"whisper_model": "base", "language": "fr"}))
    cfg = load(p)
    assert cfg.whisper_model == "base"
    assert cfg.language == "fr"
    assert cfg.gemini_model == "gemini-2.5-pro"


def test_load_ignores_unknown_keys(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"whisper_model": "tiny", "garbage_key": "ignored"}))
    cfg = load(p)
    assert cfg.whisper_model == "tiny"


def test_write_default(tmp_path: Path):
    p = tmp_path / "c.json"
    write_default(p)
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["whisper_model"] == "large-v3"
