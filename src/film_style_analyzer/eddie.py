"""Translate the style profile and clip scores into Eddie inputs.

Eddie (an AI video editor reachable over MCP) builds and changes edits but
does not know how this editor cuts. These helpers turn ``style-profile.json``
and ``clip-scores.json`` into arguments for Eddie's own tools, so an
assistant running both servers can build a cut in the editor's style and
then check it with ``compare_timeline``.

Field names follow Eddie's tool parameters (``create_edit_result``,
``set_transitions``, ``snap_cuts_to_beats``, ``grade_edit``, ``apply_style``,
``create_recipe``). Nothing here calls Eddie.
"""

from __future__ import annotations

from pathlib import Path

PLAN_SCHEMA_VERSION = "1.0"

BRIEF_MAX_CHARS = 8000          # create_edit_result.brief
STYLE_WORDS_MAX_CHARS = 300     # apply_style.style
SAVE_NAME_MAX_CHARS = 60        # apply_style.saveName

# Snap cuts to the beat when at least this share of the editor's cuts land
# on one.
SNAP_TO_BEATS_MIN_PCT = 50.0

# Dissolve length is not measured from the archive; this is the default the
# plan proposes and says so.
DEFAULT_DISSOLVE_SEC = 1.0


def _minutes(sec: float | None) -> float | None:
    return round(sec / 60, 1) if sec else None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _pace_word(avg_clip_sec: float | None) -> str | None:
    if not avg_clip_sec:
        return None
    if avg_clip_sec < 2.0:
        return "fast"
    if avg_clip_sec < 3.5:
        return "measured"
    return "unhurried"


def _scene_targets(profile: dict) -> list[dict]:
    scenes = profile.get("scenes") or {}
    out = [
        {
            "scene": label,
            "avg_shot_sec": s.get("avg_clip_duration_sec"),
            "avg_section_sec": s.get("avg_duration_sec"),
            "share_of_runtime_pct": s.get("pct_of_total_runtime"),
        }
        for label, s in scenes.items()
    ]
    out.sort(key=lambda s: -(s["share_of_runtime_pct"] or 0))
    return out


def _grade(color: dict) -> dict | None:
    """A gentle starting grade from the archive's measured colour.

    The archive measures finished, graded films; Eddie's grade is applied to
    the footage in the edit. These values only lean the footage the same way
    and are capped small; ``lookMatch`` keeps Eddie's own strength limit on.
    """
    if not color or not color.get("present"):
        return None
    args: dict = {"lookMatch": True}
    wc = color.get("mean_warm_cool")
    if wc is not None:
        args["temperature"] = int(_clamp(round(wc * 40), -25, 25))
    sat = color.get("mean_saturation")
    if sat:
        # ~90/255 mean HSV saturation reads as a neutral grade.
        args["saturation"] = round(_clamp(sat / 90, 0.8, 1.2), 2)
    contrast = color.get("mean_contrast")
    if contrast:
        # ~55/255 luminance standard deviation reads as neutral contrast.
        args["contrast"] = round(_clamp(contrast / 55, 0.85, 1.15), 2)
    if len(args) == 1:
        return None
    return {
        "grade_edit": args,
        "measured": {k: color.get(k) for k in (
            "mean_luminance", "mean_contrast", "mean_warm_cool",
            "mean_saturation", "tone_labels_seen")},
        "note": ("Approximate. Measured from finished films, applied to "
                 "ungraded footage; check the preview and adjust."),
    }


