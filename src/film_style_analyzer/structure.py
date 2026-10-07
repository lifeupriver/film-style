"""The order a film is told in, and finding the past film to imitate.

``build_structure_template`` reads the labelled chapters of every analysed
film (``guide --vision`` labels them) and any section markers in registered
project timelines, and returns the usual running order: which sections
appear, where each one starts and ends as a share of the film, and how the
films open and close.

``find_reference_films`` picks the past films most like a new one, by style
similarity to a named film and/or by shared metadata (venue, season, ...),
and bundles what is known about each so it can be imitated directly.
"""

from __future__ import annotations

import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def _norm_label(label: str | None) -> str | None:
    if not label:
        return None
    s = label.strip().lower().replace(" ", "_")
    return s or None


def film_sections(film) -> list[dict]:
    """Consecutive labelled chapters merged into sections, as shares of the film."""
    total = film.film.duration_sec or 0.0
    out: list[dict] = []
    for ch in film.chapters:
        label = _norm_label(ch.label)
        if not label or label == "other" or not total:
            continue
        if out and out[-1]["label"] == label:
            out[-1]["end_sec"] = ch.end_sec
        else:
            out.append({"label": label, "start_sec": ch.start_sec, "end_sec": ch.end_sec})
    for s in out:
        s["start_pct"] = round(100 * s["start_sec"] / total, 1)
        s["end_pct"] = round(100 * s["end_sec"] / total, 1)
        s["duration_sec"] = round(s["end_sec"] - s["start_sec"], 2)
    return out


def project_sections(project: dict) -> list[dict]:
    """Sections from an edit project's markers: each runs to the next marker."""
    dur = project.get("duration_sec") or 0.0
    marks = [m for m in project.get("markers") or [] if m.get("name")]
    out: list[dict] = []
    for i, m in enumerate(marks):
        end = marks[i + 1]["timeline_sec"] if i + 1 < len(marks) else dur
        label = _norm_label(m["name"])
        if not label or not dur or end <= m["timeline_sec"]:
            continue
        if out and out[-1]["label"] == label:
            out[-1]["end_sec"] = end
            continue
        out.append({"label": label, "start_sec": m["timeline_sec"], "end_sec": end})
    for s in out:
        s["start_pct"] = round(100 * s["start_sec"] / dur, 1)
        s["end_pct"] = round(100 * s["end_sec"] / dur, 1)
        s["duration_sec"] = round(s["end_sec"] - s["start_sec"], 2)
    return out


def build_structure_template(films: list, projects: list[dict] | None = None) -> dict:
    sequences: list[list[dict]] = []
    sources: list[str] = []
    for f in films:
        secs = film_sections(f)
        if secs:
            sequences.append(secs)
            sources.append(Path(f.film.filename).stem)
    for rec in projects or []:
        secs = project_sections(rec.get("project") or rec)
        if secs:
            sequences.append(secs)
            sources.append(f"project:{rec.get('name')}")

    n = len(sequences)
    by_label: dict[str, list[dict]] = {}
    for seq in sequences:
        seen = set()
        for s in seq:
            if s["label"] in seen:
                continue  # first occurrence decides placement
            seen.add(s["label"])
            by_label.setdefault(s["label"], []).append(s)

    sections = []
    for label, items in by_label.items():
        sections.append({
            "label": label,
            "films_with": len(items),
            "presence_pct": round(100 * len(items) / n, 1) if n else 0.0,
            "start_pct": round(statistics.median(i["start_pct"] for i in items), 1),
            "end_pct": round(statistics.median(i["end_pct"] for i in items), 1),
            "duration_sec": round(statistics.median(i["duration_sec"] for i in items), 1),
        })
    sections.sort(key=lambda s: s["start_pct"])

    openers = Counter(seq[0]["label"] for seq in sequences)
    closers = Counter(seq[-1]["label"] for seq in sequences)
    pairs = Counter((a["label"], b["label"]) for seq in sequences
                    for a, b in zip(seq, seq[1:]))

    template = {
        "schema_version": "1.0",
        "films_with_sections": n,
        "sources": sources,
        "sections": sections,
        "opening": [{"label": k, "films": v} for k, v in openers.most_common(3)],
        "closing": [{"label": k, "films": v} for k, v in closers.most_common(3)],
        "common_moves": [{"from": a, "to": b, "films": c} for (a, b), c in pairs.most_common(8)],
    }
    template["rules"] = structure_rules(template)
    return template


