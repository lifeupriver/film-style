"""Music characterization on the music-only segments of the audio track.

Uses librosa (optional pip extra `[music]`) to extract:
  - tempo (BPM)
  - beat times (seconds)
  - downsampled RMS energy curve (per-second)
  - spectral centroid (brightness proxy)
  - estimated key (chromagram argmax over a circle-of-fifths-ish projection)
"""

from __future__ import annotations

from pathlib import Path

KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


class MusicAnalyzeError(RuntimeError):
    pass


def _seconds_per_beat(tempo_bpm: float) -> float:
    return 60.0 / tempo_bpm if tempo_bpm > 0 else 0.0


def analyze_music(wav_path: Path, segments: list[dict]) -> dict:
    """Run librosa over the music portion of a WAV. `segments` comes from
    audio_classify (each item has type / start_sec / end_sec / duration_sec)."""
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as e:
        raise MusicAnalyzeError(
            "librosa not installed. Install with: pip install 'film-style-analyzer[music]'"
        ) from e

    music_segs = [
        s for s in segments
        if s.get("type") in ("music", "speech_over_music")
    ]
    if not music_segs:
        return {"has_music": False, "tempo_bpm": None, "beats": [],
                "energy_curve": [], "key": None}

    try:
        y, sr = librosa.load(str(wav_path), sr=22050, mono=True)
    except Exception as e:
        raise MusicAnalyzeError(f"librosa load failed: {e}") from e

    # Concatenate music regions only — speech-only stretches confuse the beat
    # tracker. Build a mask in samples space.
    mask = np.zeros(len(y), dtype=bool)
    for s in music_segs:
        a = int(max(0, s["start_sec"]) * sr)
        b = int(min(len(y) / sr, s["end_sec"]) * sr)
        if b > a:
            mask[a:b] = True
    music_only = y[mask]
    if len(music_only) < sr * 5:
        # Less than 5 seconds — too short for reliable analysis.
        return {"has_music": True, "tempo_bpm": None, "beats": [],
                "energy_curve": [], "key": None,
                "note": "music regions too short for reliable analysis"}

    try:
        tempo, beat_frames = librosa.beat.beat_track(y=music_only, sr=sr)
        tempo_val = float(tempo) if np.isscalar(tempo) else float(tempo[0])
        beat_times_in_music = librosa.frames_to_time(beat_frames, sr=sr)
    except Exception as e:
        raise MusicAnalyzeError(f"beat tracking failed: {e}") from e

    # Map beat times in concatenated-music-space back to original timeline.
    # Build a cumulative offset table per music segment.
    beats_global = _project_beats_to_timeline(beat_times_in_music, music_segs)

    # Energy curve: sample RMS once per second across the FULL film timeline
    # (zero where there's no music).
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)
    duration_sec = len(y) / sr
    seconds = np.arange(0, int(np.ceil(duration_sec)) + 1)
    energy_curve = []
    for t in seconds:
        # Mean RMS in [t, t+1).
        idx = (rms_times >= t) & (rms_times < t + 1)
        v = float(rms[idx].mean()) if idx.any() else 0.0
        energy_curve.append(round(v, 4))

    # Spectral centroid (brightness) on music-only.
    try:
        cent = librosa.feature.spectral_centroid(y=music_only, sr=sr)[0]
        brightness = round(float(cent.mean()), 1)
    except Exception:
        brightness = None

    # Estimated key: chroma summed, argmax.
    key = None
    try:
        chroma = librosa.feature.chroma_cqt(y=music_only, sr=sr)
        idx = int(chroma.sum(axis=1).argmax())
        key = KEYS[idx]
    except Exception:
        pass

    return {
        "has_music": True,
        "tempo_bpm": round(tempo_val, 1),
        "seconds_per_beat": round(_seconds_per_beat(tempo_val), 3),
        "beats": [round(float(t), 3) for t in beats_global],
        "energy_curve_per_sec": energy_curve,
        "spectral_centroid_hz": brightness,
        "key": key,
    }


def _project_beats_to_timeline(beats_local, music_segs) -> list[float]:
    """Beats are computed on concatenated music. Project them back to the
    original film timeline by walking each music segment's window."""
    if not len(beats_local):
        return []
    out = []
    cursor = 0.0  # time in the concatenated stream
    for seg in music_segs:
        seg_dur = seg["end_sec"] - seg["start_sec"]
        seg_start_concat = cursor
        seg_end_concat = cursor + seg_dur
        for b in beats_local:
            if seg_start_concat <= b < seg_end_concat:
                out.append(seg["start_sec"] + (b - seg_start_concat))
        cursor = seg_end_concat
    return out


def score_cut_beat_alignment(cut_times: list[float], beats: list[float],
                             tolerance_sec: float = 0.06) -> dict:
    """Given the cut times of a film and the beat times of its music, score
    how often cuts land on (or near) a beat. Returns:
      on_beat: cuts within `tolerance_sec` of a beat
      on_downbeat: cuts within tolerance of every-4th beat (loose proxy)
      off_beat: the remainder
      avg_distance_to_nearest_beat: in seconds
    """
    if not cut_times or not beats:
        return {
            "on_beat_pct": 0.0, "on_downbeat_pct": 0.0, "off_beat_pct": 0.0,
            "avg_distance_to_nearest_beat_sec": None,
            "tolerance_sec": tolerance_sec,
        }

    sorted_beats = sorted(beats)
    downbeats = set(sorted_beats[::4])

    on_beat = 0
    on_downbeat = 0
    distances: list[float] = []

    for t in cut_times:
        # Binary search for the nearest beat.
        nearest = _nearest(sorted_beats, t)
        d = abs(t - nearest)
        distances.append(d)
        if d <= tolerance_sec:
            on_beat += 1
            if nearest in downbeats:
                on_downbeat += 1

    n = len(cut_times)
    return {
        "tolerance_sec": tolerance_sec,
        "on_beat_pct": round(100 * on_beat / n, 1),
        "on_downbeat_pct": round(100 * on_downbeat / n, 1),
        "off_beat_pct": round(100 * (n - on_beat) / n, 1),
        "avg_distance_to_nearest_beat_sec": round(sum(distances) / n, 3),
        "cut_count": n,
        "beat_count": len(beats),
    }


def _nearest(sorted_arr: list[float], target: float) -> float:
    """Closest value in a sorted list to `target`."""
    import bisect
    pos = bisect.bisect_left(sorted_arr, target)
    if pos == 0:
        return sorted_arr[0]
    if pos == len(sorted_arr):
        return sorted_arr[-1]
    before = sorted_arr[pos - 1]
    after = sorted_arr[pos]
    return after if (after - target) < (target - before) else before
