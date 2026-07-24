"""Edit plan schema, clip catalog, validation, and greedy fallback assembly."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from . import __version__


class TimelineClip(BaseModel):
    clip_id: str
    trim_in_sec: float = 0.0
    trim_out_sec: float | None = None
    timeline_duration_sec: float | None = None
    segment: str | None = None
    transition_out: str = "hard_cut"
    reason: str | None = None

    @field_validator("clip_id")
    @classmethod
    def _strip_id(cls, v: str) -> str:
        return v.strip()


class EditPlan(BaseModel):
    schema_version: str = "1.0"
    generator_version: str = Field(default_factory=lambda: __version__)
    title: str = "Rough cut"
    fps: int = 24
    target_duration_sec: float | None = None
    song_path: str | None = None
    structure: str | None = None
    planner: str = "claude"
    notes: str | None = None
    timeline: list[TimelineClip] = Field(default_factory=list)


class AssemblyError(RuntimeError):
    pass


def clip_id_from_path(path: str | Path) -> str:
    stem = Path(path).stem
    for suffix in ("_proxy", "_Proxy", "-proxy"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem


def build_clip_catalog(
    clip_scores: dict,
    *,
    min_score: int = 1,
    include_rejected: bool = False,
) -> dict[str, dict[str, Any]]:
    """Index scored clips by clip_id for planner + validator."""
    catalog: dict[str, dict[str, Any]] = {}
    for rec in clip_scores.get("clips") or []:
        if rec.get("rejection") and not include_rejected:
            continue
        score = int(rec.get("score") or 0)
        if score < min_score:
            continue
        file_path = rec.get("file") or rec.get("path") or ""
        cid = clip_id_from_path(file_path)
        if cid in catalog:
            # Keep higher-scoring duplicate stems (rare).
            if score <= int(catalog[cid].get("score") or 0):
                continue
        trim = rec.get("trim") or {}
        duration = float(rec.get("duration_sec") or 0)
        trim_in = float(trim.get("trim_in_sec") or 0.0)
        trim_out = float(trim.get("trim_out_sec") or duration)
        usable = float(trim.get("usable_duration_sec") or max(0.0, trim_out - trim_in))
        analysis = rec.get("analysis") or {}
        catalog[cid] = {
            "clip_id": cid,
            "file": file_path,
            "original": rec.get("original") or file_path,
            "score": score,
            "scene": rec.get("scene"),
            "duration_sec": duration,
            "trim_in_sec": trim_in,
            "trim_out_sec": trim_out,
            "usable_duration_sec": usable,
            "framing": analysis.get("framing"),
            "emotion_peak": (rec.get("emotion") or {}).get("peak_score"),
            "has_person": analysis.get("has_person"),
        }
    return catalog


def catalog_for_prompt(
    catalog: dict[str, dict[str, Any]], limit: int = 400
) -> list[dict[str, Any]]:
    """Compact clip list for Claude — sorted by score desc."""
    rows = sorted(catalog.values(), key=lambda r: (-int(r.get("score") or 0), r["clip_id"]))
    out: list[dict[str, Any]] = []
    for row in rows[:limit]:
        out.append(
            {
                "clip_id": row["clip_id"],
                "score": row["score"],
                "scene": row.get("scene"),
                "duration_sec": row["duration_sec"],
                "trim_in_sec": row["trim_in_sec"],
                "trim_out_sec": row["trim_out_sec"],
                "usable_duration_sec": row["usable_duration_sec"],
                "framing": row.get("framing"),
                "emotion_peak": row.get("emotion_peak"),
            }
        )
    return out


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse JSON from a model response, tolerating markdown fences."""
    text = (text or "").strip()
    if not text:
        raise AssemblyError("empty planner response")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise AssemblyError(f"planner returned invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise AssemblyError("planner JSON must be an object")
    return data


def validate_and_resolve_plan(
    plan: EditPlan | dict,
    catalog: dict[str, dict[str, Any]],
) -> EditPlan:
    """Ensure every timeline clip references a known catalog entry with valid trims."""
    if isinstance(plan, dict):
        plan = EditPlan.model_validate(plan)
    resolved: list[TimelineClip] = []
    for item in plan.timeline:
        rec = catalog.get(item.clip_id)
        if not rec:
            raise AssemblyError(f"unknown clip_id in plan: {item.clip_id!r}")
        duration = float(rec["duration_sec"])
        trim_in = max(0.0, float(item.trim_in_sec))
        default_out = float(rec["trim_out_sec"])
        trim_out = float(item.trim_out_sec if item.trim_out_sec is not None else default_out)
        trim_out = min(trim_out, duration)
        if trim_out <= trim_in:
            raise AssemblyError(
                f"invalid trim window for {item.clip_id}: {trim_in:.3f}s – {trim_out:.3f}s"
            )
        source_len = trim_out - trim_in
        tl_dur = float(
            item.timeline_duration_sec if item.timeline_duration_sec is not None else source_len
        )
        tl_dur = max(0.1, min(tl_dur, source_len))
        resolved.append(
            TimelineClip(
                clip_id=item.clip_id,
                trim_in_sec=round(trim_in, 3),
                trim_out_sec=round(trim_out, 3),
                timeline_duration_sec=round(tl_dur, 3),
                segment=item.segment,
                transition_out=item.transition_out or "hard_cut",
                reason=item.reason,
            )
        )
    plan.timeline = resolved
    return plan


def resolved_timeline_entries(
    plan: EditPlan,
    catalog: dict[str, dict[str, Any]],
    *,
    media_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Expand plan items with absolute source paths for FCPXML export."""
    rows: list[dict[str, Any]] = []
    offset = 0.0
    for item in plan.timeline:
        rec = catalog[item.clip_id]
        src = rec.get("original") or rec.get("file")
        src_path = Path(src)
        if media_root and not src_path.is_absolute():
            src_path = media_root / src_path
        rows.append(
            {
                "clip_id": item.clip_id,
                "name": src_path.name,
                "source_path": str(src_path.resolve()),
                "trim_in_sec": item.trim_in_sec,
                "trim_out_sec": item.trim_out_sec,
                "timeline_duration_sec": item.timeline_duration_sec,
                "timeline_offset_sec": round(offset, 3),
                "segment": item.segment,
                "transition_out": item.transition_out,
                "score": rec.get("score"),
            }
        )
        offset += float(item.timeline_duration_sec or 0)
    return rows


def greedy_plan(
    catalog: dict[str, dict[str, Any]],
    *,
    cut_times: list[float] | None = None,
    segment_budgets: list[dict[str, float | str]] | None = None,
    target_duration_sec: float | None = None,
    min_clip_sec: float = 1.0,
    max_clip_sec: float = 8.0,
) -> EditPlan:
    """Deterministic fallback when Claude planning is unavailable."""
    pool = sorted(catalog.values(), key=lambda r: (-int(r.get("score") or 0), r["clip_id"]))
    if not pool:
        raise AssemblyError("no clips available for greedy assembly")

    slots: list[tuple[str | None, float]] = []
    if cut_times:
        prev = 0.0
        end = cut_times[-1] if cut_times else target_duration_sec
        if target_duration_sec:
            end = max(end, target_duration_sec)
        boundaries = [0.0] + list(cut_times)
        if target_duration_sec and (not cut_times or cut_times[-1] < target_duration_sec):
            boundaries.append(target_duration_sec)
        for i in range(len(boundaries) - 1):
            dur = boundaries[i + 1] - boundaries[i]
            if dur >= min_clip_sec * 0.5:
                slots.append((None, dur))
    elif segment_budgets:
        for seg in segment_budgets:
            name = str(seg["name"])
            budget = float(seg.get("target_duration_sec") or 0)
            remaining = budget
            while remaining >= min_clip_sec and len(slots) < 500:
                dur = min(max_clip_sec, max(min_clip_sec, remaining))
                slots.append((name, dur))
                remaining -= dur
    elif target_duration_sec:
        remaining = target_duration_sec
        while remaining >= min_clip_sec and len(slots) < 500:
            dur = min(max_clip_sec, max(min_clip_sec, remaining))
            slots.append((None, dur))
            remaining -= dur
    else:
        raise AssemblyError("greedy assembly needs cut times, segment budgets, or target duration")

    used: set[str] = set()
    timeline: list[TimelineClip] = []
    for segment, slot_dur in slots:
        pick = _pick_clip(pool, segment, slot_dur, used)
        if not pick:
            continue
        used.add(pick["clip_id"])
        trim_in = float(pick["trim_in_sec"])
        trim_out = float(pick["trim_out_sec"])
        usable = trim_out - trim_in
        tl_dur = min(slot_dur, usable)
        timeline.append(
            TimelineClip(
                clip_id=pick["clip_id"],
                trim_in_sec=trim_in,
                trim_out_sec=trim_in + tl_dur,
                timeline_duration_sec=round(tl_dur, 3),
                segment=segment or pick.get("scene"),
                reason="greedy fallback",
            )
        )

    return EditPlan(
        title="Greedy rough cut",
        planner="greedy",
        target_duration_sec=target_duration_sec,
        timeline=timeline,
    )


def _pick_clip(
    pool: list[dict[str, Any]],
    segment: str | None,
    slot_dur: float,
    used: set[str],
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_key: tuple[int, float] | None = None
    for rec in pool:
        cid = rec["clip_id"]
        if cid in used:
            continue
        usable = float(rec.get("usable_duration_sec") or 0)
        if usable < min(0.5, slot_dur * 0.5):
            continue
        seg_match = 1 if segment and rec.get("scene") == segment else 0
        key = (seg_match, int(rec.get("score") or 0))
        if best_key is None or key > best_key:
            best_key = key
            best = rec
    return best