def structure_rules(t: dict) -> list[str]:
    n = t["films_with_sections"]
    if not n:
        return []
    usual = [s for s in t["sections"] if s["presence_pct"] >= 50]
    rules = []
    if usual:
        rules.append("Running order: " + " → ".join(
            f"{s['label'].replace('_', ' ')} ({s['start_pct']:.0f}–{s['end_pct']:.0f}%)"
            for s in usual) + ".")
    rare = [s for s in t["sections"] if s["presence_pct"] < 50]
    if rare:
        rules.append("Sometimes included: " + ", ".join(
            s["label"].replace("_", " ") for s in rare) + ".")
    if t["opening"]:
        o = t["opening"][0]
        rules.append(f"Open on {o['label'].replace('_', ' ')} ({o['films']} of {n} films).")
    if t["closing"]:
        c = t["closing"][0]
        rules.append(f"Close on {c['label'].replace('_', ' ')} ({c['films']} of {n} films).")
    return rules


# ---------------------------------------------------------------------------
# Reference films
# ---------------------------------------------------------------------------

def _metadata_matches(film, wanted: dict[str, str]) -> int:
    md = {k.lower(): str(v).strip().lower() for k, v in (film.metadata or {}).items() if v}
    return sum(1 for k, v in wanted.items() if md.get(k.lower()) == str(v).strip().lower())


def find_reference_films(films: list, *, like: str | None = None,
                         metadata: dict[str, str] | None = None, top: int = 3,
                         projects: list[dict] | None = None,
                         soundbite_profile: dict | None = None) -> list[dict]:
    """Past films to imitate, best first, each with everything known about it."""
    from .edit_profile import project_metrics
    from .matchmaker import find_similar

    by_stem = {Path(f.film.filename).stem: f for f in films}
    if like and like not in by_stem:
        raise ValueError(f"no analysed film named {like!r}")

    scored: list[dict[str, Any]] = []
    sims = {}
    if like:
        for m in find_similar(by_stem[like], films, top_n=len(films)):
            sims[m["stem"]] = m["similarity"]
    for stem, f in by_stem.items():
        if stem == like:
            continue
        md = _metadata_matches(f, metadata) if metadata else 0
        if metadata and not md and not like:
            continue
        scored.append({"stem": stem, "film": f, "metadata_matches": md,
                       "similarity": sims.get(stem)})
    scored.sort(key=lambda s: (s["metadata_matches"], s["similarity"] or 0,
                               s["film"].analyzed_at), reverse=True)

    proj_by_film = {r.get("film_stem"): r for r in projects or [] if r.get("film_stem")}
    picks_by_film: dict[str, list] = {}
    for ex in (soundbite_profile or {}).get("examples") or []:
        if ex.get("film_stem"):
            picks_by_film.setdefault(ex["film_stem"], []).append(ex)

    out = []
    for s in scored[:top]:
        f = s["film"]
        rec = proj_by_film.get(s["stem"])
        out.append({
            "stem": s["stem"],
            "similarity": s["similarity"],
            "metadata_matches": s["metadata_matches"],
            "metadata": f.metadata or {},
            "duration_sec": f.film.duration_sec,
            "shots": f.cuts.total,
            "avg_shot_sec": f.pacing.avg_clip_duration_sec,
            "pacing_by_decile": f.pacing.pacing_curve_by_decile,
            "dissolves": f.transitions.dissolve,
            "sections": film_sections(f),
            "project": ({"name": rec["name"], "decisions": project_metrics(rec["project"])}
                        if rec else None),
            "soundbites": picks_by_film.get(s["stem"], []),
        })
    return out
