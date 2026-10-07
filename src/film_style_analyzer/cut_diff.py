"""Compare two cuts of the same footage.

``evaluate(reference, candidate)`` scores how closely a cut (for example one
Eddie built) matches the editor's own cut of the same wedding: the same
moments, the same lines, the same order, the same pacing. It gives a 0-100
number to improve against and lists what was missed and what was added.

``correction(before, after)`` reads the changes the editor made to a cut
(Eddie's version → their fixed version) and ``correction_rules`` turns a
history of those changes into rules for the next build.

Both take projects parsed by ``edit_decisions.parse_project``. Sources are
matched by ``source_key`` and measured from the start of each file, so the
two cuts can come from different tools.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

from .edit_decisions import intersect_length, ranges_length, used_ranges
from .timeline import flatten_visible

# Score weights. Spoken lines carry the story in a wedding film, so they
# count nearly as much as picture.
W_MOMENTS, W_LINES, W_ORDER, W_PACING = 0.35, 0.25, 0.20, 0.20


def _spoken(project: dict) -> dict[str, list[tuple[float, float]]]:
    """Audible, non-music ranges heard on the main storyline or audio tracks."""
    sub = {**project, "events": [
        e for e in project["events"]
        if e["audible"] and not e.get("is_music")
        and (e["track"] == "audio" or e["layer"] == 0)]}
    return used_ranges(sub, relative=True)


def _overlap(ref: dict, cand: dict) -> dict:
    r_total = sum(ranges_length(v) for v in ref.values())
    c_total = sum(ranges_length(v) for v in cand.values())
    inter = sum(intersect_length(ref[k], cand[k]) for k in ref.keys() & cand.keys())
    recall = inter / r_total if r_total else None
    precision = inter / c_total if c_total else None
    f1 = (2 * recall * precision / (recall + precision)
          if recall and precision else (0.0 if r_total and c_total else None))
    return {"reference_sec": round(r_total, 1), "candidate_sec": round(c_total, 1),
            "shared_sec": round(inter, 1),
            "recall": None if recall is None else round(recall, 3),
            "precision": None if precision is None else round(precision, 3),
            "f1": None if f1 is None else round(f1, 3)}


def _video_events(project: dict) -> list[dict]:
    return [e for e in project["events"] if e["track"] == "video"
            and not e.get("multicam") and e["source_key"]]


def _rel(e: dict) -> tuple[float, float]:
    s0 = e.get("source_start") or 0.0
    lo, hi = sorted((e["source_in"] - s0, e["source_out"] - s0))
    return lo, hi


def _match(a_events: list[dict], b_events: list[dict]) -> list[tuple[dict, dict, float]]:
    """Pair each event in ``a`` with the ``b`` event on the same source that
    shares the most footage."""
    by_key: dict[str, list[dict]] = {}
    for e in b_events:
        by_key.setdefault(e["source_key"], []).append(e)
    pairs = []
    for a in a_events:
        best, best_ov = None, 0.0
        alo, ahi = _rel(a)
        for b in by_key.get(a["source_key"], []):
            blo, bhi = _rel(b)
            ov = min(ahi, bhi) - max(alo, blo)
            if ov > best_ov:
                best, best_ov = b, ov
        if best is not None:
            pairs.append((a, best, best_ov))
    return pairs


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        for rank, i in enumerate(order):
            r[i] = rank
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 3) if den else None


def _shots(project: dict) -> list[dict]:
    return flatten_visible([
        {"start": e["timeline_start"], "end": e["timeline_end"],
         "layer": e["layer"], "name": e["source_key"]}
        for e in _video_events(project)])


def _deciles(shots: list[dict]) -> list[float]:
    if not shots:
        return []
    total = shots[-1]["end_sec"] - shots[0]["start_sec"]
    buckets: list[list[float]] = [[] for _ in range(10)]
    for s in shots:
        mid = ((s["start_sec"] + s["end_sec"]) / 2 - shots[0]["start_sec"]) / total
        buckets[min(9, int(mid * 10))].append(s["duration_sec"])
    return [round(statistics.fmean(b), 2) if b else 0.0 for b in buckets]


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    pairs = [(x, y) for x, y in zip(xs, ys) if x and y]
    if len(pairs) < 3:
        return None
    mx = statistics.fmean(p[0] for p in pairs)
    my = statistics.fmean(p[1] for p in pairs)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    den = math.sqrt(sum((x - mx) ** 2 for x, _ in pairs) * sum((y - my) ** 2 for _, y in pairs))
    return round(num / den, 3) if den else None


def _gaps(ref: dict, cand: dict, ref_project: dict, limit: int = 12) -> list[dict]:
    """Reference footage the candidate left out, longest first, with the time
    it plays at in the reference cut."""
    out = []
    for e in _video_events(ref_project) + [x for x in ref_project["events"] if x["track"] == "audio"
                                           and x["audible"] and not x.get("is_music")]:
        lo, hi = _rel(e)
        covered = intersect_length([(lo, hi)], cand.get(e["source_key"], []))
        missing = (hi - lo) - covered
        if missing >= 1.0 and covered / max(1e-6, hi - lo) < 0.5:
            out.append({"source_key": e["source_key"], "source_in": round(lo, 2),
                        "source_out": round(hi, 2), "plays_at_sec": e["timeline_start"],
                        "track": e["track"], "missing_sec": round(missing, 2)})
    out.sort(key=lambda g: -g["missing_sec"])
    seen, uniq = set(), []
    for g in out:
        k = (g["source_key"], g["source_in"])
        if k not in seen:
            seen.add(k)
            uniq.append(g)
    return uniq[:limit]


def evaluate(reference: dict, candidate: dict) -> dict:
    """Score ``candidate`` against the editor's own ``reference`` cut."""
    ref_v = used_ranges(reference, track="video", relative=True)
    cand_v = used_ranges(candidate, track="video", relative=True)
    moments = _overlap(ref_v, cand_v)
    lines = _overlap(_spoken(reference), _spoken(candidate))

    pairs = _match(_video_events(reference), _video_events(candidate))
    order = _spearman([a["timeline_start"] for a, _, _ in pairs],
                      [b["timeline_start"] for _, b, _ in pairs])

    rs, cs = _shots(reference), _shots(candidate)
    r_avg = statistics.fmean(s["duration_sec"] for s in rs) if rs else None
    c_avg = statistics.fmean(s["duration_sec"] for s in cs) if cs else None
    curve = _pearson(_deciles(rs), _deciles(cs))
    pacing = {
        "reference_duration_sec": reference.get("duration_sec"),
        "candidate_duration_sec": candidate.get("duration_sec"),
        "reference_shots": len(rs), "candidate_shots": len(cs),
        "reference_avg_shot_sec": None if r_avg is None else round(r_avg, 2),
        "candidate_avg_shot_sec": None if c_avg is None else round(c_avg, 2),
        "pacing_curve_correlation": curve,
    }

    parts: dict[str, tuple[float, float]] = {}
    if moments["f1"] is not None:
        parts["moments"] = (W_MOMENTS, moments["f1"])
    if lines["f1"] is not None:
        parts["lines"] = (W_LINES, lines["f1"])
    if order is not None:
        parts["order"] = (W_ORDER, (order + 1) / 2)
    if r_avg and c_avg:
        ratio_term = max(0.0, 1 - abs(math.log(c_avg / r_avg)))
        curve_term = max(0.0, curve) if curve is not None else ratio_term
        parts["pacing"] = (W_PACING, (ratio_term + curve_term) / 2)
    weight = sum(w for w, _ in parts.values())
    score = round(100 * sum(w * v for w, v in parts.values()) / weight, 1) if weight else None

    shared_sources = ref_v.keys() & cand_v.keys()
    notes = []
    if ref_v and cand_v and not shared_sources:
        notes.append("The two cuts share no source files by name. Check that both "
                     "reference the same footage (proxies and renamed files are "
                     "matched by base name without extension or a _proxy suffix).")

    return {
        "score": score,
        "components": {k: round(100 * v, 1) for k, (_, v) in parts.items()},
        "weights": {k: w for k, (w, _) in parts.items()},
        "moments": moments,
        "lines": lines,
        "order_correlation": order,
        "matched_shots": len(pairs),
        "pacing": pacing,
        "missed": _gaps(ref_v, cand_v, reference),
        "extra": [{"source_key": g["source_key"], "source_in": g["source_in"],
                   "source_out": g["source_out"], "plays_at_sec": g["plays_at_sec"],
                   "extra_sec": g["missing_sec"]}
                  for g in _gaps(cand_v, ref_v, candidate)],
        "sources": {"reference": len(ref_v), "candidate": len(cand_v),
                    "shared": len(shared_sources)},
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------

def _position_third(t: float, dur: float) -> str:
    p = t / dur if dur else 0.0
    return "opening" if p < 1 / 3 else "middle" if p < 2 / 3 else "ending"


def correction(before: dict, after: dict, *, note: str = "") -> dict:
    """What the editor changed going from ``before`` (e.g. Eddie's cut) to
    ``after`` (their fix)."""
    b_ev, a_ev = _video_events(before), _video_events(after)
    pairs = _match(b_ev, a_ev)
    matched_b = {id(b) for b, _, _ in pairs}
    reverse = _match(a_ev, b_ev)
    matched_a = {id(a) for a, _, _ in reverse}

    dur_b = before.get("duration_sec") or 0.0
    removed = [{"source_key": e["source_key"], "duration": e["duration"],
                "at_sec": e["timeline_start"], "layer": e["layer"],
                "part": _position_third(e["timeline_start"], dur_b)}
               for e in b_ev if id(e) not in matched_b]
    dur_a = after.get("duration_sec") or 0.0
    added = [{"source_key": e["source_key"], "duration": e["duration"],
              "at_sec": e["timeline_start"], "layer": e["layer"],
              "part": _position_third(e["timeline_start"], dur_a)}
             for e in a_ev if id(e) not in matched_a]

    trims = []
    for b, a, _ in pairs:
        blo, bhi = _rel(b)
        alo, ahi = _rel(a)
        trims.append({
            "source_key": b["source_key"],
            "head_sec": round(alo - blo, 2),        # + started later
            "tail_sec": round(bhi - ahi, 2),        # + ended earlier
            "length_change_sec": round(a["duration"] - b["duration"], 2),
            "speed_before": b["speed"], "speed_after": a["speed"],
            "part": _position_third(b["timeline_start"], dur_b),
        })

    order = _spearman([b["timeline_start"] for b, _, _ in pairs],
                      [a["timeline_start"] for _, a, _ in pairs])
    lines_before, lines_after = _spoken(before), _spoken(after)
    lines = _overlap(lines_before, lines_after)

    def diss(p):
        return [t["duration"] for t in p["transitions"] if t["kind"] == "dissolve"]

    sb, sa = _shots(before), _shots(after)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "before": before.get("name"),
        "after": after.get("name"),
        "note": note,
        "summary": {
            "duration_before_sec": dur_b,
            "duration_after_sec": dur_a,
            "duration_change_pct": round(100 * (dur_a - dur_b) / dur_b, 1) if dur_b else None,
            "shots_before": len(sb), "shots_after": len(sa),
            "avg_shot_before_sec": round(dur_b / len(sb), 2) if sb else None,
            "avg_shot_after_sec": round(dur_a / len(sa), 2) if sa else None,
            "removed_shots": len(removed), "added_shots": len(added),
            "removed_pct": round(100 * len(removed) / len(b_ev), 1) if b_ev else None,
            "order_correlation": order,
            "lines_kept_pct": None if lines["recall"] is None else round(100 * lines["recall"], 1),
            "lines_added_sec": round(lines["candidate_sec"] - lines["shared_sec"], 1),
            "dissolves_before": len(diss(before)), "dissolves_after": len(diss(after)),
        },
        "removed": removed,
        "added": added,
        "trims": trims,
    }


