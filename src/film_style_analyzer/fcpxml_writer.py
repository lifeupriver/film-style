"""Write FCPXML 1.10 timelines with a video spine (+ optional music lane)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote
from urllib.request import pathname2url


def _sec_rational(sec: float, denom: int = 1000) -> str:
    return f"{int(round(max(0.0, sec) * denom))}/{denom}s"


def _file_url(path: str | Path) -> str:
    p = Path(path).expanduser().resolve()
    return "file://" + quote(pathname2url(str(p)), safe="/:")


def write_fcpxml(
    timeline: list[dict],
    *,
    title: str = "Rough cut",
    fps: int = 24,
    width: int = 1920,
    height: int = 1080,
    song_path: str | Path | None = None,
    event_name: str = "Film Style Assembly",
) -> str:
    """Emit FCPXML for a list of resolved timeline entries.

    Each entry needs: source_path, trim_in_sec, timeline_duration_sec,
    timeline_offset_sec, name (optional).
    """
    if not timeline and not song_path:
        raise ValueError("timeline is empty")

    total_dur = 0.0
    if timeline:
        last = timeline[-1]
        total_dur = float(last.get("timeline_offset_sec") or 0) + float(
            last.get("timeline_duration_sec") or 0
        )
    if song_path:
        # Caller may pass song duration via timeline metadata later; for now
        # derive from last video end or keep minimal.
        pass

    fcpxml = ET.Element("fcpxml", {"version": "1.10"})
    resources = ET.SubElement(fcpxml, "resources")
    fmt = ET.SubElement(
        resources,
        "format",
        {
            "id": "r1",
            "name": f"FFVideoFormat{height}p{fps}",
            "frameDuration": f"100/{fps * 100}s",
            "width": str(width),
            "height": str(height),
        },
    )
    _ = fmt  # referenced by assets

    asset_ids: dict[str, str] = {}
    next_id = 2

    def _ensure_asset(
        source_path: str, *, has_video: bool, has_audio: bool, duration_sec: float
    ) -> str:
        nonlocal next_id
        key = source_path
        if key in asset_ids:
            return asset_ids[key]
        aid = f"r{next_id}"
        next_id += 1
        ET.SubElement(
            resources,
            "asset",
            {
                "id": aid,
                "name": Path(source_path).name,
                "uid": source_path,
                "src": _file_url(source_path),
                "start": "0s",
                "duration": _sec_rational(duration_sec),
                "hasVideo": "1" if has_video else "0",
                "hasAudio": "1" if has_audio else "0",
                "format": "r1",
            },
        )
        asset_ids[key] = aid
        return aid

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", {"name": event_name})
    project = ET.SubElement(event, "project", {"name": title})
    sequence = ET.SubElement(
        project,
        "sequence",
        {
            "duration": _sec_rational(total_dur),
            "format": "r1",
            "tcStart": "0s",
            "tcFormat": "NDF",
        },
    )
    spine = ET.SubElement(sequence, "spine")

    for entry in timeline:
        src = entry["source_path"]
        trim_in = float(entry["trim_in_sec"])
        tl_dur = float(entry["timeline_duration_sec"])
        offset = float(entry.get("timeline_offset_sec") or 0)
        # Asset duration must cover trim_in + at least timeline use.
        src_duration = max(float(entry.get("source_duration_sec") or 0), trim_in + tl_dur, tl_dur)
        ref = _ensure_asset(src, has_video=True, has_audio=True, duration_sec=src_duration)
        ET.SubElement(
            spine,
            "asset-clip",
            {
                "name": entry.get("name") or Path(src).name,
                "ref": ref,
                "offset": _sec_rational(offset),
                "duration": _sec_rational(tl_dur),
                "start": _sec_rational(trim_in),
                "tcFormat": "NDF",
            },
        )

    if song_path:
        song = Path(song_path).expanduser().resolve()
        song_dur = float(total_dur) if total_dur > 0 else 1.0
        ref = _ensure_asset(str(song), has_video=False, has_audio=True, duration_sec=song_dur)
        ET.SubElement(
            spine,
            "asset-clip",
            {
                "name": song.name,
                "ref": ref,
                "offset": "0s",
                "duration": _sec_rational(song_dur),
                "start": "0s",
                "lane": "-1",
                "audioRole": "music",
            },
        )

    body = ET.tostring(fcpxml, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + body
