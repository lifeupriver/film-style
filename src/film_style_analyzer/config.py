"""User config at ~/.film-style-analyzer/config.json. Missing keys fall back to defaults."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


def config_path() -> Path:
    return Path.home() / ".film-style-analyzer" / "config.json"


def __getattr__(name: str):
    if name == "CONFIG_PATH":
        return config_path()
    raise AttributeError(name)


@dataclass
class Config:
    # Branding / identity (used by dashboard masthead, NotebookLM brief title,
    # MCP prompt templates). Generic by default; set to your own name/studio.
    brand_name: str = "The Atelier"
    editor_name: str = "the editor"

    whisper_model: str = "large-v3"
    language: str = "en"
    scene_detect_threshold: float | None = None
    min_scene_length_sec: float = 0.5
    anthropic_model: str = "claude-sonnet-4-20250514"
    gemini_model: str = "gemini-2.5-pro"
    thumbnail_quality: int = 2
    cleanup_audio_after_analysis: bool = True

    # Active genre — partitions ~/.film-style-analyzer/<genre>/.
    default_genre: str = "wedding"

    # How text-only LLM calls (guide writer, NotebookLM intro) reach Claude:
    #   "api" = use Anthropic Python SDK (requires ANTHROPIC_API_KEY)
    #   "cli" = shell out to the local `claude` Code CLI (uses your Claude
    #           Pro/Max subscription quota; requires `claude` on PATH)
    # Vision passes (--vision, --shot-sizes) still need "api" because the
    # local CLI is text-only.
    claude_backend: str = "api"


def load(path: Path | None = None) -> Config:
    p = path or config_path()
    if not p.exists():
        return Config()
    try:
        raw = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return Config()
    valid = {f for f in Config.__dataclass_fields__}
    filtered = {k: v for k, v in raw.items() if k in valid}
    return Config(**{**asdict(Config()), **filtered})


def write_default(path: Path | None = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(Config()), indent=2))
    return p
