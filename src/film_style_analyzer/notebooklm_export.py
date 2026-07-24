"""NotebookLM export — produce a single markdown brief that NotebookLM can
ingest as a source.

NotebookLM has no public API, so this is a paste-bridge: we produce the
markdown, you upload it as a source in your notebook, then NotebookLM can
chat about your style alongside the YouTube videos you've also added as
sources.

The brief is dense: profile rules, pacing curve described in prose, audio
design summary, transcript excerpts (if available), per-scene rules,
similar-film clusters, and any saved YouTube inspirations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .genre_pack import GenrePack
from .schemas import FilmAnalysis


def build_brief_intro(pack: GenrePack, brand_name: str, n: int) -> str:
    """Render the per-genre opening paragraph using the pack's prompt template."""
    return pack.prompts["notebooklm_brief_intro"].format(brand_name=brand_name, n=n)


def export_brief(
    films: list[FilmAnalysis],
    profile: dict[str, Any],
    pack: GenrePack,
    inspirations: list[dict] | None = None,
    *,
    title: str = "Editing Style Profile",
    brand_name: str = "the editor",
) -> str:
    """Produce a markdown document suitable for NotebookLM ingestion."""
    out: list[str] = []

    out.append(f"# {title}")
    out.append("")
    out.append(
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')} from "
        f"{len(films)} analyzed {pack.display_name}s._"
    )
    out.append("")
    out.append(build_brief_intro(pack, brand_name=brand_name, n=len(films)))
    out.append("")
    out.append(
        "This document is a complete profile of one editor's style. Treat "
        "every numerical rule as a binding constraint and every per-scene "
        "guideline as a default unless explicitly overridden."
    )
    out.append("")
    out.append("---")
    out.append("")

    # ---- 1. Editing rules ----
    rules = profile.get("rules") or []
    if rules:
        out.append("## Binding Rules")
        out.append("")
        for r in rules:
            out.append(f"- {r}")
        out.append("")

    # ---- 2. Pacing curve described in prose ----
    pacing = profile.get("pacing") or {}
    decile = pacing.get("decile_curve") or []
    if decile:
        out.append("## Pacing Curve")
        out.append("")
        out.append(
            "Across the run-time, the editor's average clip duration moves as "
            "follows (each value is the mean clip duration in that decile of "
            "the film):"
        )
        out.append("")
        out.append("| Position | Avg clip |")
        out.append("|---|---|")
        for i, v in enumerate(decile):
            out.append(f"| {i * 10}–{(i + 1) * 10}% | {v:.2f}s |")
        out.append("")
        # Plain-English summary of the curve shape.
        if len(decile) >= 4:
            opening = sum(decile[:2]) / 2
            mid = sum(decile[3:7]) / 4
            closing = sum(decile[8:]) / 2
            shape = []
            if opening > mid * 1.15:
                shape.append("opens slowly")
            if mid < min(opening, closing) * 0.95:
                shape.append("accelerates through the middle")
            if closing > mid * 1.05:
                shape.append("relaxes near the close")
            if shape:
                out.append("**Shape:** " + ", ".join(shape) + ".")
                out.append("")

    # ---- 3. Transition mix ----
    trans = profile.get("transitions") or {}
    if trans:
        out.append("## Transitions")
        out.append("")
        out.append(
            f"- **Hard cuts:** {trans.get('hard_cut_pct', 0):.0f}% — the dominant transition."
        )
        out.append(
            f"- **Dissolves:** {trans.get('dissolve_pct', 0):.0f}% (~{trans.get('avg_dissolves_per_film', 0):.0f} per film, used as scene-break punctuation)."
        )
        out.append(
            f"- **Fades:** {trans.get('fade_pct', 0):.0f}% (typically only at the very start and end)."
        )
        out.append("")

    # ---- 4. Audio design ----
    audio = profile.get("audio") or {}
    if audio.get("present"):
        out.append("## Audio Design")
        out.append("")
        if audio.get("first_speech_at_pct_target") is not None:
            out.append(
                f"- The first speech (vows/toast/voiceover) enters around "
                f"**{audio['first_speech_at_pct_target']:.0f}% into the film** "
                f"(~{audio.get('first_speech_at_sec_target', 0):.0f}s)."
            )
        if audio.get("speech_over_music_pct_target"):
            out.append(
                f"- Speech plays over music for ~"
                f"**{audio['speech_over_music_pct_target']:.0f}% of the run-time**; "
                f"music rarely cuts out underneath."
            )
        if audio.get("avg_speech_segment_sec_target"):
            out.append(
                f"- Speech excerpts average "
                f"**{audio['avg_speech_segment_sec_target']:.1f} seconds**, "
                f"longest ~{audio.get('longest_speech_segment_sec_target', 0):.0f}s."
            )
        out.append("")

    # ---- 5. Color ----
    color = profile.get("color") or {}
    if color.get("present"):
        out.append("## Color & Grade")
        out.append("")
        wc = color.get("mean_warm_cool", 0) or 0
        tendency = "warm" if wc > 0.1 else ("cool" if wc < -0.1 else "neutral")
        out.append(
            f"- Grade leans **{tendency}** (warm/cool index {wc:+.2f}, range −1 cool to +1 warm)."
        )
        if color.get("mean_luminance") is not None:
            out.append(
                f"- Mean luminance **{color['mean_luminance']:.0f}/255**, "
                f"contrast σ **{color.get('mean_contrast', 0):.0f}**."
            )
        palette = color.get("dominant_palette") or []
        if palette:
            sample = ", ".join(p["hex"] for p in palette[:6])
            out.append(f"- Dominant palette across the corpus: {sample}.")
        if color.get("tone_labels_seen"):
            seen = ", ".join(
                f"{k} ({v})"
                for k, v in sorted(color["tone_labels_seen"].items(), key=lambda kv: -kv[1])[:5]
            )
            out.append(f"- Tone labels observed: {seen}.")
        out.append("")

    # ---- 6. Shot mix ----
    shot = profile.get("shot_mix") or {}
    if shot.get("labeled_clips"):
        out.append("## Shot Mix")
        out.append("")
        out.append(
            f"Across {shot['labeled_clips']} labeled clips, the dominant shot "
            f"size is **{shot['dominant'].replace('_', ' ')}**. Distribution:"
        )
        out.append("")
        for k, v in sorted(shot["distribution"].items(), key=lambda kv: -kv[1]):
            out.append(f"- {k.replace('_', ' ')}: {v:.1f}%")
        out.append("")

    # ---- 7. Music ----
    music = profile.get("music") or {}
    if music.get("present"):
        out.append("## Music")
        out.append("")
        if music.get("target_tempo_range_bpm"):
            lo, hi = music["target_tempo_range_bpm"]
            out.append(
                f"- Tempo range **{lo:.0f}–{hi:.0f} BPM** "
                f"(avg {music.get('avg_tempo_bpm', 0):.0f})."
            )
        if music.get("cut_on_beat_pct_target"):
            out.append(
                f"- Roughly **{music['cut_on_beat_pct_target']:.0f}% of cuts "
                f"land on a music beat** (within ~60 ms tolerance)."
            )
        if music.get("common_keys"):
            keys = ", ".join(f"{k['key']} ({k['count']})" for k in music["common_keys"])
            out.append(f"- Most common keys: {keys}.")
        out.append("")

    # ---- 8. Per-scene rules ----
    scenes = profile.get("scenes") or {}
    if scenes:
        out.append("## Per-Scene Rules")
        out.append("")
        out.append(
            "Each scene type cuts at a different pace and follows different "
            "audio conventions. Use these as the scene-specific defaults:"
        )
        out.append("")
        out.append("| Scene | Avg duration | Avg clips | Avg clip dur |")
        out.append("|---|---|---|---|")
        for label, s in sorted(scenes.items(), key=lambda kv: -kv[1]["pct_of_total_runtime"]):
            out.append(
                f"| {label.replace('_', ' ')} | "
                f"{s['avg_duration_sec']:.1f}s | {s['avg_clip_count']:.0f} | "
                f"{s['avg_clip_duration_sec']:.2f}s |"
            )
        out.append("")

    # ---- 9. Structure ----
    structure = profile.get("structure") or {}
    if structure:
        out.append("## Opening & Closing")
        out.append("")
        opening = structure.get("opening") or {}
        closing = structure.get("closing") or {}
        if opening.get("first_cut_at_sec_target"):
            out.append(
                f"- Hold the first shot for ~"
                f"**{opening['first_cut_at_sec_target']:.1f}s** before the "
                f"first cut."
            )
        if closing.get("fade_to_black_ratio") is not None:
            ratio = closing["fade_to_black_ratio"]
            if ratio > 0.5:
                out.append(f"- End with a **fade to black** ({ratio:.0%} of films do).")
            else:
                out.append(f"- Fade to black on **{ratio:.0%}** of films — not standard.")
        out.append("")

    # ---- 10. Sample transcript excerpts ----
    excerpts = _gather_top_transcript_excerpts(films, max_per_film=1, max_total=8)
    if excerpts:
        out.append("## Speech Excerpts (sample)")
        out.append("")
        out.append(
            "The kind of spoken-word content the editor pulls into the film. "
            "These are vow / toast / voiceover passages that survived the cut:"
        )
        out.append("")
        for ex in excerpts:
            out.append(f"> {ex['text']}")
            out.append(f"_— {ex['filename']}, {ex['start_sec']:.0f}s – {ex['end_sec']:.0f}s_")
            out.append("")

    # ---- 11. Source films ----
    out.append("## Source Films")
    out.append("")
    out.append(f"This profile was built from {len(films)} films. Per-film summaries:")
    out.append("")
    for f in films:
        meta = f.metadata or {}
        tags = ", ".join(f"{k}: {v}" for k, v in sorted(meta.items())) or "no tags"
        out.append(
            f"- **{f.film.filename}** — "
            f"{f.film.duration_sec / 60:.1f} min, "
            f"{f.cuts.total} cuts, "
            f"{f.pacing.avg_clip_duration_sec:.2f}s avg clip — _{tags}_"
        )
    out.append("")

    # ---- 12. Inspirations from YouTube ----
    if inspirations:
        out.append("## YouTube Inspirations")
        out.append("")
        out.append(
            "The user has flagged these YouTube videos as stylistic "
            "references. Each was analyzed by Gemini for pacing, shots, "
            "audio, and grade:"
        )
        out.append("")
        for ins in inspirations:
            out.append(f"### {ins['url']}")
            out.append("")
            ana = ins.get("analysis") or {}
            for k in (
                "pacing",
                "shot_selection",
                "audio_design",
                "color_grade",
                "structure",
                "relevance",
            ):
                v = ana.get(k)
                if v:
                    label = k.replace("_", " ").title()
                    if isinstance(v, list):
                        v = "; ".join(str(x) for x in v)
                    out.append(f"- **{label}:** {v}")
            distinctive = ana.get("distinctive_choices")
            if distinctive:
                out.append("- **Distinctive choices:**")
                for d in distinctive:
                    out.append(f"  - {d}")
            out.append("")

    out.append("---")
    out.append("")
    out.append(
        "_End of brief. Paste this whole document as a NotebookLM source "
        "alongside any YouTube reference videos to ground NotebookLM's "
        "answers in this specific editor's measured style._"
    )

    return "\n".join(out)


def _gather_top_transcript_excerpts(
    films: list[FilmAnalysis],
    *,
    max_per_film: int = 1,
    max_total: int = 8,
) -> list[dict]:
    """Pick the longest transcript segment from each film, capped overall."""
    out: list[dict] = []
    for f in films:
        if not f.transcript or not f.transcript.get("segments"):
            continue
        segs = sorted(
            f.transcript["segments"],
            key=lambda s: -((s.get("end_sec") or 0) - (s.get("start_sec") or 0)),
        )
        for s in segs[:max_per_film]:
            text = (s.get("text") or "").strip()
            if not text:
                continue
            out.append(
                {
                    "filename": f.film.filename,
                    "start_sec": s.get("start_sec") or 0,
                    "end_sec": s.get("end_sec") or 0,
                    "text": text,
                }
            )
            if len(out) >= max_total:
                return out
    return out


def write_brief(
    films: list[FilmAnalysis],
    profile: dict,
    output_path: Path,
    pack: GenrePack,
    *,
    inspirations: list[dict] | None = None,
    title: str = "Editing Style Profile",
    brand_name: str = "the editor",
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        export_brief(films, profile, pack, inspirations, title=title, brand_name=brand_name)
    )
    return output_path
