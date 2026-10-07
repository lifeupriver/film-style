"""Read an editing project's timeline into source-referenced edit decisions.

A finished film shows what the editor ended up with. The project timeline
(FCPXML from Final Cut or Resolve, OTIO from Premiere, Resolve or Eddie)
shows the decisions behind it: which camera file each shot came from, where
in that file it starts and stops, its speed and framing, the transitions and
their lengths, the music, and any markers the editor left.

``parse_project(path)`` returns::

    {
      "format": "fcpxml" | "otio",
      "name": str,
      "duration_sec": float,
      "events": [ {track, layer, timeline_start, timeline_end, duration,
                   source_key, source_name, source_path, source_in, source_out,
                   source_start, source_duration, speed, speed_ramp, scale,
                   audible, is_music, role, name} ],
      "transitions": [ {timeline_sec, duration, kind} ],
      "markers": [ {timeline_sec, name} ],
      "sources": { source_key: {name, path, start, duration, has_video, has_audio} },
    }

All times are seconds. ``source_in``/``source_out`` are in the source file's
own time, so they line up with a transcript of that file.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

from .fcpxml_parser import _parse_rational

_PROXY_SUFFIX = re.compile(r"[\s_\-.]*(proxy|prx|optimized|opt)$", re.IGNORECASE)
_CLIP_TAGS = ("asset-clip", "clip", "sync-clip", "ref-clip", "mc-clip")
# Below this level a clip's audio counts as muted.
_MUTED_DB = -40.0


def source_key(name_or_path: str) -> str:
    """Stable identity for a source file across tools.

    ``/Volumes/A/A001_C003_proxy.mov`` and ``A001_C003.MXF`` both become
    ``a001c003``, so a cut exported from Eddie (which may hold proxies or
    renamed files) can be matched against the editor's own project.
    """
    stem = Path(unquote(str(name_or_path)).split("?")[0]).name
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    stem = _PROXY_SUFFIX.sub("", stem)
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def _url_to_path(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme in ("file", ""):
        return unquote(parsed.path or url)
    return url


def _db(value: str | None) -> float | None:
    if not value:
        return None
    v = value.strip().lower().replace("db", "").strip()
    if v in ("-inf", "-infinity"):
        return float("-inf")
    try:
        return float(v)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# FCPXML
# ---------------------------------------------------------------------------

def _tag(e) -> str:
    return e.tag.split("}")[-1]


def _fcpxml_sources(root) -> dict[str, dict]:
    """Asset id -> source record."""
    out: dict[str, dict] = {}
    for e in root.iter():
        if _tag(e) != "asset":
            continue
        src = e.attrib.get("src", "")
        if not src:
            rep = next((c for c in e if _tag(c) == "media-rep"), None)
            if rep is not None:
                src = rep.attrib.get("src", "")
        path = _url_to_path(src)
        name = e.attrib.get("name") or Path(path).name
        out[e.attrib.get("id", "")] = {
            "name": name,
            "path": path,
            "key": source_key(path or name),
            "start": _parse_rational(e.attrib.get("start", "0s")),
            "duration": _parse_rational(e.attrib.get("duration", "0s")) or None,
            "has_video": e.attrib.get("hasVideo") == "1",
            "has_audio": e.attrib.get("hasAudio") == "1",
        }
    return out


def _speed_info(clip) -> tuple[float, bool]:
    """(average speed, whether the speed changes) from a timeMap."""
    tm = next((c for c in clip if _tag(c) == "timeMap"), None)
    if tm is None:
        return 1.0, False
    pts = [(_parse_rational(p.attrib.get("time", "0s")),
            _parse_rational(p.attrib.get("value", "0s")))
           for p in tm if _tag(p) == "timept"]
    if len(pts) < 2:
        return 1.0, False
    rates = []
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t1 > t0:
            rates.append((v1 - v0) / (t1 - t0))
    if not rates:
        return 1.0, False
    total_t = pts[-1][0] - pts[0][0]
    avg = (pts[-1][1] - pts[0][1]) / total_t if total_t > 0 else 1.0
    ramp = max(rates) - min(rates) > 0.05
    return round(avg, 3), ramp


def _scale(clip) -> float | None:
    for c in clip:
        if _tag(c) == "adjust-transform" and c.attrib.get("scale"):
            try:
                parts = [float(x) for x in c.attrib["scale"].split()]
                return round(max(parts), 3)
            except ValueError:
                return None
    return None


def _muted(clip) -> bool:
    for c in clip:
        if _tag(c) == "adjust-volume":
            db = _db(c.attrib.get("amount"))
            if db is not None and db <= _MUTED_DB:
                return True
    return clip.attrib.get("audioRole", "").lower() == "none"


def _media_ref(clip, sources: dict) -> tuple[dict | None, float]:
    """The source a clip shows and the source time at the clip's ``start``."""
    ref = clip.attrib.get("ref")
    if ref and ref in sources:
        if "start" in clip.attrib:
            return sources[ref], _parse_rational(clip.attrib["start"])
        return sources[ref], sources[ref]["start"]
    # <clip>/<sync-clip> wrap <video>/<audio>/<asset-clip> children.
    c_start = _parse_rational(clip.attrib.get("start", "0s"))
    for child in clip:
        cref = child.attrib.get("ref")
        if _tag(child) in ("video", "asset-clip", "audio") and cref in sources:
            inner_off = _parse_rational(child.attrib.get("offset", "0s"))
            inner_start = (_parse_rational(child.attrib["start"])
                           if "start" in child.attrib else sources[cref]["start"])
            return sources[cref], inner_start + (c_start - inner_off)
    return None, 0.0


