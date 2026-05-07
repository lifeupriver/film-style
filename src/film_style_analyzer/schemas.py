"""Pydantic models for analysis data structures."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TransitionType = Literal[
    "hard_cut",     # single-frame jump in pixel content
    "dissolve",     # gradual blend across multiple frames
    "fade_in",      # opening fade from black
    "fade_out",     # closing fade to black
    "still_hold",   # boundary where one side is a held still photograph
                    # (near-zero inter-frame motion). Common in wedding-film
                    # editing where the editor intersperses photos with motion.
]


class FilmMeta(BaseModel):
    filename: str
    path: str
    duration_sec: float
    resolution: str
    frame_rate: float
    codec: str


class ShotDescription(BaseModel):
    """Semantic description of what's in a clip — populated by a vision pass
    that lets Claude (or another VLM) look at the clip's middle-frame
    thumbnail and emit structured fields.

    Used by downstream tools that need to pick clips from raw footage to
    match the editor's choices: 'find me a 3–5s tender medium-close shot of
    couple in golden_hour' becomes searchable when these fields are set.

    Every field is optional. Fields with controlled vocabularies use lower-
    snake-case strings; the dashboard can render them as filter pills."""

    subjects: list[str] = Field(default_factory=list)
    # Vocab: bride, groom, couple, wedding_party, officiant, parents,
    # family, kids, guests, details_only

    action: str | None = None
    # Short imperative phrase: "walking down aisle", "embracing",
    # "looking down at flowers", "laughing", "exchanging rings", "still pose"

    setting: str | None = None
    # Vocab: altar, aisle, lawn, garden, dance_floor, tent, ballroom,
    # ceremony_seating, getting_ready_room, reception_table, hallway,
    # exterior_landscape, interior_other, vehicle

    lighting: str | None = None
    # Vocab: golden_hour, natural_daylight, overcast, candle,
    # warm_indoor, mixed_indoor, dim_indoor, uplighting_warm,
    # uplighting_cool, dance_floor, night_exterior

    camera: str | None = None
    # Vocab: locked, slight_handheld, handheld, push_in, pull_back,
    # pan, tilt, gimbal_walk, drone, rack_focus, slow_motion

    mood: str | None = None
    # Vocab: tender, joyful, ceremonial, intimate, candid, kinetic,
    # still, anticipatory, celebratory

    description: str | None = None
    # One short free-form sentence that captures anything the structured
    # fields miss. Avoid restating fields above.


class Clip(BaseModel):
    index: int
    start_sec: float
    end_sec: float
    duration_sec: float
    transition_in: TransitionType
    transition_out: TransitionType
    thumbnail: str | None = None
    shot_size: str | None = None       # populated by --shot-sizes
    color: dict | None = None          # populated by color analysis pass
    shot_description: ShotDescription | None = None  # what's in the frame
                                                     # (subjects, action,
                                                     # setting, lighting,
                                                     # camera, mood, free text)


class Cuts(BaseModel):
    total: int
    timestamps_sec: list[float]
    clips: list[Clip]


class Pacing(BaseModel):
    avg_clip_duration_sec: float
    median_clip_duration_sec: float
    std_dev_sec: float
    min_clip_sec: float
    max_clip_sec: float
    clip_duration_histogram: dict[str, int]
    pacing_curve_by_quartile: dict[str, float]
    pacing_curve_by_decile: list[float]


class Transitions(BaseModel):
    hard_cut: int = 0
    dissolve: int = 0
    fade_in: int = 0
    fade_out: int = 0
    still_hold: int = 0
    dissolve_positions_pct: list[float] = Field(default_factory=list)
    avg_dissolve_duration_sec: float = 0.0


class Structure(BaseModel):
    opening: dict
    closing: dict


class ChapterRecord(BaseModel):
    index: int
    start_clip: int
    end_clip: int
    start_sec: float
    end_sec: float
    duration_sec: float
    clip_count: int
    avg_clip_sec: float
    representative_thumbnail: str | None = None
    label: str | None = None  # populated by --vision


class FilmAnalysis(BaseModel):
    version: str = "1.0"
    analyzed_at: datetime
    analyzer_version: str
    film: FilmMeta
    cuts: Cuts
    pacing: Pacing
    transitions: Transitions
    chapters: list[ChapterRecord] = Field(default_factory=list)
    audio: dict | None = None
    transcript: dict | None = None
    structure: Structure
    gemini_analysis: dict | None = None
    color: dict | None = None          # film-level color summary
    music: dict | None = None          # tempo/beats/energy from C
    metadata: dict = Field(default_factory=dict)  # per-wedding tags (G)