def correction_rules(records: list[dict]) -> dict:
    """Tendencies across every correction so far, as numbers and rules."""
    if not records:
        return {"corrections": 0, "rules": []}
    s = [r["summary"] for r in records]

    def med(key):
        vals = [x[key] for x in s if x.get(key) is not None]
        return round(statistics.median(vals), 2) if vals else None

    trims = [t for r in records for t in r.get("trims", [])]
    removed = [x for r in records for x in r.get("removed", [])]
    added = [x for r in records for x in r.get("added", [])]
    parts = {p: sum(1 for x in removed if x["part"] == p) for p in ("opening", "middle", "ending")}
    head = statistics.median([t["head_sec"] for t in trims]) if trims else None
    tail = statistics.median([t["tail_sec"] for t in trims]) if trims else None

    stats = {
        "corrections": len(records),
        "duration_change_pct": med("duration_change_pct"),
        "removed_pct": med("removed_pct"),
        "removed_by_part": parts,
        "added_shots_per_cut": round(len(added) / len(records), 1),
        "added_broll_share_pct": round(100 * sum(1 for x in added if x["layer"] >= 1) / len(added), 1) if added else None,
        "head_trim_sec": None if head is None else round(head, 2),
        "tail_trim_sec": None if tail is None else round(tail, 2),
        "lines_kept_pct": med("lines_kept_pct"),
        "order_correlation": med("order_correlation"),
        "dissolve_change": med("dissolves_after") - med("dissolves_before")
        if med("dissolves_after") is not None and med("dissolves_before") is not None else None,
    }

    rules = []
    n = stats["corrections"]
    if stats["duration_change_pct"] is not None and abs(stats["duration_change_pct"]) >= 5:
        verb = "shortened" if stats["duration_change_pct"] < 0 else "lengthened"
        rules.append(f"In {n} past correction(s) you {verb} the cut by about "
                     f"{abs(stats['duration_change_pct']):.0f}%; aim for that length from the start.")
    if stats["removed_pct"]:
        where = max(parts, key=parts.get) if any(parts.values()) else None
        r = f"You removed about {stats['removed_pct']:.0f}% of the shots"
        if where:
            r += f", most often in the {where}"
        rules.append(r + "; be more selective there.")
    if head is not None and abs(head) >= 0.2:
        rules.append(f"You start shots {abs(head):.1f}s {'later' if head > 0 else 'earlier'} "
                     "than the first cut did.")
    if tail is not None and abs(tail) >= 0.2:
        rules.append(f"You end shots {abs(tail):.1f}s {'earlier' if tail > 0 else 'later'} "
                     "than the first cut did.")
    if stats["lines_kept_pct"] is not None and stats["lines_kept_pct"] < 85:
        rules.append(f"Only about {stats['lines_kept_pct']:.0f}% of the chosen spoken lines "
                     "survived your edit; choose fewer, stronger lines.")
    if stats["added_broll_share_pct"] and stats["added_broll_share_pct"] >= 50:
        rules.append("Most of what you add is b-roll over the audio; cover more of the "
                     "spoken lines with cutaways.")
    if stats["order_correlation"] is not None and stats["order_correlation"] < 0.8:
        rules.append("You often reorder the shots; follow the reference film's section order.")
    if stats["dissolve_change"]:
        rules.append(f"You {'add' if stats['dissolve_change'] > 0 else 'remove'} about "
                     f"{abs(stats['dissolve_change']):g} dissolve(s) per cut.")
    return {**stats, "rules": rules}