def style_words(profile: dict) -> str:
    """A description of the look in at most 300 characters, for
    ``apply_style(style=...)``. Pieces are dropped from the end to fit."""
    genre = profile.get("genre_display_name") or profile.get("genre") or "film"
    duration = profile.get("duration") or {}
    pacing = profile.get("pacing") or {}
    trans = profile.get("transitions") or {}
    closing = (profile.get("structure") or {}).get("closing") or {}
    music = profile.get("music") or {}
    color = profile.get("color") or {}
    audio = profile.get("audio") or {}

    pieces: list[str] = []
    lo, hi = _minutes(duration.get("target_min_sec")), _minutes(duration.get("target_max_sec"))
    pieces.append(f"{genre}, {lo:g}-{hi:g} min." if lo and hi else f"{genre}.")
    pace = _pace_word(pacing.get("target_avg_clip_sec"))
    if pace:
        pieces.append(f"{pace.capitalize()} pace, shots avg "
                      f"{pacing['target_avg_clip_sec']:.1f}s.")
    if trans.get("hard_cut_pct") is not None:
        t = f"{trans['hard_cut_pct']:.0f}% hard cuts"
        if trans.get("avg_dissolves_per_film"):
            t += f", ~{trans['avg_dissolves_per_film']:.0f} dissolves"
        pieces.append(t + ".")
    if (closing.get("fade_to_black_ratio") or 0) > 0.5:
        pieces.append("Ends on a fade to black.")
    if (music.get("cut_on_beat_pct_target") or 0) >= SNAP_TO_BEATS_MIN_PCT:
        pieces.append("Cuts land on the beat.")
    if audio.get("present") and audio.get("speech_over_music_pct_target"):
        pieces.append("Music-led, speech laid over music.")
    wc = color.get("mean_warm_cool")
    if wc is not None:
        pieces.append("Warm grade." if wc > 0.1 else ("Cool grade." if wc < -0.1
                                                      else "Neutral grade."))

    while pieces and len(" ".join(pieces)) > STYLE_WORDS_MAX_CHARS:
        pieces.pop()
    return " ".join(pieces)


def _brief(profile: dict, scene_targets: list[dict]) -> str:
    duration = profile.get("duration") or {}
    genre = profile.get("genre_display_name") or profile.get("genre") or "film"
    lines = []
    med, lo, hi = (_minutes(duration.get(k)) for k in
                   ("target_median_sec", "target_min_sec", "target_max_sec"))
    if med:
        rng = f" (my finished films run {lo:g}-{hi:g} minutes)" if lo and hi else ""
        lines.append(f"Length: about {med:g} minutes{rng}.")
    lines.append(f"Cut this {genre.lower()} the way I cut. Measured from "
                 f"{profile.get('film_count', 0)} of my finished films:")
    lines += [f"- {r}" for r in profile.get("rules") or []]
    if scene_targets:
        lines.append("Shot length by part of the day:")
        for s in scene_targets:
            if s["avg_shot_sec"]:
                lines.append(f"- {s['scene'].replace('_', ' ')}: shots average "
                             f"{s['avg_shot_sec']:.1f}s")
    text = "\n".join(lines)
    return text[:BRIEF_MAX_CHARS]


def _recipe(profile: dict, brief: str) -> dict:
    duration = profile.get("duration") or {}
    genre = profile.get("genre_display_name") or profile.get("genre") or "film"
    med = _minutes(duration.get("target_median_sec")) or 5
    rules = "\n".join(line for line in brief.splitlines()
                      if not line.startswith("Length:"))
    template = (
        f"Build a {{length}}-minute {genre.lower()} from this project's footage "
        "in my editing style.\n\n"
        f"{rules}\n\n"
        "{focus}\n"
    )
    return {
        "title": f"{genre} in my style",
        "tagline": f"A {genre.lower()} cut to the pacing measured from my own films.",
        "icon": "film",
        "promptTemplate": template,
        "inputs": [
            {"id": "length", "label": "Length", "kind": "number",
             "min": 1, "max": 60, "defaultValue": med, "unit": "min"},
            {"id": "focus", "label": "Anything to include or leave out",
             "kind": "textarea", "placeholder": "e.g. open on the vows; skip the cake cutting",
             "required": False, "rows": 3},
        ],
        "toolsUsed": ["create_edit_result", "set_transitions",
                      "snap_cuts_to_beats", "grade_edit"],
    }


