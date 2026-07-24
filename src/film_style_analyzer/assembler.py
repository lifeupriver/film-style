"""Rough-cut assembly orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .edit_plan import (
    build_clip_catalog,
    greedy_plan,
    resolved_timeline_entries,
    validate_and_resolve_plan,
)
from .edit_planner import plan_edit_with_claude
from .fcpxml_writer import write_fcpxml
from .genre_pack import GenrePack
from .genre_pack import load as load_genre_pack
from .paths import paths_for_genre
from .predict_cuts import PredictCutsError, predict_cuts
from .structure_templates import segment_budgets


class AssembleError(RuntimeError):
    pass


def load_clip_scores(path: Path) -> dict:
    if not path.is_file():
        raise AssembleError(f"clip scores not found: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise AssembleError(f"invalid clip scores JSON: {path}") from e


def load_style_profile(genre: str | None) -> dict | None:
    paths = paths_for_genre(genre)
    profile_path = paths.profile_path
    if not profile_path.is_file():
        return None
    try:
        return json.loads(profile_path.read_text())
    except json.JSONDecodeError:
        return None


def _cut_times_from_song(
    song_path: Path,
    profile: dict | None,
    *,
    target_duration_sec: float | None,
    snap_tolerance_sec: float,
) -> list[float]:
    try:
        prediction = predict_cuts(
            song_path,
            profile or {},
            target_duration_sec=target_duration_sec,
            snap_tolerance_sec=snap_tolerance_sec,
        )
    except PredictCutsError as e:
        raise AssembleError(str(e)) from e
    return [float(c["time_sec"]) for c in prediction.get("cuts") or []]


def assemble(
    *,
    clip_scores_path: Path,
    output_fcpxml: Path,
    plan_output: Path | None = None,
    genre: str | None = None,
    pack: GenrePack | None = None,
    profile: dict | None = None,
    planner: str = "claude",
    song_path: Path | None = None,
    structure: str | None = None,
    target_duration_sec: float | None = None,
    min_score: int = 50,
    brief: str | None = None,
    backend: str = "api",
    model: str = "claude-sonnet-4-20250514",
    fps: int = 24,
    media_root: Path | None = None,
    snap_tolerance_sec: float = 0.12,
    existing_plan_path: Path | None = None,
) -> dict[str, Any]:
    """Plan (Claude or greedy) + export FCPXML rough cut."""
    paths = paths_for_genre(genre)
    pack = pack or load_genre_pack(paths.genre)
    profile = profile if profile is not None else load_style_profile(paths.genre)

    scores = load_clip_scores(clip_scores_path)
    catalog = build_clip_catalog(scores, min_score=min_score)
    if not catalog:
        raise AssembleError(
            f"no clips scored >= {min_score} in {clip_scores_path}. "
            "Run `film-style score-clips` first."
        )

    if target_duration_sec is None and profile:
        dur = (profile.get("duration") or {}).get("target_median_sec")
        if dur:
            target_duration_sec = float(dur)

    cut_times: list[float] | None = None
    if song_path:
        if not song_path.is_file():
            raise AssembleError(f"song not found: {song_path}")
        cut_times = _cut_times_from_song(
            song_path,
            profile,
            target_duration_sec=target_duration_sec,
            snap_tolerance_sec=snap_tolerance_sec,
        )

    segment_rows = None
    if structure and target_duration_sec:
        segment_rows = segment_budgets(structure, target_duration_sec)

    if existing_plan_path:
        if not existing_plan_path.is_file():
            raise AssembleError(f"edit plan not found: {existing_plan_path}")
        raw = json.loads(existing_plan_path.read_text())
        plan = validate_and_resolve_plan(raw, catalog)
        plan.planner = "imported"
    elif planner == "greedy":
        plan = greedy_plan(
            catalog,
            cut_times=cut_times,
            segment_budgets=segment_rows,
            target_duration_sec=target_duration_sec,
            min_clip_sec=float((profile or {}).get("pacing", {}).get("min_clip_sec") or 1.0),
            max_clip_sec=float((profile or {}).get("pacing", {}).get("max_clip_sec") or 8.0),
        )
        plan.structure = structure
        plan.song_path = str(song_path) if song_path else None
        plan.target_duration_sec = target_duration_sec
        plan.fps = fps
    elif planner == "claude":
        plan = plan_edit_with_claude(
            catalog=catalog,
            profile=profile,
            pack=pack,
            target_duration_sec=target_duration_sec,
            structure=structure,
            cut_times=cut_times,
            song_path=str(song_path) if song_path else None,
            style_guide_path=paths.guide_path,
            brief=brief,
            backend=backend,
            model=model,
            fps=fps,
        )
    else:
        raise AssembleError(f"unknown planner {planner!r}; use claude or greedy")

    timeline = resolved_timeline_entries(plan, catalog, media_root=media_root)
    if not timeline:
        raise AssembleError("edit plan produced an empty timeline")

    # Attach source duration hints for asset declarations.
    for row in timeline:
        rec = catalog[row["clip_id"]]
        row["source_duration_sec"] = float(rec.get("duration_sec") or 0)

    xml = write_fcpxml(
        timeline,
        title=plan.title,
        fps=fps,
        song_path=song_path,
        event_name=f"{pack.display_name} assembly",
    )
    output_fcpxml.parent.mkdir(parents=True, exist_ok=True)
    output_fcpxml.write_text(xml)

    if plan_output:
        plan_output.parent.mkdir(parents=True, exist_ok=True)
        plan_output.write_text(plan.model_dump_json(indent=2))

    total_sec = timeline[-1]["timeline_offset_sec"] + timeline[-1]["timeline_duration_sec"]
    return {
        "title": plan.title,
        "planner": plan.planner,
        "clip_count": len(timeline),
        "total_duration_sec": round(total_sec, 2),
        "fcpxml_path": str(output_fcpxml),
        "plan_path": str(plan_output) if plan_output else None,
        "structure": structure,
        "song_path": str(song_path) if song_path else None,
        "notes": plan.notes,
    }


def export_plan_to_fcpxml(
    *,
    plan_path: Path,
    clip_scores_path: Path,
    output_fcpxml: Path,
    song_path: Path | None = None,
    fps: int = 24,
    media_root: Path | None = None,
    min_score: int = 1,
) -> dict[str, Any]:
    """Re-export an existing edit plan JSON to FCPXML."""
    scores = load_clip_scores(clip_scores_path)
    catalog = build_clip_catalog(scores, min_score=min_score, include_rejected=True)
    raw = json.loads(plan_path.read_text())
    plan = validate_and_resolve_plan(raw, catalog)
    timeline = resolved_timeline_entries(plan, catalog, media_root=media_root)
    for row in timeline:
        rec = catalog[row["clip_id"]]
        row["source_duration_sec"] = float(rec.get("duration_sec") or 0)
    xml = write_fcpxml(
        timeline,
        title=plan.title,
        fps=fps,
        song_path=song_path,
        event_name="Film Style Assembly",
    )
    output_fcpxml.write_text(xml)
    total_sec = timeline[-1]["timeline_offset_sec"] + timeline[-1]["timeline_duration_sec"]
    return {
        "title": plan.title,
        "clip_count": len(timeline),
        "total_duration_sec": round(total_sec, 2),
        "fcpxml_path": str(output_fcpxml),
    }
