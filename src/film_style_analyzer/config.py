"""User config at ~/.film-style-analyzer/config.json. Missing keys fall back to defaults."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_PATH = Path.home() / ".film-style-analyzer" / "config.json"


@dataclass
class Config:
    # Branding / identity (used by dashboard masthead, NotebookLM brief title,
    # MCP prompt templates). Generic by default; set to your own name/studio.
    brand_name: str = "The Atelier"
    editor_name: str = "the editor"

    whisper_model: str = "large-v3"
    language: str = "en"
    scene_detect_threshold: float | None = None
    # None = not explicitly set by the user; callers should fall back to the
    # active genre pack's tuned value (see cli.py `analyze`'s precedence
    # chain: CLI flag > this config value > genre pack > built-in default).
    min_scene_length_sec: float | None = None
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
    p = path or CONFIG_PATH
    if not p.exists():
        return Config()
    try:
        raw = json.loads(p.read_text())
        if not isinstance(raw, dict):
            raise ValueError(f"expected a JSON object at the top level, got {type(raw).__name__}")
    except (json.JSONDecodeError, OSError, ValueError) as e:
        print(
            f"warning: could not read config at {p} ({type(e).__name__}: {e}); "
            "falling back to defaults for all settings",
            file=sys.stderr,
        )
        return Config()
    valid = {f for f in Config.__dataclass_fields__}
    filtered = {k: v for k, v in raw.items() if k in valid}
    return Config(**{**asdict(Config()), **filtered})


def write_default(path: Path | None = None, *, force: bool = False) -> Path:
    """Write the default config to `path` (or CONFIG_PATH).

    Refuses to clobber an existing (possibly customized) config unless
    `force=True` — pass `--force` on the CLI to overwrite intentionally.
    """
    p = path or CONFIG_PATH
    if p.exists() and not force:
        raise FileExistsError(
            f"config already exists at {p}; pass force=True "
            "(`film-style config --init --force`) to overwrite it"
        )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(Config()), indent=2))
    return p