def parse_fcpxml(path: Path) -> dict:
    root = ET.parse(path).getroot()
    sources = _fcpxml_sources(root)
    seq = next((e for e in root.iter() if _tag(e) == "sequence"), None)
    project = next((e for e in root.iter() if _tag(e) == "project"), None)
    spine = next((c for c in seq if _tag(c) == "spine"), None) if seq is not None else None

    events: list[dict] = []
    transitions: list[dict] = []
    markers: list[dict] = []

    def add_clip(clip, tl_start: float, layer: int) -> None:
        tag = _tag(clip)
        d = _parse_rational(clip.attrib.get("duration", ""))
        if d <= 0:
            return
        if tag in _CLIP_TAGS:
            src, src_in = _media_ref(clip, sources)
            speed, ramp = _speed_info(clip)
            role = (clip.attrib.get("audioRole") or clip.attrib.get("role") or "").lower()
            audio_only = bool(src) and src["has_audio"] and not src["has_video"]
            is_audio_track = layer < 0 or audio_only
            is_music = is_audio_track and ("music" in role or audio_only and "dialogue" not in role)
            base = {
                "layer": layer,
                "timeline_start": round(tl_start, 3),
                "timeline_end": round(tl_start + d, 3),
                "duration": round(d, 3),
                "source_key": src["key"] if src else source_key(clip.attrib.get("name", "")),
                "source_name": src["name"] if src else clip.attrib.get("name", ""),
                "source_path": src["path"] if src else "",
                "source_in": round(src_in, 3),
                "source_out": round(src_in + d * speed, 3),
                "source_start": src["start"] if src else 0.0,
                "source_duration": src["duration"] if src else None,
                "speed": speed,
                "speed_ramp": ramp,
                "scale": _scale(clip),
                "role": role,
                "name": clip.attrib.get("name", ""),
                "multicam": tag == "mc-clip",
            }
            if not is_audio_track:
                events.append({**base, "track": "video", "audible":
                               bool(src and src["has_audio"]) and not _muted(clip),
                               "is_music": False})
            else:
                events.append({**base, "track": "audio",
                               "audible": not _muted(clip), "is_music": is_music})
        # Markers sit in the clip's source time.
        c_start = _parse_rational(clip.attrib.get("start", "0s"))
        for m in clip:
            if _tag(m) in ("marker", "chapter-marker"):
                markers.append({
                    "timeline_sec": round(tl_start + _parse_rational(m.attrib.get("start", "0s")) - c_start, 3),
                    "name": m.attrib.get("value", ""),
                })
        # Connected clips and secondary storylines.
        for child in clip:
            lane = child.attrib.get("lane")
            if lane is None or not lane.lstrip("-").isdigit():
                continue
            c_tl = tl_start + _parse_rational(child.attrib.get("offset", "0s")) - c_start
            if _tag(child) == "spine":
                walk(child, c_tl, int(lane))
            else:
                add_clip(child, c_tl, int(lane))

    def walk(sp, origin: float, layer: int) -> None:
        t = origin
        sp_off = _parse_rational(sp.attrib.get("offset", "0s")) if layer else 0.0
        for item in sp:
            tag = _tag(item)
            d = _parse_rational(item.attrib.get("duration", ""))
            if layer == 0 and "offset" in item.attrib:
                start = _parse_rational(item.attrib["offset"])
            elif "offset" in item.attrib and layer:
                start = origin + _parse_rational(item.attrib["offset"]) - sp_off
            else:
                start = t
            if tag == "transition":
                name = (item.attrib.get("name") or "").lower()
                kind = "dissolve" if ("dissolve" in name or "cross" in name) else (
                    "fade" if "fade" in name or "dip" in name else name or "other")
                transitions.append({"timeline_sec": round(start + d / 2, 3),
                                    "duration": round(d, 3), "kind": kind})
                continue
            # Gaps emit no event of their own but carry connected clips
            # and markers, so they go through add_clip too.
            add_clip(item, start, layer)
            t = start + d

    if spine is not None:
        walk(spine, 0.0, 0)

    duration = _parse_rational(seq.attrib.get("duration", "")) if seq is not None else 0.0
    if not duration and events:
        duration = max(e["timeline_end"] for e in events if e["layer"] == 0) if any(
            e["layer"] == 0 for e in events) else max(e["timeline_end"] for e in events)

    return _finish("fcpxml", project.attrib.get("name", "") if project is not None else path.stem,
                   duration, events, transitions, markers, sources.values())


