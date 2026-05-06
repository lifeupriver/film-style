"""Build style-profile.json — the addressable, typed contract for downstream
AI tools that need to assemble cuts in the editor's measured style.

Distinct from the markdown style-guide.md which is for humans. This file
is consumed programmatically:

    profile["pacing"]["target_avg_clip_sec"]              → 3.4
    profile["audio"]["first_speech_at_pct_target"]        → 16.6
    profile["scenes"]["ceremony"]["avg_clip_sec"]         → 4.8
    profile["color"]["dominant_palette"]                  → [...]
    profile["music"]["target_tempo_range_bpm"]            → [90, 130]
    profile["shot_mix"]["distribution"]                   → {"medium": 35.2, ...}
    profile["rules"]                                      → list of "do this" rules
"""

from __future__ import annotations

import statistics
from dataclasses import asdict
from typing import Any

from . import __version__
from .genre_pack import GenrePack
from .schemas import FilmAnalysis


def build_profile(
    films: list[FilmAnalysis],
    aggregated: dict,
    pack: GenrePack,
) -> dict[str, Any]:
    if not films:
        return {
            "schema_version": "1.0",
            "generator_version": __version__,
            "film_count": 0,
            "rules": [],
            "genre": pack.name,
            "genre_display_name": pack.display_name,
            "genre_extensions": {},
        }

    rules: list[str] = []

    pacing = aggregated.get("pacing", {})
    duration = aggregated.get("duration", {})
    transitions = aggregated.get("transitions", {})
    audio = aggregated.get("audio")
    transcript = aggregated.get("transcript")
    scene_breakdown = aggregated.get("scene_breakdown", []) or []

    # ---- pacing -----------------------------------------------------------
    pacing_block = {
        "target_avg_clip_sec": pacing.get("avg_clip_sec"),
        "target_median_clip_sec": pacing.get("median_clip_sec"),
        "min_clip_sec": pacing.get("min_clip_sec"),
        "max_clip_sec": pacing.get("max_clip_sec"),
        "decile_curve": pacing.get("avg_deciles") or [],
        "std_dev_sec": pacing.get("std_dev_sec"),
    }
    if pacing.get("avg_clip_sec"):
        rules.append(
            f"Target average clip duration {pacing['avg_clip_sec']:.2f}s "
            f"(σ {pacing.get('std_dev_sec', 0):.2f}). "
            f"Range: {pacing.get('min_clip_sec', 0):.1f}s – {pacing.get('max_clip_sec', 0):.1f}s."
        )

    # ---- duration / clip count -------------------------------------------
    duration_block = {
        "target_min_sec": duration.get("min_sec"),
        "target_max_sec": duration.get("max_sec"),
        "target_median_sec": duration.get("median_sec"),
        "target_avg_sec": duration.get("avg_sec"),
    }
    if duration.get("min_sec") and duration.get("max_sec"):
        rules.append(
            f"Total runtime should land in {duration['min_sec']:.0f}s – "
            f"{duration['max_sec']:.0f}s "
            f"(median {duration.get('median_sec', 0):.0f}s)."
        )
    cuts_block = aggregated.get("clip_counts", {})

    # ---- transitions ------------------------------------------------------
    transition_block = {
        "hard_cut_pct": transitions.get("hard_cut_pct"),
        "dissolve_pct": transitions.get("dissolve_pct"),
        "fade_pct": transitions.get("fade_pct"),
        "still_hold_pct": transitions.get("still_hold_pct"),
        "avg_dissolves_per_film": transitions.get("avg_dissolves_per_film"),
        "avg_still_holds_per_film": transitions.get("avg_still_holds_per_film"),
    }
    if transitions.get("hard_cut_pct") is not None:
        parts = [
            f"{transitions['hard_cut_pct']:.0f}% hard cuts",
            f"{transitions.get('dissolve_pct', 0):.0f}% dissolves "
            f"(~{transitions.get('avg_dissolves_per_film', 0):.0f} per film)",
        ]
        if pack.still_hold_relevant and transitions.get("still_hold_pct"):
            parts.append(
                f"{transitions['still_hold_pct']:.0f}% still-holds "
                f"(boundaries between motion video and held photographs, "
                f"~{transitions.get('avg_still_holds_per_film', 0):.0f} per film)"
            )
        rules.append(". ".join(parts) + ".")

    # ---- audio ------------------------------------------------------------
    audio_block: dict[str, Any] = {"present": audio is not None}
    if audio:
        audio_block.update({
            "music_only_pct_target": audio.get("music_only_pct_avg"),
            "speech_over_music_pct_target": audio.get("speech_over_music_pct_avg"),
            "ambient_pct_target": audio.get("ambient_pct_avg"),
            "first_speech_at_pct_target": audio.get("first_speech_at_pct_avg"),
            "first_speech_at_sec_target": audio.get("first_speech_at_sec_avg"),
            "speech_segments_per_film_target": audio.get("speech_segments_per_film_avg"),
            "avg_speech_segment_sec_target": audio.get("avg_speech_segment_sec"),
            "longest_speech_segment_sec_target": audio.get("longest_speech_segment_sec_avg"),
        })
        first_pct = audio.get("first_speech_at_pct_avg")
        first_sec = audio.get("first_speech_at_sec_avg") or 0
        speech_over = audio.get("speech_over_music_pct_avg")
        if pack.audio_emphasis == "music_first":
            if first_pct is not None:
                rules.append(
                    f"Hold music alone before any speech for the first "
                    f"{first_pct:.0f}% of the film (~{first_sec:.0f}s)."
                )
            if speech_over:
                rules.append(
                    f"Layer speech over music for ~{speech_over:.0f}% of total "
                    f"runtime; speech rarely plays without music underneath."
                )
        elif pack.audio_emphasis == "voiceover_first":
            if first_pct is not None:
                rules.append(
                    f"Voiceover/dialogue starts within the first "
                    f"{first_pct:.0f}% of runtime (~{first_sec:.1f}s) — lead "
                    f"with the message, not with mood."
                )
        elif pack.audio_emphasis == "interview":
            if speech_over:
                rules.append(
                    f"Interview/dialogue covers ~{speech_over:.0f}% of "
                    f"runtime; cut to b-roll under speech, not over silence."
                )
        elif pack.audio_emphasis == "beat_locked":
            rules.append(
                "Lock cuts to the music beat — see music block for tempo target."
            )
        elif pack.audio_emphasis == "hook_driven":
            if first_sec is not None:
                rules.append(
                    f"Open with a hook in the first 3 seconds; first speech "
                    f"lands at ~{first_sec:.1f}s."
                )

    if transcript:
        audio_block["transcript_avg_total_words"] = transcript.get("avg_total_words")
        audio_block["transcript_avg_speakers"] = transcript.get("avg_speakers_detected")

    # ---- color (per-film aggregate) --------------------------------------
    with_color = [f for f in films if f.color]
    color_block: dict[str, Any] = {"present": bool(with_color)}
    if with_color:
        lum = [f.color.get("mean_luminance") for f in with_color if f.color.get("mean_luminance") is not None]
        contrast = [f.color.get("mean_contrast") for f in with_color if f.color.get("mean_contrast") is not None]
        wc = [f.color.get("mean_warm_cool") for f in with_color if f.color.get("mean_warm_cool") is not None]
        sat = [f.color.get("mean_saturation") for f in with_color if f.color.get("mean_saturation") is not None]
        color_block.update({
            "films_analyzed": len(with_color),
            "mean_luminance": round(statistics.fmean(lum), 1) if lum else None,
            "mean_contrast": round(statistics.fmean(contrast), 1) if contrast else None,
            "mean_warm_cool": round(statistics.fmean(wc), 3) if wc else None,
            "mean_saturation": round(statistics.fmean(sat), 1) if sat else None,
            "dominant_palette": _aggregate_color_palette(with_color),
            "tone_labels_seen": _count_tone_labels(with_color),
        })
        if wc:
            wc_avg = statistics.fmean(wc)
            tendency = "warm" if wc_avg > 0.1 else ("cool" if wc_avg < -0.1 else "neutral")
            rules.append(
                f"Lean {tendency} in grade (warm/cool index {wc_avg:+.2f}). "
                f"Mean luminance {color_block.get('mean_luminance', 0):.0f}/255, "
                f"contrast σ {color_block.get('mean_contrast', 0):.0f}."
            )

    # ---- shot mix --------------------------------------------------------
    shot_mix = _aggregate_shot_mix(films)
    if shot_mix["labeled_clips"]:
        rules.append(_shot_mix_rule(shot_mix))

    # ---- music -----------------------------------------------------------
    with_music = [f for f in films if f.music and f.music.get("has_music")]
    music_block: dict[str, Any] = {"present": bool(with_music)}
    if with_music:
        tempos = [f.music.get("tempo_bpm") for f in with_music if f.music.get("tempo_bpm")]
        if tempos:
            music_block["target_tempo_range_bpm"] = [
                round(min(tempos), 1),
                round(max(tempos), 1),
            ]
            music_block["avg_tempo_bpm"] = round(statistics.fmean(tempos), 1)
            rules.append(
                f"Music tempo lands {min(tempos):.0f}–{max(tempos):.0f} BPM "
                f"(avg {statistics.fmean(tempos):.0f})."
            )
        keys = [f.music.get("key") for f in with_music if f.music.get("key")]
        if keys:
            from collections import Counter
            common = Counter(keys).most_common(3)
            music_block["common_keys"] = [{"key": k, "count": n} for k, n in common]

        # Cut-on-beat — average across films that have it.
        on_beats = [f.music["beat_alignment"]["on_beat_pct"]
                    for f in with_music
                    if f.music.get("beat_alignment")]
        if on_beats:
            avg = round(statistics.fmean(on_beats), 1)
            music_block["cut_on_beat_pct_target"] = avg
            rules.append(
                f"Land {avg:.0f}% of cuts on a music beat "
                f"(within ~60 ms tolerance)."
            )

    # ---- scenes (chapter breakdown) --------------------------------------
    scenes_block = {
        s["label"]: {
            "occurrences": s["occurrences"],
            "pct_of_total_runtime": s["pct_of_total_runtime"],
            "avg_duration_sec": s["avg_duration_sec"],
            "avg_clip_count": s["avg_clip_count"],
            "avg_clip_duration_sec": s["avg_clip_duration_sec"],
        }
        for s in scene_breakdown
    }
    if scenes_block:
        # Build a per-scene pacing rule.
        slowest = max(scene_breakdown, key=lambda s: s["avg_clip_duration_sec"])
        fastest = min(scene_breakdown, key=lambda s: s["avg_clip_duration_sec"])
        if slowest["label"] != fastest["label"]:
            rules.append(
                f"Pacing varies by scene: {slowest['label'].replace('_', ' ')} cuts "
                f"slowest ({slowest['avg_clip_duration_sec']:.1f}s avg), "
                f"{fastest['label'].replace('_', ' ')} fastest "
                f"({fastest['avg_clip_duration_sec']:.1f}s avg)."
            )

    # ---- structure: opening / closing -----------------------------------
    opening = aggregated.get("opening", {})
    closing = aggregated.get("closing", {})
    structure_block = {
        "opening": {
            "first_cut_at_sec_target": opening.get("avg_first_cut_at_sec"),
            "first_5_clips_avg_duration_sec_target": opening.get("avg_first_5_clips_sec"),
        },
        "closing": {
            "last_5_clips_avg_duration_sec_target": closing.get("avg_last_5_clips_sec"),
            "fade_to_black_ratio": closing.get("fade_to_black_ratio"),
        },
    }
    if opening.get("avg_first_cut_at_sec"):
        rules.append(
            f"Hold the first shot for ~{opening['avg_first_cut_at_sec']:.1f}s "
            "before the first cut."
        )
    if closing.get("fade_to_black_ratio") and closing["fade_to_black_ratio"] > 0.5:
        rules.append("End with a fade to black.")

    # ---- final assembly --------------------------------------------------
    return {
        "schema_version": "1.0",
        "generator_version": __version__,
        "film_count": len(films),
        "genre": pack.name,
        "genre_display_name": pack.display_name,
        "genre_extensions": {},
        "duration": duration_block,
        "clip_counts": cuts_block,
        "pacing": pacing_block,
        "transitions": transition_block,
        "audio": audio_block,
        "color": color_block,
        "shot_mix": shot_mix,
        "music": music_block,
        "scenes": scenes_block,
        "structure": structure_block,
        "rules": rules,
        "source_films": [
            {
                "filename": f.film.filename,
                "duration_sec": f.film.duration_sec,
                "clips": f.cuts.total,
                "avg_clip_sec": f.pacing.avg_clip_duration_sec,
                "metadata": f.metadata or {},
            }
            for f in films
        ],
    }