def _learned_brief(learned: dict) -> str:
    """Sections for the brief from what was learned beyond the finished films."""
    blocks = []
    ep = learned.get("edit_profile") or {}
    if ep.get("rules"):
        blocks.append(f"How I build a cut (from {ep.get('project_count', 0)} of my project files):\n"
                      + "\n".join(f"- {r}" for r in ep["rules"]))
    st = learned.get("structure") or {}
    if st.get("rules"):
        blocks.append("Running order:\n" + "\n".join(f"- {r}" for r in st["rules"]))
    sb = learned.get("soundbites") or {}
    sb_rules = list(sb.get("rules") or [])
    if sb.get("written_rules"):
        sb_rules.append(sb["written_rules"].strip())
    if sb_rules:
        blocks.append("How I choose spoken lines (vows, letters, toasts):\n"
                      + "\n".join(r if r.startswith("-") else f"- {r}" for r in sb_rules))
    co = learned.get("corrections") or {}
    if co.get("rules"):
        blocks.append("From my corrections of earlier AI cuts:\n"
                      + "\n".join(f"- {r}" for r in co["rules"]))
    return "\n\n".join(blocks)


def _visual(edit_profile: dict) -> dict | None:
    d = (edit_profile or {}).get("decisions") or {}
    if not d:
        return None
    out: dict = {}
    if d.get("slow_motion_pct"):
        out["slow_motion"] = {
            "share_of_shots_pct": d["slow_motion_pct"],
            "speed": d.get("slow_motion_speed"),
            "how": ("Use set_speed_ramp with preset \"constant\" and rate "
                    f"{d.get('slow_motion_speed') or 0.5:g} on about "
                    f"{d['slow_motion_pct']:.0f}% of picture-only shots and b-roll overlays "
                    "(never on segments carrying spoken lines)."),
        }
    if d.get("speed_ramps"):
        out["speed_ramps_per_film"] = d["speed_ramps"]
    if d.get("punch_in_pct"):
        out["punch_in"] = {
            "share_of_shots_pct": d["punch_in_pct"],
            "scale": d.get("punch_in_scale"),
            "how": ("Use crop_segments with anchor \"face\" and zoom "
                    f"{d.get('punch_in_scale') or 1.2:g} on about {d['punch_in_pct']:.0f}% "
                    "of segments, favouring spoken moments."),
        }
    if d.get("broll_coverage_pct"):
        out["broll_coverage_pct"] = d["broll_coverage_pct"]
        out["broll_how"] = (f"Use add_brolls so cutaways cover about "
                            f"{d['broll_coverage_pct']:.0f}% of the running time.")
    if d.get("head_skip_sec") is not None:
        out["trim_into_clips"] = {"head_sec": d["head_skip_sec"], "tail_sec": d.get("tail_skip_sec")}
    if d.get("music_tracks"):
        out["music"] = {k: d.get(k) for k in ("music_tracks", "music_coverage_pct",
                                              "music_starts_at_sec")}
    return out or None