# ---------------------------------------------------------------------------
# OTIO
# ---------------------------------------------------------------------------

def _schema(o: dict) -> str:
    return (o.get("OTIO_SCHEMA") or "").split(".")[0]


def _sec(rt: dict | None) -> float:
    if not rt:
        return 0.0
    rate = rt.get("rate") or 0
    return float(rt.get("value") or 0) / rate if rate else 0.0


def _otio_speed(item: dict) -> tuple[float, bool]:
    for fx in item.get("effects") or []:
        if _schema(fx) == "LinearTimeWarp":
            return round(float(fx.get("time_scalar") or 1.0), 3), False
        if _schema(fx) == "FreezeFrame":
            return 0.0, False
    return 1.0, False


def parse_otio_doc(doc: dict, name: str = "") -> dict:
    if _schema(doc) != "Timeline":
        raise ValueError("not an OTIO timeline")
    events: list[dict] = []
    transitions: list[dict] = []
    markers: list[dict] = []
    sources: dict[str, dict] = {}

    video_layer = -1
    audio_layer = 0
    for track in (doc.get("tracks") or {}).get("children") or []:
        if _schema(track) != "Track":
            continue
        is_video = (track.get("kind") or "Video").lower() == "video"
        if is_video:
            video_layer += 1
            layer = video_layer
        else:
            audio_layer -= 1
            layer = audio_layer
        track_name = (track.get("name") or "").lower()
        t = 0.0
        for item in track.get("children") or []:
            sch = _schema(item)
            if sch == "Transition":
                d = _sec(item.get("in_offset")) + _sec(item.get("out_offset"))
                ttype = (item.get("transition_type") or item.get("name") or "").lower()
                kind = "dissolve" if ("dissolve" in ttype or "cross" in ttype) else (
                    "fade" if "fade" in ttype or "dip" in ttype else ttype or "other")
                if is_video:
                    transitions.append({"timeline_sec": round(t, 3),
                                        "duration": round(d, 3), "kind": kind})
                continue
            sr = item.get("source_range") or {}
            d = _sec(sr.get("duration"))
            for m in item.get("markers") or []:
                mr = m.get("marked_range") or {}
                markers.append({
                    "timeline_sec": round(t + _sec(mr.get("start_time")) - _sec(sr.get("start_time")), 3),
                    "name": m.get("name") or "",
                })
            if sch != "Clip" or d <= 0:
                t += max(d, 0.0)
                continue
            ref = item.get("media_reference") or {}
            url = ref.get("target_url") or ""
            path = _url_to_path(url)
            sname = Path(path).name if path else (ref.get("name") or item.get("name") or "")
            key = source_key(path or sname)
            ar = ref.get("available_range") or {}
            if key not in sources:
                sources[key] = {
                    "name": sname, "path": path, "key": key,
                    "start": _sec(ar.get("start_time")),
                    "duration": _sec(ar.get("duration")) or None,
                    "has_video": False, "has_audio": False,
                }
            sources[key]["has_video" if is_video else "has_audio"] = True
            speed, ramp = _otio_speed(item)
            src_in = _sec(sr.get("start_time"))
            role = track_name
            events.append({
                "track": "video" if is_video else "audio",
                "layer": layer,
                "timeline_start": round(t, 3),
                "timeline_end": round(t + d, 3),
                "duration": round(d, 3),
                "source_key": key,
                "source_name": sname,
                "source_path": path,
                "source_in": round(src_in, 3),
                "source_out": round(src_in + d * (speed or 0), 3),
                "source_start": sources[key]["start"],
                "source_duration": sources[key]["duration"],
                "speed": speed,
                "speed_ramp": ramp,
                "scale": None,
                "role": role,
                "name": item.get("name") or "",
                "multicam": False,
                "audible": True,
                "is_music": (not is_video) and ("music" in role or "song" in role),
            })
            t += d

    # A video clip's own audio is not represented separately in OTIO when the
    # export keeps it on a matching audio track; treat video as audible only
    # when no audio track carries the same source over the same range.
    audio_spans = {(e["source_key"], e["timeline_start"]) for e in events if e["track"] == "audio"}
    for e in events:
        if e["track"] == "video":
            e["audible"] = (e["source_key"], e["timeline_start"]) in audio_spans

    durations = [e["timeline_end"] for e in events]
    return _finish("otio", doc.get("name") or name, max(durations) if durations else 0.0,
                   events, transitions, markers, sources.values())


