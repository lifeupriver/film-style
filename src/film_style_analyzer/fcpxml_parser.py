"""Minimal FCPXML parser — extracts clip durations and transitions."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


def _parse_rational(value: str) -> float:
    """Parse FCPXML time strings like '12345/24000s' or '5s' into seconds."""
    if not value:
        return 0.0
    v = value.strip().rstrip("s")
    m = re.match(r"^(-?\d+)(?:/(\d+))?$", v)
    if not m:
        return 0.0
    num = int(m.group(1))
    den = int(m.group(2)) if m.group(2) else 1
    return num / den if den else 0.0


def parse(path: Path) -> dict:
    tree = ET.parse(path)
    root = tree.getroot()

    clip_durations: list[float] = []
    transitions = 0
    dissolves = 0
    audio_lane_durations: list[float] = []
    audio_role_set: set[str] = set()

    # Track which assets are audio-only via <asset> declarations.
    audio_asset_ids: set[str] = set()
    for asset in root.iter():
        tag = asset.tag.split("}")[-1]
        if tag == "asset":
            has_audio = asset.attrib.get("hasAudio") == "1"
            has_video = asset.attrib.get("hasVideo") == "1"
            aid = asset.attrib.get("id")
            if aid and has_audio and not has_video:
                audio_asset_ids.add(aid)

    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag in ("asset-clip", "ref-clip", "clip", "sync-clip"):
            d = _parse_rational(elem.attrib.get("duration", ""))
            ref = elem.attrib.get("ref", "")
            lane = elem.attrib.get("lane")
            role = (elem.attrib.get("audioRole") or elem.attrib.get("role") or "").lower()
            is_audio_lane = lane is not None and lane.lstrip("-").isdigit() and int(lane) < 0
            is_audio = (
                ref in audio_asset_ids or is_audio_lane or "music" in role or "dialogue" in role
            )
            if is_audio:
                if d > 0:
                    audio_lane_durations.append(d)
                if role:
                    audio_role_set.add(role)
            elif d > 0:
                clip_durations.append(d)
        elif tag == "transition":
            transitions += 1
            name = (elem.attrib.get("name") or "").lower()
            if "dissolve" in name or "cross" in name:
                dissolves += 1

    total_duration = sum(clip_durations)
    audio = {
        "audio_clip_count": len(audio_lane_durations),
        "audio_total_duration_sec": round(sum(audio_lane_durations), 2),
        "audio_roles": sorted(audio_role_set),
        "has_audio": bool(audio_lane_durations),
    }
    return {
        "clip_count": len(clip_durations),
        "clip_durations": clip_durations,
        "total_duration_sec": total_duration,
        "avg_clip_sec": (total_duration / len(clip_durations)) if clip_durations else 0.0,
        "transitions_total": transitions,
        "dissolves": dissolves,
        "audio": audio,
    }