def build_plan(profile: dict, learned: dict | None = None) -> dict:
    """Everything an assistant needs to drive Eddie in this editor's style.

    ``learned`` optionally carries what was learned beyond the finished
    films: ``edit_profile``, ``structure``, ``soundbites``, ``corrections``
    and ``eddie_card`` (a saved Eddie style card record).
    """
    if not profile or not profile.get("film_count"):
        raise ValueError("style profile is empty — run `film-style guide` first")
    learned = learned or {}

    duration = profile.get("duration") or {}
    trans = profile.get("transitions") or {}
    closing = (profile.get("structure") or {}).get("closing") or {}
    music = profile.get("music") or {}
    genre = profile.get("genre_display_name") or profile.get("genre") or "film"

    scenes = _scene_targets(profile)
    brief = _brief(profile, scenes)
    extra = _learned_brief(learned)
    if extra:
        brief = (brief + "\n\n" + extra)[:BRIEF_MAX_CHARS]

    build: dict = {"brief": brief}
    med = _minutes(duration.get("target_median_sec"))
    lo = _minutes(duration.get("target_min_sec"))
    if med:
        build["targetDurationMinutes"] = med
        if lo and lo >= med * 0.5:
            build["minimumDurationMinutes"] = lo

    decisions = (learned.get("edit_profile") or {}).get("decisions") or {}
    fade_out = (closing.get("fade_to_black_ratio") or 0) > 0.5
    if decisions.get("ends_with_fade_ratio") is not None:
        fade_out = decisions["ends_with_fade_ratio"] > 0.5
    fade_in = (decisions.get("opens_with_fade_ratio") or 0) > 0.5
    dissolve_sec = decisions.get("dissolve_sec")
    transitions = {
        "fade_in_at_start": fade_in,
        "fade_out_at_end": fade_out,
        "fade_duration_sec": decisions.get("fade_sec"),
        "dissolves_per_film": decisions.get("dissolves") or trans.get("avg_dissolves_per_film"),
        "dissolve_pct": trans.get("dissolve_pct"),
        "dissolve_duration_sec": dissolve_sec or DEFAULT_DISSOLVE_SEC,
        "dissolve_duration_measured": bool(dissolve_sec),
        "how": ("After the build, read the segments with get_edit(format=\"segments\"). "
                + ("Set a fade in on the first segment. " if fade_in else "")
                + ("Set a fade out on the last segment. " if fade_out else "")
                + (f"Place about {(decisions.get('dissolves') or trans['avg_dissolves_per_film']):.0f} "
                   f"dissolves of {dissolve_sec or DEFAULT_DISSOLVE_SEC:g}s, "
                   "preferring boundaries between parts of the day; every other "
                   "boundary stays a hard cut."
                   if (decisions.get("dissolves") or trans.get("avg_dissolves_per_film")) else
                   "Keep every boundary a hard cut.")),
    }

    on_beat = music.get("cut_on_beat_pct_target")
    beats = {
        "snap": bool(on_beat and on_beat >= SNAP_TO_BEATS_MIN_PCT),
        "cut_on_beat_pct_target": on_beat,
        "snap_cuts_to_beats": {"toleranceSec": 0.3},
    }

    words = style_words(profile)
    look_name = f"{genre} - my style"[:SAVE_NAME_MAX_CHARS]

    notes = [
        "Eddie's `pacing` option sets how much pause to keep between spoken "
        "lines; the archive does not measure that, so the plan leaves it unset.",
        "Shot-by-shot pacing is checked after the build: export the edit "
        "(fcpxml or otio) and run compare_timeline.",
    ]
    if not music.get("present"):
        notes.append("No music analysis in the archive; beat snapping is off.")
    if not learned.get("edit_profile"):
        notes.append("No project files learned yet. Run `film-style add-project` on past "
                     "timelines, then `learn-edits`, to add trims, b-roll, slow motion, "
                     "punch-ins and measured transition lengths.")
    if not learned.get("soundbites"):
        notes.append("No spoken-line learning yet. Run `film-style learn-soundbites`.")

    card = learned.get("eddie_card")
    apply_style = {
        "style": words,
        "plan": {"mode": "plan", "style": words},
        "save": {"mode": "save", "style": words, "saveName": look_name},
    }
    if card:
        apply_style["card"] = card.get("data")
        apply_style["card_name"] = card.get("name")
        apply_style["plan_with_card"] = {"mode": "plan", "card": card.get("data")}
    sb = learned.get("soundbites") or {}

    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "genre": profile.get("genre"),
        "film_count": profile.get("film_count"),
        "create_edit_result": build,
        "scene_targets": scenes,
        "transitions": transitions,
        "beats": beats,
        "grade": _grade(profile.get("color") or {}),
        "apply_style": apply_style,
        "structure": (learned.get("structure") or {}).get("sections") or None,
        "visual": _visual(learned.get("edit_profile") or {}),
        "soundbites": ({"stats": sb.get("stats"), "rules": sb.get("rules"),
                        "written_rules": sb.get("written_rules"),
                        "examples": "call get_soundbite_examples"} if sb else None),
        "corrections": (learned.get("corrections") or {}).get("rules") or None,
        "recipe": _recipe(profile, brief),
        "workflow": [
            "get_reference_film: pick the past film closest to this wedding "
            "(venue, season, or a film named by the editor) and follow its sections.",
            "list_sources and get_transcript: read the vows, letters and toasts.",
            "get_soundbite_examples: see which lines this editor keeps, then "
            "choose lines the same way.",
            "create_edit_result: pass `brief` and the duration fields from "
            "create_edit_result, soundbites in the running order from `structure`; "
            "add picture selects from get_eddie_selects.",
            "add_brolls, set_speed_ramp, crop_segments: follow `visual`.",
            "set_transitions: follow transitions.how.",
            "snap_cuts_to_beats: only if beats.snap is true.",
            "grade_edit: optional starting grade from grade.grade_edit.",
            "export_edit (fcpxml or otio), then compare_timeline on the file; "
            "trim or extend the shots listed in shot_deviations.",
            "When the editor fixes the cut, run learn_correction on Eddie's "
            "export and their fixed timeline so the next build improves.",
        ],
        "notes": notes,
    }