# ---------------------------------------------------------------------------


def _finish(fmt, name, duration, events, transitions, markers, sources) -> dict:
    events.sort(key=lambda e: (e["timeline_start"], e["layer"]))
    markers.sort(key=lambda m: m["timeline_sec"])
    return {
        "format": fmt,
        "name": name,
        "duration_sec": round(duration, 3),
        "events": events,
        "transitions": sorted(transitions, key=lambda t: t["timeline_sec"]),
        "markers": markers,
        "sources": {s["key"]: {k: v for k, v in s.items() if k != "key"} for s in sources},
    }


def parse_project(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".otio":
        return parse_otio_doc(json.loads(path.read_text()), path.stem)
    if suffix in (".fcpxml", ".xml"):
        return parse_fcpxml(path)
    if path.is_dir() and suffix == ".fcpxmld":
        return parse_fcpxml(path / "Info.fcpxml")
    raise ValueError(f"unsupported project format {suffix!r}; expected .fcpxml, .fcpxmld or .otio")


# ---------------------------------------------------------------------------
# Range helpers shared by evaluation, corrections and soundbites
# ---------------------------------------------------------------------------

def merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(r for r in ranges if r[1] > r[0]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def ranges_length(ranges: list[tuple[float, float]]) -> float:
    return sum(b - a for a, b in ranges)


def intersect_length(x: list[tuple[float, float]], y: list[tuple[float, float]]) -> float:
    i = j = 0
    total = 0.0
    while i < len(x) and j < len(y):
        a, b = max(x[i][0], y[j][0]), min(x[i][1], y[j][1])
        if b > a:
            total += b - a
        if x[i][1] < y[j][1]:
            i += 1
        else:
            j += 1
    return total


def used_ranges(project: dict, *, track: str | None = None,
                audible_only: bool = False, include_music: bool = False,
                relative: bool = False) -> dict[str, list[tuple[float, float]]]:
    """Merged source-time ranges per source key.

    With ``relative`` the ranges are measured from the start of the file
    rather than in the source's own timecode, so two tools that declare
    different start timecodes for the same file still line up.
    """
    by: dict[str, list[tuple[float, float]]] = {}
    for e in project["events"]:
        if track and e["track"] != track:
            continue
        if audible_only and not e["audible"]:
            continue
        if e["is_music"] and not include_music:
            continue
        if e.get("multicam") or not e["source_key"]:
            continue
        s0 = (e.get("source_start") or 0.0) if relative else 0.0
        lo, hi = sorted((e["source_in"] - s0, e["source_out"] - s0))
        by.setdefault(e["source_key"], []).append((lo, hi))
    return {k: merge_ranges(v) for k, v in by.items()}
