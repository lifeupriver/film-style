"""Learn the editor's decisions from their project timelines.

Input: projects parsed by ``edit_decisions.parse_project``. Output: an edit
profile of medians across projects, covering what the finished films cannot
show: how much of each chosen clip is kept and where in it the shot starts,
how much b-roll covers the audio, slow motion and punch-ins, measured
transition lengths, and how music is laid in.
"""

from __future__ import annotations

import statistics
from typing import Any

from .edit_decisions import merge_ranges, ranges_length, used_ranges
from .timeline import flatten_visible

SLOW_MOTION_BELOW = 0.95
PUNCH_IN_AT_LEAST = 1.05


def _median(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(statistics.median(vals), 3) if vals else None


def _pct(n: float, d: float) -> float | None:
    return round(100 * n / d, 1) if d else None


def project_metrics(project: dict) -> dict[str, Any]:
    """Per-project measurements of the edit decisions."""
    events = project["events"]
    dur = project.get("duration_sec") or 0.0
    video = [e for e in events if e["track"] == "video" and not e.get("multicam")]

    visible = flatten_visible([
        {"start": e["timeline_start"], "end": e["timeline_end"],
         "layer": e["layer"], "name": e["source_key"]} for e in video])

    # Selection: what share of each chosen clip made it in.
    ranges = used_ranges(project, track="video")
    keep_pcts, pieces = [], []
    footage = 0.0
    for key, rs in ranges.items():
        src = project["sources"].get(key) or {}
        total = src.get("duration")
        pieces.append(len(rs))
        if total:
            footage += total
            keep_pcts.append(100 * min(1.0, ranges_length(rs) / total))

    head, tail = [], []
    for e in video:
        sd = e.get("source_duration")
        if sd:
            s0 = e.get("source_start") or 0.0
            lo, hi = sorted((e["source_in"], e["source_out"]))
            head.append(max(0.0, lo - s0))
            tail.append(max(0.0, s0 + sd - hi))

    broll = merge_ranges([(e["timeline_start"], e["timeline_end"])
                          for e in video if e["layer"] >= 1])
    slow = [e for e in video if 0 < e["speed"] < SLOW_MOTION_BELOW]
    ramps = [e for e in video if e.get("speed_ramp")]
    punch = [e for e in video if (e.get("scale") or 1.0) >= PUNCH_IN_AT_LEAST]

    dissolves = [t["duration"] for t in project["transitions"] if t["kind"] == "dissolve"]
    fades = [t for t in project["transitions"] if t["kind"] == "fade"]

    music = [e for e in events if e.get("is_music")]
    music_cov = merge_ranges([(e["timeline_start"], e["timeline_end"]) for e in music])
    speech = merge_ranges([(e["timeline_start"], e["timeline_end"]) for e in events
                           if e["audible"] and not e.get("is_music")
                           and (e["track"] == "audio" or e["layer"] == 0)])

    return {
        "name": project.get("name"),
        "duration_sec": round(dur, 2),
        "shot_count": len(visible),
        "avg_shot_sec": round(dur / len(visible), 2) if visible and dur else None,
        "sources_used": len(ranges),
        "footage_in_used_clips_sec": round(footage, 1) if footage else None,
        "keep_pct_of_clip": _median(keep_pcts),
        "pieces_per_clip": _median(pieces),
        "head_skip_sec": _median(head),
        "tail_skip_sec": _median(tail),
        "broll_coverage_pct": _pct(ranges_length(broll), dur),
        "slow_motion_pct": _pct(len(slow), len(video)),
        "slow_motion_speed": _median([e["speed"] for e in slow]),
        "speed_ramps": len(ramps),
        "punch_in_pct": _pct(len(punch), len(video)),
        "punch_in_scale": _median([e["scale"] for e in punch]),
        "dissolves": len(dissolves),
        "dissolve_sec": _median(dissolves),
        "fade_sec": _median([t["duration"] for t in fades]),
        "opens_with_fade": any(t["timeline_sec"] <= 2.0 for t in fades),
        "ends_with_fade": any(dur and t["timeline_sec"] >= dur - 2.0 for t in fades),
        "music_tracks": len({e["source_key"] for e in music}),
        "music_coverage_pct": _pct(ranges_length(music_cov), dur),
        "music_starts_at_sec": round(min(e["timeline_start"] for e in music), 2) if music else None,
        "speech_coverage_pct": _pct(ranges_length(speech), dur),
        "markers": [m["name"] for m in project.get("markers") or [] if m.get("name")],
    }


_MEDIAN_KEYS = (
    "duration_sec", "shot_count", "avg_shot_sec", "sources_used",
    "keep_pct_of_clip", "pieces_per_clip", "head_skip_sec", "tail_skip_sec",
    "broll_coverage_pct", "slow_motion_pct", "slow_motion_speed", "speed_ramps",
    "punch_in_pct", "punch_in_scale", "dissolves", "dissolve_sec", "fade_sec",
    "music_tracks", "music_coverage_pct", "music_starts_at_sec",
    "speech_coverage_pct",
)


def build_edit_profile(projects: list[dict]) -> dict:
    """Medians across projects, plus plain-language rules."""
    per = [project_metrics(p) for p in projects]
    agg: dict[str, Any] = {k: _median([m[k] for m in per]) for k in _MEDIAN_KEYS}
    agg["opens_with_fade_ratio"] = round(sum(m["opens_with_fade"] for m in per) / len(per), 2) if per else None
    agg["ends_with_fade_ratio"] = round(sum(m["ends_with_fade"] for m in per) / len(per), 2) if per else None
    return {
        "schema_version": "1.0",
        "project_count": len(per),
        "decisions": agg,
        "rules": edit_rules(agg),
        "projects": per,
    }


def edit_rules(a: dict) -> list[str]:
    rules: list[str] = []
    if a.get("keep_pct_of_clip") is not None:
        r = f"From each camera clip you use, keep about {a['keep_pct_of_clip']:.0f}% of it"
        if a.get("pieces_per_clip"):
            r += f" ({a['pieces_per_clip']:g} piece{'s' if a['pieces_per_clip'] != 1 else ''} per clip)"
        rules.append(r + ".")
    if a.get("head_skip_sec") is not None:
        rules.append(f"Start shots about {a['head_skip_sec']:.1f}s into the clip and end "
                     f"about {a['tail_skip_sec'] or 0:.1f}s before it ends.")
    if a.get("broll_coverage_pct"):
        rules.append(f"B-roll covers about {a['broll_coverage_pct']:.0f}% of the film "
                     "over the main storyline.")
    if a.get("slow_motion_pct"):
        r = f"About {a['slow_motion_pct']:.0f}% of shots play in slow motion"
        if a.get("slow_motion_speed"):
            r += f" (typically {a['slow_motion_speed'] * 100:.0f}% speed)"
        rules.append(r + ".")
    if a.get("speed_ramps"):
        rules.append(f"Use about {a['speed_ramps']:g} speed ramp(s) per film.")
    if a.get("punch_in_pct"):
        rules.append(f"Punch in on about {a['punch_in_pct']:.0f}% of shots "
                     f"(around {a['punch_in_scale'] or 1.1:.2f}x).")
    if a.get("dissolve_sec"):
        rules.append(f"Dissolves run about {a['dissolve_sec']:.2f}s.")
    if (a.get("opens_with_fade_ratio") or 0) > 0.5:
        rules.append("Fade in from black at the start.")
    if (a.get("ends_with_fade_ratio") or 0) > 0.5:
        rules.append(f"Fade out to black at the end"
                     + (f" over about {a['fade_sec']:.1f}s." if a.get("fade_sec") else "."))
    if a.get("music_tracks"):
        r = f"Use {a['music_tracks']:g} song(s)"
        if a.get("music_coverage_pct"):
            r += f" under about {a['music_coverage_pct']:.0f}% of the film"
        if a.get("music_starts_at_sec") is not None:
            r += f", music in at {a['music_starts_at_sec']:.1f}s"
        rules.append(r + ".")
    if a.get("speech_coverage_pct"):
        rules.append(f"Spoken audio (vows, toasts, letters) plays under about "
                     f"{a['speech_coverage_pct']:.0f}% of the film.")
    return rules
