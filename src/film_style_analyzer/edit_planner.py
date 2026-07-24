"""Claude-powered edit planning for rough-cut assembly."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .edit_plan import (
    AssemblyError,
    EditPlan,
    catalog_for_prompt,
    extract_json_object,
    validate_and_resolve_plan,
)
from .genre_pack import GenrePack
from .structure_templates import segment_budgets

PLANNER_SYSTEM = """You are an expert assistant editor assembling a rough cut that matches a filmmaker's established style.

You receive:
- A style profile and optional style guide excerpt (measurable pacing, transitions, structure rules)
- A structure template with segment time budgets (when provided)
- Predicted music cut times (when a song is provided)
- A catalog of scored raw clips (clip_id, score, scene, trims, framing, emotion)

Your job: choose an ORDERED list of clips for the timeline. Prefer high-scoring clips. Match segment/scene labels when assembling structured films. Vary framing when the profile suggests a shot mix. Never use a clip_id not in the catalog. Respect trim windows.

Return ONLY valid JSON (no markdown prose) with this shape:
{
  "title": "Project name — rough v1",
  "notes": "1-3 sentences on editorial intent",
  "timeline": [
    {
      "clip_id": "DSC_0042",
      "trim_in_sec": 1.2,
      "trim_out_sec": 4.8,
      "timeline_duration_sec": 3.6,
      "segment": "getting_ready",
      "transition_out": "hard_cut",
      "reason": "brief justification"
    }
  ]
}

Rules:
- timeline_duration_sec must be <= (trim_out_sec - trim_in_sec)
- Do not repeat the same clip_id unless absolutely necessary
- Hard-rejected clips are omitted from the catalog — do not invent ids
- For beat-driven montage, align segment boundaries to provided cut_times when possible
- Target total runtime close to target_duration_sec when given
"""


def _profile_excerpt(profile: dict | None, max_rules: int = 12) -> dict[str, Any]:
    if not profile:
        return {}
    pacing = profile.get("pacing") or {}
    return {
        "genre": profile.get("genre"),
        "film_count": profile.get("film_count"),
        "pacing": {
            k: pacing.get(k)
            for k in (
                "target_avg_clip_sec",
                "target_median_clip_sec",
                "min_clip_sec",
                "max_clip_sec",
                "decile_curve",
            )
        },
        "transitions": profile.get("transitions"),
        "audio": profile.get("audio"),
        "shot_mix": profile.get("shot_mix"),
        "scenes": profile.get("scenes"),
        "rules": (profile.get("rules") or [])[:max_rules],
    }


def build_planner_prompt(
    *,
    catalog: dict[str, dict[str, Any]],
    profile: dict | None,
    style_guide_excerpt: str | None,
    pack: GenrePack,
    target_duration_sec: float | None,
    structure: str | None,
    segment_rows: list[dict[str, float | str]] | None,
    cut_times: list[float] | None,
    song_path: str | None,
    brief: str | None,
) -> str:
    payload: dict[str, Any] = {
        "genre": pack.name,
        "genre_display_name": pack.display_name,
        "editorial_brief": brief,
        "target_duration_sec": target_duration_sec,
        "structure": structure,
        "segment_budgets": segment_rows,
        "song_path": song_path,
        "cut_times_sec": cut_times,
        "style_profile": _profile_excerpt(profile),
        "style_guide_excerpt": (style_guide_excerpt or "")[:4000] or None,
        "scene_labels": pack.scene_labels,
        "clip_catalog": catalog_for_prompt(catalog),
        "clip_count": len(catalog),
    }
    return (
        "Plan a rough cut using the following inputs.\n\n"
        f"{json.dumps(payload, indent=2)}\n\n"
        "Respond with the JSON edit plan only."
    )


def plan_edit_with_claude(
    *,
    catalog: dict[str, dict[str, Any]],
    profile: dict | None,
    pack: GenrePack,
    target_duration_sec: float | None = None,
    structure: str | None = None,
    cut_times: list[float] | None = None,
    song_path: str | None = None,
    style_guide_path: Path | None = None,
    brief: str | None = None,
    backend: str = "api",
    model: str = "claude-sonnet-4-20250514",
    fps: int = 24,
) -> EditPlan:
    segment_rows = None
    if structure and target_duration_sec:
        segment_rows = segment_budgets(structure, target_duration_sec)

    guide_excerpt = None
    if style_guide_path and style_guide_path.is_file():
        guide_excerpt = style_guide_path.read_text()[:8000]

    user = build_planner_prompt(
        catalog=catalog,
        profile=profile,
        style_guide_excerpt=guide_excerpt,
        pack=pack,
        target_duration_sec=target_duration_sec,
        structure=structure,
        segment_rows=segment_rows,
        cut_times=cut_times,
        song_path=song_path,
        brief=brief,
    )
    system = PLANNER_SYSTEM.replace(
        "filmmaker's established style",
        f"{pack.display_name} editor's established style",
    )

    if backend == "cli":
        from .claude_cli import complete as claude_cli_complete

        raw = claude_cli_complete(prompt=user, system=system, max_turns=2, output_format="text")
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise AssemblyError(
                "ANTHROPIC_API_KEY is not set. Export it or pass --planner greedy, "
                'or set claude_backend="cli" in config.'
            )
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(block.text for block in msg.content if hasattr(block, "text"))

    data = extract_json_object(raw)
    data.setdefault("fps", fps)
    data.setdefault("target_duration_sec", target_duration_sec)
    data.setdefault("song_path", song_path)
    data.setdefault("structure", structure)
    data["planner"] = backend
    plan = validate_and_resolve_plan(EditPlan.model_validate(data), catalog)
    return plan
