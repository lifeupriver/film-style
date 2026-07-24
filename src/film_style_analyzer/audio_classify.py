"""inaSpeechSegmenter audio classification → speech / music / noise / speech_over_music."""

from __future__ import annotations

from pathlib import Path


class ClassifyError(RuntimeError):
    pass


# inaSpeechSegmenter labels we keep. Other labels (e.g. "noEnergy") become "silence".
_KEEP = {"speech", "male", "female", "music", "noise"}


def _normalize_label(label: str) -> str:
    if label in ("male", "female", "speech"):
        return "speech"
    if label == "music":
        return "music"
    if label == "noise":
        return "noise"
    return "silence"


def _merge_adjacent(segments: list[dict]) -> list[dict]:
    """Merge consecutive same-type segments."""
    if not segments:
        return []
    out = [dict(segments[0])]
    for seg in segments[1:]:
        if seg["type"] == out[-1]["type"] and abs(seg["start_sec"] - out[-1]["end_sec"]) < 0.05:
            out[-1]["end_sec"] = seg["end_sec"]
            out[-1]["duration_sec"] = round(out[-1]["end_sec"] - out[-1]["start_sec"], 2)
        else:
            out.append(dict(seg))
    return out


def _detect_overlaps(speech_segs: list[dict], music_segs: list[dict]) -> list[dict]:
    """Find time ranges where speech and music overlap; tag as speech_over_music.

    Returns a unified, non-overlapping segment list spanning the full timeline.
    """
    # Build event list.
    events: list[tuple[float, str, str]] = []
    for s in speech_segs:
        events.append((s["start_sec"], "start", "speech"))
        events.append((s["end_sec"], "end", "speech"))
    for s in music_segs:
        events.append((s["start_sec"], "start", "music"))
        events.append((s["end_sec"], "end", "music"))
    events.sort(key=lambda e: (e[0], 0 if e[1] == "end" else 1))

    active = {"speech": 0, "music": 0}
    out: list[dict] = []
    cur_t = 0.0
    cur_label: str | None = None
    for t, kind, what in events:
        if cur_label and t > cur_t:
            out.append(
                {
                    "start_sec": cur_t,
                    "end_sec": t,
                    "type": cur_label,
                    "duration_sec": round(t - cur_t, 2),
                }
            )
        if kind == "start":
            active[what] += 1
        else:
            active[what] -= 1
        if active["speech"] > 0 and active["music"] > 0:
            cur_label = "speech_over_music"
        elif active["speech"] > 0:
            cur_label = "speech"
        elif active["music"] > 0:
            cur_label = "music"
        else:
            cur_label = None
        cur_t = t
    return _merge_adjacent(out)


def classify(wav_path: Path, total_duration_sec: float) -> dict:
    try:
        from inaSpeechSegmenter import Segmenter
    except ImportError as e:
        raise ClassifyError(
            "inaSpeechSegmenter not installed. Install with: pip install 'film-style-analyzer[audio]'"
        ) from e

    try:
        seg = Segmenter()
        raw = seg(str(wav_path))
    except Exception as e:
        raise ClassifyError(f"inaSpeechSegmenter failed: {e}") from e

    speech_segs: list[dict] = []
    music_segs: list[dict] = []
    noise_segs: list[dict] = []
    for label, start, end in raw:
        kind = _normalize_label(label)
        record = {
            "start_sec": float(start),
            "end_sec": float(end),
            "type": kind,
            "duration_sec": round(float(end) - float(start), 2),
        }
        if kind == "speech":
            speech_segs.append(record)
        elif kind == "music":
            music_segs.append(record)
        elif kind == "noise":
            noise_segs.append(record)

    unified = _detect_overlaps(speech_segs, music_segs)
    # Layer noise into gaps not already covered by speech/music.
    if noise_segs:
        # Project noise into uncovered gaps by collecting non-(speech|music) gaps.
        covered = sorted(unified, key=lambda x: x["start_sec"])
        noise_layered: list[dict] = []
        for n in noise_segs:
            ns, ne = n["start_sec"], n["end_sec"]
            for c in covered:
                if c["end_sec"] <= ns or c["start_sec"] >= ne:
                    continue
                if c["start_sec"] > ns:
                    noise_layered.append(
                        {
                            "start_sec": ns,
                            "end_sec": c["start_sec"],
                            "type": "noise",
                            "duration_sec": round(c["start_sec"] - ns, 2),
                        }
                    )
                ns = max(ns, c["end_sec"])
            if ns < ne:
                noise_layered.append(
                    {
                        "start_sec": ns,
                        "end_sec": ne,
                        "type": "noise",
                        "duration_sec": round(ne - ns, 2),
                    }
                )
        unified = sorted(unified + noise_layered, key=lambda x: x["start_sec"])
        unified = _merge_adjacent(unified)

    music_only = sum(s["duration_sec"] for s in unified if s["type"] == "music")
    speech_over_music = sum(s["duration_sec"] for s in unified if s["type"] == "speech_over_music")
    speech_only = sum(s["duration_sec"] for s in unified if s["type"] == "speech")
    ambient = sum(s["duration_sec"] for s in unified if s["type"] == "noise")

    speech_segments = [s for s in unified if s["type"] in ("speech", "speech_over_music")]
    first_speech_at = speech_segments[0]["start_sec"] if speech_segments else None

    total = total_duration_sec or 1.0
    pct = lambda x: round(100 * x / total, 1)

    return {
        "segments": unified,
        "summary": {
            "music_only_sec": round(music_only, 1),
            "music_only_pct": pct(music_only),
            "speech_over_music_sec": round(speech_over_music, 1),
            "speech_over_music_pct": pct(speech_over_music),
            "speech_only_sec": round(speech_only, 1),
            "speech_only_pct": pct(speech_only),
            "ambient_sec": round(ambient, 1),
            "ambient_pct": pct(ambient),
            "first_speech_at_sec": first_speech_at,
            "first_speech_at_pct": pct(first_speech_at) if first_speech_at is not None else None,
            "total_speech_duration_sec": round(speech_only + speech_over_music, 1),
            "speech_segment_count": len(speech_segments),
            "avg_speech_segment_sec": (
                round(sum(s["duration_sec"] for s in speech_segments) / len(speech_segments), 2)
                if speech_segments
                else 0.0
            ),
            "longest_speech_segment_sec": (
                round(max((s["duration_sec"] for s in speech_segments), default=0.0), 2)
            ),
        },
    }
