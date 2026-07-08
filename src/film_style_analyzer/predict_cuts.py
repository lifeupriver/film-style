"""Music-aware cut prediction.

Given a song (audio file) + a style-profile.json, generate a list of cut
timestamps that would assemble in the editor's style:

  1. Run librosa on the song to get tempo + beat times.
  2. Walk forward across the song's runtime. At each point we know "what
     decile of the song are we in," so look up the target clip duration
     from profile.pacing.decile_curve.
  3. The next ideal cut = current + target. Snap that to the nearest beat
     within tolerance (or to the closest beat if no in-tolerance beat).
  4. Repeat until we reach the end.

Optional FCPXML marker-track output that imports cleanly into Resolve /
Premiere / FCP.
"""

from __future__ import annotations

import bisect
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np


class PredictCutsError(RuntimeError):
    pass


def _load_song_beats(song_path: Path) -> tuple[float, float, list[float]]:
    """Return (duration_sec, tempo_bpm, beat_times). Raises if librosa missing."""
    try:
        import librosa  # type: ignore
    except ImportError as e:
        raise PredictCutsError(
            "librosa not installed. Install with: pip install 'film-style-analyzer[music]'"
        ) from e

    try:
        y, sr = librosa.load(str(song_path), sr=22050, mono=True)
    except Exception as e:
        raise PredictCutsError(f"could not load {song_path}: {e}") from e

    duration = len(y) / sr
    try:
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = [float(t) for t in librosa.frames_to_time(beat_frames, sr=sr)]
        # librosa.beat.beat_track returns tempo as a shape-(1,) ndarray under
        # numpy 2.x; float(ndarray) raises, so flatten to the first scalar.
        tempo_val = float(np.atleast_1d(tempo).reshape(-1)[0])
    except Exception as e:
        raise PredictCutsError(f"beat tracking failed: {e}") from e
    return duration, tempo_val, beat_times


def _target_duration_at(t: float, total: float, deciles: list[float]) -> float:
    """Look up the decile-curve target duration for time `t` within a song
    of total length `total`."""
    if not deciles or total <= 0:
        return 3.5  # safe fallback
    pos = max(0.0, min(0.999, t / total))
    idx = min(len(deciles) - 1, int(pos * len(deciles)))
    val = deciles[idx]
    return float(val) if val and val > 0 else 3.5


def _nearest_beat(beats: list[float], target: float) -> float | None:
    if not beats:
        return None
    pos = bisect.bisect_left(beats, target)
    if pos == 0:
        return beats[0]
    if pos >= len(beats):
        return beats[-1]
    before, after = beats[pos - 1], beats[pos]
    return after if (after - target) < (target - before) else before


def predict_cuts(
    song_path: Path,
    profile: dict,
    *,
    target_duration_sec: float | None = None,
    snap_tolerance_sec: float = 0.12,
    min_clip_sec: float | None = None,
    max_clip_sec: float | None = None,
) -> dict:
    """Generate predicted cut times for a song using a style profile."""
    duration, tempo, beats = _load_song_beats(song_path)
    runtime = min(duration, target_duration_sec) if target_duration_sec else duration

    pacing = (profile or {}).get("pacing", {}) or {}
    deciles = pacing.get("decile_curve") or pacing.get("avg_deciles") or []
    if min_clip_sec is None:
        min_clip_sec = pacing.get("min_clip_sec") or 1.0
    if max_clip_sec is None:
        max_clip_sec = pacing.get("max_clip_sec") or 8.0

    cuts: list[dict] = []
    t = 0.0
    iter_guard = 0
    while t < runtime and iter_guard < 5000:
        iter_guard += 1
        target_dur = _target_duration_at(t, runtime, deciles)
        # Clamp by the editor's observed range.
        target_dur = max(min_clip_sec, min(max_clip_sec, target_dur))
        ideal = t + target_dur

        snapped = _nearest_beat(beats, ideal)
        snap_used = False
        if snapped is not None and abs(snapped - ideal) <= snap_tolerance_sec and snapped > t + min_clip_sec * 0.5:
            cut_time = snapped
            snap_used = True
        else:
            cut_time = ideal

        if cut_time >= runtime:
            break
        cuts.append({
            "time_sec": round(cut_time, 3),
            "ideal_target_sec": round(ideal, 3),
            "target_clip_dur_sec": round(target_dur, 3),
            "snapped_to_beat": snap_used,
            "decile": min(9, int((cut_time / runtime) * 10)) if runtime else 0,
        })
        t = cut_time

    on_beat_count = sum(1 for c in cuts if c["snapped_to_beat"])
    return {
        "song": str(song_path),
        "song_duration_sec": round(duration, 2),
        "song_tempo_bpm": round(tempo, 1),
        "snap_tolerance_sec": snap_tolerance_sec,
        "predicted_cut_count": len(cuts),
        "on_beat_pct": round(100 * on_beat_count / len(cuts), 1) if cuts else 0.0,
        "cuts": cuts,
    }


# ---------- FCPXML marker-track export ------------------------------------


def to_fcpxml_markers(prediction: dict, *, song_basename: str | None = None,
                      fps: int = 24) -> str:
    """Emit a minimal FCPXML 1.10 with a single asset-clip + markers at each
    predicted cut. Imports cleanly into Resolve / Premiere / FCP."""
    duration_sec = prediction["song_duration_sec"]
    name = song_basename or Path(prediction["song"]).stem

    fcpxml = ET.Element("fcpxml", {"version": "1.10"})
    resources = ET.SubElement(fcpxml, "resources")
    fmt = ET.SubElement(resources, "format", {
        "id": "r1",
        "name": f"FFVideoFormat{fps}p",
        "frameDuration": f"100/{fps * 100}s",
    })
    asset = ET.SubElement(resources, "asset", {
        "id": "r2",
        "name": name,
        "duration": f"{int(duration_sec * 1000)}/1000s",
        "hasAudio": "1",
        "hasVideo": "0",
        "format": "r1",
    })
    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", {"name": "Predicted Cuts"})
    project = ET.SubElement(event, "project", {"name": f"{name} — predicted"})
    sequence = ET.SubElement(project, "sequence", {
        "duration": f"{int(duration_sec * 1000)}/1000s",
        "format": "r1",
        "tcStart": "0s",
    })
    spine = ET.SubElement(sequence, "spine")
    clip = ET.SubElement(spine, "asset-clip", {
        "name": name,
        "ref": "r2",
        "offset": "0s",
        "duration": f"{int(duration_sec * 1000)}/1000s",
        "audioRole": "music",
    })

    for i, c in enumerate(prediction["cuts"]):
        ET.SubElement(clip, "marker", {
            "start": f"{int(c['time_sec'] * 1000)}/1000s",
            "duration": "1/30s",
            "value": (
                f"Cut {i + 1:03d} · target {c['target_clip_dur_sec']:.2f}s"
                + (" · on beat" if c["snapped_to_beat"] else "")
            ),
        })

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE fcpxml>\n'
        + ET.tostring(fcpxml, encoding="unicode")
    )