def selects_from_scores(scores: dict, min_score: int = 70,
                        use_original_names: bool = False) -> dict:
    """Turn ``clip-scores.json`` into soundbites for ``create_edit_result``.

    Each kept clip becomes ``{sourceId, fileName, in, out, reason}`` with the
    usable range found by ``score-clips --detect-trims`` (or the whole clip
    when no trim was run). ``sourceId`` is the file name, which Eddie
    resolves against the project's sources (extension optional).
    """
    soundbites: list[dict] = []
    whole_clips = 0
    skipped = {"rejected": 0, "below_min_score": 0, "no_usable_range": 0}
    for rec in scores.get("clips") or []:
        if rec.get("rejection"):
            skipped["rejected"] += 1
            continue
        score = rec.get("score") or 0
        if score < min_score:
            skipped["below_min_score"] += 1
            continue
        duration = float(rec.get("duration_sec") or 0)
        trim = rec.get("trim") or {}
        t_in = float(trim.get("trim_in_sec", 0.0))
        t_out = float(trim.get("trim_out_sec", duration)) if trim else duration
        if t_out - t_in <= 0:
            skipped["no_usable_range"] += 1
            continue
        if t_in <= 0 and t_out >= duration:
            whole_clips += 1
        file_name = Path(rec.get("file") or "").name
        original = Path(rec.get("original") or "").name
        source = original if (use_original_names and original) else file_name
        reason = f"score {score}"
        if rec.get("scene"):
            reason += f", {rec['scene']}"
        if trim.get("reason"):
            reason += f", trim: {trim['reason']}"
        soundbites.append({
            "sourceId": source,
            "fileName": original or file_name,
            "in": round(t_in, 3),
            "out": round(t_out, 3),
            "reason": reason,
        })
    notes = []
    if whole_clips:
        notes.append(
            f"{whole_clips} clip(s) use their whole length (no trim found or "
            "--detect-trims not run). Eddie refuses whole untranscribed clips "
            "unless create_edit_result is called with allowWholeSourceClips: true."
        )
    return {
        "min_score": min_score,
        "kept": len(soundbites),
        "whole_clips": whole_clips,
        "skipped": skipped,
        "soundbites": soundbites,
        "notes": notes + [
            "Pass `soundbites` to Eddie's create_edit_result. Clips are in "
            "file order, which is usually camera order.",
            "sourceId is the scored file's name; if Eddie holds the camera "
            "originals under other names, rerun with original names or map "
            "them with list_sources.",
        ],
    }
