"""Minimal OpenTimelineIO (.otio JSON) parser.

Reads the plain JSON form OTIO writes, so the ``opentimelineio`` package is
not needed. Produces the same summary keys as ``fcpxml_parser.parse`` plus
``visible_clips`` (see ``timeline.flatten_visible``).

OTIO layout: a Timeline holds a Stack of Tracks. Tracks later in the Stack
sit on top. Within a Track, Clips and Gaps advance the playhead; a
Transition overlaps its neighbours and takes no track time of its own.
"""

from __future__ import annotations

from .timeline import flatten_visible


def _schema(obj: dict) -> str:
    return (obj.get("OTIO_SCHEMA") or "").split(".")[0]


def _seconds(rt: dict | None) -> float:
    if not rt:
        return 0.0
    rate = rt.get("rate") or 0
    return float(rt.get("value") or 0) / rate if rate else 0.0


def _item_duration(item: dict) -> float:
    sr = item.get("source_range")
    if sr:
        return _seconds(sr.get("duration"))
    if _schema(item) in ("Stack", "Track", "SerializableCollection"):
        children = item.get("children") or []
        if _schema(item) == "Stack":
            return max((_item_duration(c) for c in children), default=0.0)
        return sum(_item_duration(c) for c in children
                   if _schema(c) != "Transition")
    ref = item.get("media_reference") or {}
    ar = ref.get("available_range")
    return _seconds(ar.get("duration")) if ar else 0.0


def parse(doc: dict) -> dict:
    if _schema(doc) != "Timeline":
        raise ValueError("not an OTIO timeline (top-level OTIO_SCHEMA must be Timeline)")
    tracks = (doc.get("tracks") or {}).get("children") or []

    video_intervals: list[dict] = []
    primary_durations: list[float] = []
    transitions = 0
    dissolves = 0
    audio_durations: list[float] = []
    audio_names: set[str] = set()

    video_layer = -1
    for track in tracks:
        if _schema(track) != "Track":
            continue
        kind = (track.get("kind") or "Video").lower()
        is_video = kind == "video"
        if is_video:
            video_layer += 1
        t = 0.0
        for item in track.get("children") or []:
            schema = _schema(item)
            if schema == "Transition":
                if is_video:
                    transitions += 1
                    ttype = (item.get("transition_type") or item.get("name") or "").lower()
                    if "dissolve" in ttype or "cross" in ttype:
                        dissolves += 1
                continue
            d = _item_duration(item)
            if schema == "Gap" or d <= 0:
                t += max(d, 0.0)
                continue
            if is_video:
                video_intervals.append({
                    "start": t, "end": t + d, "layer": video_layer,
                    "name": item.get("name") or "",
                })
                if video_layer == 0:
                    primary_durations.append(d)
            else:
                audio_durations.append(d)
                if track.get("name"):
                    audio_names.add(str(track["name"]).lower())
            t += d

    visible = flatten_visible(video_intervals)
    durations = [c["duration_sec"] for c in visible] or primary_durations
    total = sum(durations)
    return {
        "format": "otio",
        "clip_count": len(durations),
        "clip_durations": durations,
        "total_duration_sec": total,
        "avg_clip_sec": (total / len(durations)) if durations else 0.0,
        "transitions_total": transitions,
        "dissolves": dissolves,
        "visible_clips": visible,
        "audio": {
            "audio_clip_count": len(audio_durations),
            "audio_total_duration_sec": round(sum(audio_durations), 2),
            "audio_roles": sorted(audio_names),
            "has_audio": bool(audio_durations),
        },
    }
