"""Workspace path resolution for per-genre data layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

LEGACY_LAYOUT_FILES = (
    "analyses",
    "thumbs",
    "audio",
    "inspirations.json",
    "aggregate-stats.json",
    "style-profile.json",
    "style-guide.md",
    "notebooklm-brief.md",
)


def data_root() -> Path:
    return Path.home() / ".film-style-analyzer"


def shot_profile_path() -> Path:
    return data_root() / "shot-profile.json"


def __getattr__(name: str):
    if name == "DATA_ROOT":
        return data_root()
    if name == "SHOT_PROFILE_PATH":
        return shot_profile_path()
    raise AttributeError(name)


@dataclass(frozen=True)
class GenrePaths:
    genre: str
    root: Path
    analyses_dir: Path
    thumbs_dir: Path
    audio_dir: Path
    guide_path: Path
    stats_path: Path
    profile_path: Path
    inspirations_path: Path
    notebooklm_path: Path
    edit_craft_dir: Path


def resolve_genre(genre: str | None = None) -> str:
    """CLI/MCP flag → config.default_genre → 'wedding'."""
    if genre:
        return genre
    try:
        from .config import load

        return getattr(load(), "default_genre", "wedding")
    except Exception:
        return "wedding"


def paths_for_genre(genre: str | None = None) -> GenrePaths:
    name = resolve_genre(genre)
    root = data_root() / name
    return GenrePaths(
        genre=name,
        root=root,
        analyses_dir=root / "analyses",
        thumbs_dir=root / "thumbs",
        audio_dir=root / "audio",
        guide_path=root / "style-guide.md",
        stats_path=root / "aggregate-stats.json",
        profile_path=root / "style-profile.json",
        inspirations_path=root / "inspirations.json",
        notebooklm_path=root / "notebooklm-brief.md",
        edit_craft_dir=root / "edit-craft",
    )


def legacy_layout_present(data_root_path: Path | None = None) -> bool:
    root = data_root_path or data_root()
    return (root / "analyses").is_dir()


def default_paths() -> GenrePaths:
    """Paths for the active genre at call time (reads config each call)."""
    return paths_for_genre(None)
