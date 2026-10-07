"""Compare an edited timeline against the archive's aggregate stats.

One report builder shared by the CLI ``compare`` command, the dashboard's
``/api/compare`` endpoint and the MCP ``compare_timeline`` tool.
"""

from __future__ import annotations

# A shot is flagged when it runs this far from the profile's average for
# its point in the film, and by at least MIN_SHOT_DELTA_SEC in absolute terms.
LONG_SHOT_RATIO = 1.5
SHORT_SHOT_RATIO = 0.6
MIN_SHOT_DELTA_SEC = 0.5


def _visible_or_sequential(cut: dict) -> list[dict]:
    clips = cut.get("visible_clips")
    if clips:
        return clips
    out, t = [], 0.0
    for i, d in enumerate(cut.get("clip_durations") or []):
        out.append({"index": i, "name": "", "start_sec": round(t, 3),
                    "end_sec": round(t + d, 3), "duration_sec": round(d, 3)})
        t += d
    return out


def shot_deviations(cut: dict, expected_deciles: list[float]) -> list[dict]:
    """Shots that run long or short against the profile's pacing curve.

    Each shot is judged against the average shot length of the decile its
    midpoint falls in. Sorted with the largest deviation first.
    """
    clips = _visible_or_sequential(cut)
    if not clips or not expected_deciles:
        return []
    total = clips[-1]["end_sec"] - clips[0]["start_sec"]
    if total <= 0:
        return []
    origin = clips[0]["start_sec"]

    out: list[dict] = []
    for c in clips:
        mid_pct = ((c["start_sec"] + c["end_sec"]) / 2 - origin) / total
        decile = min(9, max(0, int(mid_pct * 10)))
        if decile >= len(expected_deciles):
            continue
        expected = expected_deciles[decile]
        actual = c["duration_sec"]
        if not expected:
            continue
        ratio = actual / expected
        delta = actual - expected
        if abs(delta) < MIN_SHOT_DELTA_SEC:
            continue
        if ratio > LONG_SHOT_RATIO:
            action = "trim"
        elif ratio < SHORT_SHOT_RATIO:
            action = "extend"
        else:
            continue
        out.append({
            "index": c["index"],
            "name": c.get("name") or "",
            "start_sec": c["start_sec"],
            "end_sec": c["end_sec"],
            "duration_sec": actual,
            "decile": decile,
            "expected_sec": round(expected, 2),
            "action": action,
            "by_sec": round(abs(delta), 2),
            "ratio": round(ratio, 2),
        })
    out.sort(key=lambda s: abs(s["ratio"] - 1), reverse=True)
    return out


def build_report(cut: dict, profile: dict) -> dict:
    """Decile- and shot-level deviation report between a cut and the profile."""
    if not profile:
        return {"empty_profile": True, "cut": cut}

    pdur = profile.get("duration", {})
    pclips = profile.get("clip_counts", {})
    ppace = profile.get("pacing", {})
    ptrans = profile.get("transitions", {})

    expected_clips = pclips.get("avg") or 0
    expected_avg = ppace.get("avg_clip_sec") or 0
    expected_diss = ptrans.get("avg_dissolves_per_film") or 0
    expected_deciles = ppace.get("avg_deciles") or []
    durations = cut.get("clip_durations") or []

    actual_deciles: list[float] = []
    if durations:
        n = len(durations)
        for i in range(10):
            slc = durations[i * n // 10:(i + 1) * n // 10]
            actual_deciles.append(round(sum(slc) / max(1, len(slc)), 3) if slc else 0.0)

    pacing_diff = []
    for i, (a, e) in enumerate(zip(actual_deciles, expected_deciles)):
        delta_pct = ((a - e) / e * 100) if e else 0
        pacing_diff.append({
            "decile": i,
            "actual": a,
            "expected": e,
            "delta_pct": round(delta_pct, 1),
        })

    delta_clips = (
        (cut["clip_count"] - expected_clips) / expected_clips * 100
        if expected_clips else 0
    )
    delta_pace = (
        (cut["avg_clip_sec"] - expected_avg) / expected_avg * 100
        if expected_avg else 0
    )

    suggestions: list[str] = []
    if abs(delta_pace) > 15:
        direction = "Tighten" if delta_pace > 0 else "Lengthen"
        suggestions.append(f"{direction} clips toward {expected_avg:.2f}s avg.")
    if abs(delta_clips) > 20:
        direction = "Remove" if delta_clips > 0 else "Add"
        suggestions.append(f"{direction} clips toward ~{expected_clips:.0f} total.")
    if expected_diss and cut["dissolves"] > expected_diss * 1.5:
        suggestions.append(f"Reduce dissolves toward ~{expected_diss:.1f}.")
    for d in pacing_diff:
        if abs(d["delta_pct"]) > 25 and d["expected"]:
            verb = "tighten" if d["delta_pct"] > 0 else "lengthen"
            suggestions.append(
                f"At {d['decile']*10}-{(d['decile']+1)*10}% — {verb} "
                f"({d['actual']:.2f}s → {d['expected']:.2f}s)."
            )

    duration_in_range = (
        pdur.get("min_sec") is not None and
        pdur.get("max_sec") is not None and
        pdur["min_sec"] <= cut["total_duration_sec"] <= pdur["max_sec"]
    )

    return {
        "empty_profile": False,
        "profile": {
            "film_count": profile.get("film_count", 0),
            "duration": pdur,
            "clip_counts": pclips,
            "pacing": ppace,
            "transitions": ptrans,
        },
        "cut": cut,
        "deltas": {
            "clip_count_pct": round(delta_clips, 1),
            "avg_clip_pct": round(delta_pace, 1),
            "duration_in_range": duration_in_range,
        },
        "pacing_diff": pacing_diff,
        "shot_deviations": shot_deviations(cut, expected_deciles),
        "suggestions": suggestions,
    }