# ---------------- helpers ---------------------------------------------------


def _aggregate_color_palette(films: list[FilmAnalysis], top: int = 8) -> list[dict]:
    bucket: dict[str, float] = {}
    for f in films:
        for entry in (f.color or {}).get("dominant_palette", []) or []:
            bucket[entry["hex"]] = bucket.get(entry["hex"], 0.0) + entry.get("weight", 0.0)
    total = sum(bucket.values()) or 1.0
    items = sorted(bucket.items(), key=lambda kv: -kv[1])[:top]
    return [{"hex": h, "weight": round(w / total, 4)} for h, w in items]


def _count_tone_labels(films: list[FilmAnalysis]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in films:
        label = (f.color or {}).get("tone_label")
        if label:
            out[label] = out.get(label, 0) + 1
    return out


def _aggregate_shot_mix(films: list[FilmAnalysis]) -> dict:
    counts: dict[str, int] = {}
    total = 0
    for f in films:
        for c in f.cuts.clips:
            if not c.shot_size:
                continue
            counts[c.shot_size] = counts.get(c.shot_size, 0) + 1
            total += 1
    if not total:
        return {"labeled_clips": 0, "distribution": {}, "dominant": None}
    pct = {k: round(100 * v / total, 1) for k, v in counts.items()}
    dominant = max(pct.items(), key=lambda kv: kv[1])[0]
    return {
        "labeled_clips": total,
        "distribution": pct,
        "dominant": dominant,
    }


def _shot_mix_rule(mix: dict) -> str:
    pct = mix["distribution"]
    parts = sorted(pct.items(), key=lambda kv: -kv[1])
    pretty = ", ".join(f"{k.replace('_', ' ')} {v:.0f}%" for k, v in parts[:4])
    return f"Shot mix favours {mix['dominant'].replace('_', ' ')}; full distribution: {pretty}."
