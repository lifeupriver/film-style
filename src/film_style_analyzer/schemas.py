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
