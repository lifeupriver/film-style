"""Genre Pack abstraction.

A GenrePack bundles the vocabulary (scene labels, shot labels), prompts, and
tuned numeric defaults that adapt the analyzer to a specific genre of
filmmaking. Packs are TOML files — shipped in this package and optionally
overridden in `~/.film-style-analyzer/genre_packs/`.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

USER_PACK_DIR = Path.home() / ".film-style-analyzer" / "genre_packs"
SHIPPED_PACK_DIR = Path(__file__).parent / "genre_packs"

REQUIRED_PROMPT_KEYS = (
    "guide_writer_system",
    "chapter_classify_system",
    "shot_classify_system",
    "gemini_film_prompt",
    "gemini_youtube_prompt",
    "mcp_edit_in_style",
    "notebooklm_brief_intro",
)


# Default emotion scoring — wedding pack values; other packs override via [emotion].
DEFAULT_EMOTION_WEIGHTS: dict[str, float] = {
    "happy": 1.0,
    "surprise": 0.6,
    "sad": 0.4,
    "neutral": 0.0,
    "angry": -0.5,
    "fear": -0.3,
    "disgust": -0.5,
}

DEFAULT_WEDDING_SCENE_WEIGHTS: dict[str, float] = {
    "first_look": 1.5,
    "ceremony": 1.5,
    "speeches": 1.5,
    "parent_dances": 1.3,
    "first_dance": 1.2,
    "dancing": 1.0,
    "couple_photos": 1.0,
    "getting_ready_bride": 0.8,
    "getting_ready_groom": 0.8,
    "cocktail_hour": 0.7,
    "family_photos": 0.8,
    "reception_details": 0.0,
    "b_roll": 0.0,
    "exit": 1.0,
}

_LOW_EMOTION_LABELS = frozenset(
    {
        "b_roll",
        "details",
        "establishing",
        "transition",
        "other",
        "reception_details",
        "logo",
        "kicker",
    }
)


class GenrePackError(RuntimeError):
    pass


@dataclass(frozen=True)
class GenrePack:
    name: str
    display_name: str
    scene_detect_threshold: float
    min_scene_length_sec: float
    scene_labels: tuple[str, ...]
    shot_labels: tuple[str, ...]
    insert_definition: str
    metadata_keys: dict[str, list[str]]
    audio_emphasis: str
    still_hold_relevant: bool
    duration_range_hint_sec: tuple[float, float]
    prompts: dict[str, str]
    emotion_weights: dict[str, float]
    emotion_scene_weights: dict[str, float]


def _resolve_path(name: str) -> Path:
    user = USER_PACK_DIR / f"{name}.toml"
    if user.is_file():
        return user
    shipped = SHIPPED_PACK_DIR / f"{name}.toml"
    if shipped.is_file():
        return shipped
    raise GenrePackError(
        f"genre pack {name!r} not found (searched {USER_PACK_DIR} and {SHIPPED_PACK_DIR})"
    )


def _load_wedding_fallback_prompts() -> dict[str, str]:
    """Wedding's prompts are the fallback for any pack that omits a prompt key."""
    path = SHIPPED_PACK_DIR / "wedding.toml"
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text()).get("prompts", {})


def _default_scene_weights(scene_labels: tuple[str, ...], name: str) -> dict[str, float]:
    if name == "wedding":
        return dict(DEFAULT_WEDDING_SCENE_WEIGHTS)
    return {label: 0.0 if label in _LOW_EMOTION_LABELS else 1.0 for label in scene_labels}


def load(name: str) -> GenrePack:
    path = _resolve_path(name)
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise GenrePackError(f"failed to parse {path}: {e}") from e

    prompts = dict(raw.get("prompts", {}))
    if name != "wedding":
        for key, val in _load_wedding_fallback_prompts().items():
            prompts.setdefault(key, val)

    missing = [k for k in REQUIRED_PROMPT_KEYS if k not in prompts]
    if missing:
        raise GenrePackError(f"pack {name!r} missing required prompts: {missing}")

    duration = raw.get("duration_range_hint_sec") or [0.0, 0.0]
    scene_labels = tuple(raw["scene_labels"])
    emotion_raw = raw.get("emotion", {}) or {}
    emotion_weights = dict(emotion_raw.get("weights") or DEFAULT_EMOTION_WEIGHTS)
    scene_weight_raw = emotion_raw.get("scene_weights")
    if scene_weight_raw:
        emotion_scene_weights = {str(k): float(v) for k, v in scene_weight_raw.items()}
    else:
        emotion_scene_weights = _default_scene_weights(scene_labels, raw["name"])
    return GenrePack(
        name=raw["name"],
        display_name=raw["display_name"],
        scene_detect_threshold=float(raw["scene_detect_threshold"]),
        min_scene_length_sec=float(raw["min_scene_length_sec"]),
        scene_labels=scene_labels,
        shot_labels=tuple(raw["shot_labels"]),
        insert_definition=raw["insert_definition"],
        metadata_keys={k: list(v) for k, v in raw.get("metadata_keys", {}).items()},
        audio_emphasis=raw["audio_emphasis"],
        still_hold_relevant=bool(raw["still_hold_relevant"]),
        duration_range_hint_sec=(float(duration[0]), float(duration[1])),
        prompts=prompts,
        emotion_weights=emotion_weights,
        emotion_scene_weights=emotion_scene_weights,
    )


def list_available() -> list[str]:
    names: set[str] = set()
    for d in (SHIPPED_PACK_DIR, USER_PACK_DIR):
        if d.is_dir():
            for p in d.glob("*.toml"):
                names.add(p.stem)
    return sorted(names)
