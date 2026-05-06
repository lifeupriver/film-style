"""Aggregate per-film analyses into cross-film stats."""

from __future__ import annotations

import statistics
from typing import Iterable

from .schemas import FilmAnalysis


def aggregate(analyses: Iterable[FilmAnalysis]) -> dict:
    films = list(analyses)
    if not films:
        return {}

    durations = [f.film.duration_sec for f in films]
    clip_counts = [f.cuts.total for f in films]
    all_clip_durations = [c.duration_sec for f in films for c in f.cuts.clips]

    total_hard = sum(f.transitions.hard_cut for f in films)
    total_diss = sum(f.transitions.dissolve for f in films)
    total_fade = sum(f.transitions.fade_in + f.transitions.fade_out for f in films)
    total_still = sum(f.transitions.still_hold for f in films)
    total_trans = total_hard + total_diss + total_fade + total_still or 1

    # Only films with enough clips to fill every decile (>= 10) contribute,
    # otherwise empty slices were padded with 0.0 and would drag the average.
    deciles = [
        f.pacing.pacing_curve_by_decile for f in films
        if f.pacing.pacing_curve_by_decile and f.cuts.total >= 10
    ]
    avg_deciles = (
        [round(statistics.fmean(col), 2) for col in zip(*deciles)] if deciles else []
    )

    first_5_avgs = [f.structure.opening["first_5_clips_avg_duration_sec"] for f in films]
    last_5_avgs = [f.structure.closing["last_5_clips_avg_duration_sec"] for f in films]
    first_cuts = [f.structure.opening["first_cut_at_sec"] for f in films]

    fades_to_black = sum(1 for f in films if f.structure.closing.get("fade_to_black"))

    # Audio aggregation across films that have it.
    with_audio = [f for f in films if f.audio and f.audio.get("summary")]
    audio_summary: dict | None = None
    if with_audio:
        sums = [f.audio["summary"] for f in with_audio]
        def _avg(key: str) -> float | None:
            vals = [s.get(key) for s in sums if s.get(key) is not None]
            return round(statistics.fmean(vals), 2) if vals else None
        audio_summary = {
            "films_with_audio": len(with_audio),
            "music_only_pct_avg": _avg("music_only_pct"),
            "speech_over_music_pct_avg": _avg("speech_over_music_pct"),
            "speech_only_pct_avg": _avg("speech_only_pct"),
            "ambient_pct_avg": _avg("ambient_pct"),
            "first_speech_at_pct_avg": _avg("first_speech_at_pct"),
            "first_speech_at_sec_avg": _avg("first_speech_at_sec"),
            "avg_speech_segment_sec": _avg("avg_speech_segment_sec"),
            "longest_speech_segment_sec_avg": _avg("longest_speech_segment_sec"),
            "speech_segments_per_film_avg": _avg("speech_segment_count"),
        }

    with_transcript = [f for f in films if f.transcript]
    transcript_summary: dict | None = None
    if with_transcript:
        word_counts = [f.transcript.get("total_words", 0) for f in with_transcript]
        speakers = [f.transcript.get("speakers_detected", 0) for f in with_transcript]
        transcript_summary = {
            "films_with_transcript": len(with_transcript),
            "avg_total_words": round(statistics.fmean(word_counts), 1),
            "avg_speakers_detected": round(statistics.fmean(speakers), 2),
        }

    gemini_excerpts = [
        {"filename": f.film.filename, "analysis": f.gemini_analysis}
        for f in films if f.gemini_analysis
    ]

    # Per-scene-label aggregation across films that have chapter labels.
    label_buckets: dict[str, list[dict]] = {}
    total_film_seconds = sum(durations) or 1.0
    for f in films:
        for ch in f.chapters:
            if not ch.label:
                continue
            label_buckets.setdefault(ch.label, []).append({
                "duration_sec": ch.duration_sec,
                "clip_count": ch.clip_count,
                "avg_clip_sec": ch.avg_clip_sec,
            })
    scene_breakdown: list[dict] = []
    for label, entries in sorted(label_buckets.items(), key=lambda kv: -sum(e["duration_sec"] for e in kv[1])):
        total_dur = sum(e["duration_sec"] for e in entries)
        scene_breakdown.append({
            "label": label,
            "occurrences": len(entries),
            "pct_of_total_runtime": round(100 * total_dur / total_film_seconds, 1),
            "avg_duration_sec": round(total_dur / len(entries), 2) if entries else 0.0,
            "avg_clip_count": round(statistics.fmean(e["clip_count"] for e in entries), 1),
            "avg_clip_duration_sec": round(statistics.fmean(e["avg_clip_sec"] for e in entries), 2),
        })

    return {
        "film_count": len(films),
        "duration": {
            "min_sec": round(min(durations), 1),
            "max_sec": round(max(durations), 1),
            "avg_sec": round(statistics.fmean(durations), 1),
            "median_sec": round(statistics.median(durations), 1),
        },
        "clip_counts": {
            "min": min(clip_counts),
            "max": max(clip_counts),
            "avg": round(statistics.fmean(clip_counts), 1),
        },
        "pacing": {
            "avg_clip_sec": round(statistics.fmean(all_clip_durations), 2),
            "median_clip_sec": round(statistics.median(all_clip_durations), 2),
            "std_dev_sec": round(statistics.pstdev(all_clip_durations), 2),
            "min_clip_sec": round(min(all_clip_durations), 2),
            "max_clip_sec": round(max(all_clip_durations), 2),
            "avg_deciles": avg_deciles,
        },
        "transitions": {
            "hard_cut_pct": round(100 * total_hard / total_trans, 1),
            "dissolve_pct": round(100 * total_diss / total_trans, 1),
            "fade_pct": round(100 * total_fade / total_trans, 1),
            "still_hold_pct": round(100 * total_still / total_trans, 1),
            "avg_dissolves_per_film": round(total_diss / len(films), 1),
            "avg_still_holds_per_film": round(total_still / len(films), 1),
        },
        "opening": {
            "avg_first_cut_at_sec": round(statistics.fmean(first_cuts), 2),
            "avg_first_5_clips_sec": round(statistics.fmean(first_5_avgs), 2),
        },
        "closing": {
            "avg_last_5_clips_sec": round(statistics.fmean(last_5_avgs), 2),
            "fade_to_black_ratio": round(fades_to_black / len(films), 2),
        },
        "audio": audio_summary,
        "transcript": transcript_summary,
        "gemini_analyses": gemini_excerpts,
        "scene_breakdown": scene_breakdown,
        "films": [
            {
                "filename": f.film.filename,
                "duration_sec": f.film.duration_sec,
                "clips": f.cuts.total,
                "avg_clip_sec": f.pacing.avg_clip_duration_sec,
            }
            for f in films
        ],
    }
