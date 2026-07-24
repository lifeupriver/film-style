"""Score raw footage clips against the learned shot profile.

Per clip we sample N frames, run every composition detector + emotion on
each, then aggregate (median for composition, peak for emotion). Hard
rejections drive score to 0; soft penalties stack but never below 0.

B-roll / detail shots without people skip the people-specific detectors
and are scored only on exposure, sharpness, stability, and horizon.
"""

from __future__ import annotations

import json
import logging
import statistics
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2

from . import __version__
from .composition import analyze_frame, motion_magnitude
from .emotion import (
    aggregate_clip_emotions,
    analyze_emotions,
)
from .media_probe import probe

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hard rejections — score = 0, never use.
# ---------------------------------------------------------------------------

HARD_REJECTIONS: dict[str, callable] = {
    "severely_underexposed": lambda c: c["mean_brightness"] < 0.12,
    "severely_overexposed": lambda c: c["mean_brightness"] > 0.88,
    "completely_out_of_focus": lambda c: c["laplacian_variance"] < 15,
    "head_cut_off": lambda c: c.get("head_cutoff") and c.get("faces_detected", 0) > 0,
}


# ---------------------------------------------------------------------------
# Soft penalties.
# ---------------------------------------------------------------------------


def collect_penalties(clip: dict, has_person: bool) -> list[dict]:
    p: list[dict] = []

    motion = clip.get("avg_motion_magnitude", 0)
    if motion > 8.0:
        p.append({"name": "excessive_shake", "value": -20})
    elif motion > 5.0:
        p.append({"name": "moderate_shake", "value": -10})

    lap = clip.get("laplacian_variance", 0)
    if 20 <= lap < 50:
        p.append({"name": "soft_focus", "value": -20})

    framing = clip.get("framing")
    if framing == "extreme-close-up":
        p.append({"name": "too_tight_crop", "value": -15})
    if framing in ("full", "wide"):
        p.append({"name": "too_wide", "value": -10})

    rating = clip.get("exposure_rating")
    if rating == "underexposed":
        p.append({"name": "underexposed", "value": -15})
    elif rating == "overexposed":
        p.append({"name": "overexposed", "value": -15})

    if clip.get("backlit"):
        p.append({"name": "backlit_subject", "value": -15})

    tilt = clip.get("horizon_tilt_degrees")
    if tilt is not None and clip.get("horizon_lines_detected") and abs(tilt) > 3:
        p.append({"name": "horizon_tilted", "value": -10})

    if has_person:
        head = clip.get("headroom_pct")
        if head is not None and (head < 5 or head > 25):
            p.append({"name": "poor_headroom", "value": -10})

        lr = clip.get("lead_room_ratio")
        if lr is not None and lr < 1.0:
            p.append({"name": "poor_lead_room", "value": -5})

        sep = clip.get("subject_separation_ratio")
        if sep is not None and sep < 1.2:
            p.append({"name": "low_subject_separation", "value": -5})

        # "Shooting from behind": pose detected but no face. We approximate
        # this with no faces and framing != no-person.
        if clip.get("faces_detected", 0) == 0 and framing != "no-person":
            p.append({"name": "shooting_from_behind", "value": -30})

    return p


# ---------------------------------------------------------------------------
# Composite scoring.
# ---------------------------------------------------------------------------


def compute_clip_score(
    clip: dict,
    shot_profile: dict,
    scene: str | None = None,
    emotion_scene_weights: dict[str, float] | None = None,
) -> tuple[int, str | None]:
    """Returns (score 0-100, hard_rejection_reason or None)."""
    for name, test in HARD_REJECTIONS.items():
        try:
            if test(clip):
                return 0, name
        except (KeyError, TypeError):
            continue

    score = 50
    has_person = clip.get("has_person", clip.get("faces_detected", 0) > 0)

    # ---- Composition (up to +50) ----
    if has_person:
        preferred = shot_profile.get("preferred_framing", "medium")
        framing = clip.get("framing")
        if framing == preferred:
            score += 20
        elif framing in ("medium", "medium-close", "close-up"):
            score += 10

        if clip.get("faces_detected", 0) > 0:
            score += 10
            avg_size = (
                shot_profile.get("face_presence", {}).get("primary_face_avg_size_pct", 0) or 0
            )
            if clip.get("face_size_pct", 0) >= avg_size * 0.5:
                score += 5

        score += int(clip.get("thirds_score", 0) * 10)

        head = clip.get("headroom_pct")
        if head is not None and 8 <= head <= 15:
            score += 5

        lr = clip.get("lead_room_ratio")
        if lr is not None and lr > 1.1:
            score += 5

        sep = clip.get("subject_separation_ratio")
        if sep is not None and sep > 2.0:
            score += 5

    rating = clip.get("exposure_rating")
    if rating == "good":
        score += 10
    elif rating == "acceptable":
        score += 5

    focus = clip.get("focus_rating")
    if focus == "sharp":
        score += 10
    elif focus == "acceptable":
        score += 5

    # ---- Emotion (up to +15, scene-weighted) ----
    if has_person:
        peak = clip.get("emotion", {}).get(
            "peak_emotion_score",
            clip.get("emotion", {}).get("peak_wedding_emotion", 0),
        )
        if peak > 60:
            boost = 15
        elif peak > 40:
            boost = 10
        elif peak > 20:
            boost = 5
        else:
            boost = 0
        if emotion_scene_weights is not None:
            weight = emotion_scene_weights.get(scene, 1.0) if scene else 1.0
        else:
            from .emotion import EMOTION_SCENE_WEIGHT

            weight = EMOTION_SCENE_WEIGHT.get(scene, 1.0) if scene else 1.0
        score += int(boost * weight)

    # ---- Soft penalties ----
    for pen in clip.get("penalties_applied", []):
        score += pen["value"]

    return max(0, min(100, score)), None


# ---------------------------------------------------------------------------
# Aggregating per-clip frame results.
# ---------------------------------------------------------------------------


def _median_or_none(values: list, default=None):
    if not values:
        return default
    if len(values) == 1:
        return values[0]
    return statistics.median(values)


def aggregate_clip_frames(frames: list[dict], motion_values: list[float]) -> dict:
    """Combine a clip's per-frame detector outputs into a single record.
    Median for composition (resilient to outliers), peak for emotion."""
    if not frames:
        return {}

    has_person_frames = [f for f in frames if f.get("has_person")]
    has_person = len(has_person_frames) > len(frames) / 2

    # Pick framing by majority vote (median doesn't apply to strings).
    framings = [f.get("framing") for f in frames if f.get("framing")]
    framing = max(set(framings), key=framings.count) if framings else "no-person"

    def med(key, default=None, restrict_to_person=False):
        src = has_person_frames if restrict_to_person else frames
        vals = [f.get(key) for f in src if f.get(key) is not None]
        return _median_or_none(vals, default)

    # face stats only meaningful when at least one frame had a face
    face_size = med("face_size_pct", 0.0, restrict_to_person=True) or 0.0
    headroom = med("headroom_pct", None, restrict_to_person=True)
    lead = med("lead_room_ratio", None, restrict_to_person=True)
    facing = (
        sum(1 for f in has_person_frames if f.get("facing_camera")) > len(has_person_frames) / 2
    )
    head_cutoff = (
        sum(1 for f in has_person_frames if f.get("head_cutoff")) > len(has_person_frames) / 2
    )

    avg_motion = round(statistics.fmean(motion_values), 3) if motion_values else 0.0

    out = {
        "has_person": has_person,
        "framing": framing,
        "faces_detected": int(round(med("faces_detected", 0))),
        "face_size_pct": round(face_size, 2),
        "facing_camera": facing,
        "head_cutoff": head_cutoff,
        "headroom_pct": round(headroom, 2) if headroom is not None else None,
        "lead_room_ratio": round(lead, 3) if lead is not None else None,
        "thirds_score": round(med("thirds_score", 0.0) or 0.0, 3),
        "horizon_tilt_degrees": med("horizon_tilt_degrees"),
        "horizon_lines_detected": any(f.get("horizon_lines_detected") for f in frames),
        "exposure_rating": _majority_str(frames, "exposure_rating", "acceptable"),
        "mean_brightness": round(med("mean_brightness", 0.5) or 0.5, 3),
        "backlit": sum(1 for f in frames if f.get("backlit")) > len(frames) / 2,
        "focus_rating": _majority_str(frames, "focus_rating", "acceptable"),
        "laplacian_variance": round(med("laplacian_variance", 0.0) or 0.0, 2),
        "subject_separation_ratio": round(med("subject_separation_ratio", 1.0) or 1.0, 2),
        "motion_blur_on_subject": sum(1 for f in frames if f.get("motion_blur_on_subject"))
        > len(frames) / 2,
        "stability": "stable"
        if avg_motion < 5.0
        else ("moderate_shake" if avg_motion < 8.0 else "shaky"),
        "avg_motion_magnitude": avg_motion,
    }
    return out


def _majority_str(frames: list[dict], key: str, default: str) -> str:
    vals = [f.get(key) for f in frames if f.get(key)]
    if not vals:
        return default
    return max(set(vals), key=vals.count)


# ---------------------------------------------------------------------------
# Frame extraction via ffmpeg.
# ---------------------------------------------------------------------------


def extract_sample_frames(clip_path: Path, samples: int, out_dir: Path) -> list[Path]:
    """Sample N evenly-spaced frames. Returns the list of JPEG paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = _probe_duration(clip_path)
    if duration <= 0:
        return []
    timestamps = (
        [round(duration * (i + 0.5) / samples, 3) for i in range(samples)] if samples > 0 else []
    )
    out_paths = []
    for i, ts in enumerate(timestamps):
        out = out_dir / f"sample_{i:02d}.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{ts:.3f}",
            "-i",
            str(clip_path),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
            if out.exists():
                out_paths.append(out)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning("frame extraction failed for %s @ %s: %s", clip_path, ts, e)
    return out_paths


def extract_frames_at_interval(
    clip_path: Path, interval_sec: float, out_dir: Path
) -> list[tuple[float, Path]]:
    """Sample frames every `interval_sec`. Returns [(time_sec, path), ...]."""
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = _probe_duration(clip_path)
    if duration <= 0:
        return []
    times = []
    t = 0.0
    while t < duration:
        times.append(round(t, 3))
        t += interval_sec
    out: list[tuple[float, Path]] = []
    for i, ts in enumerate(times):
        path = out_dir / f"interval_{i:04d}.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{ts:.3f}",
            "-i",
            str(clip_path),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(path),
        ]
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
            if path.exists():
                out.append((ts, path))
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return out


def _probe_duration(clip_path: Path) -> float:
    try:
        return probe(clip_path).duration_sec
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Trim point detection.
# ---------------------------------------------------------------------------


def detect_trim_points(clip_path: Path, interval_sec: float = 0.5, extract_fn=None) -> dict:
    """Find the first stable+sharp window from the start and the last
    stable+sharp window from the end. Returns trim_in/trim_out in seconds."""
    extract_fn = extract_fn or extract_frames_at_interval
    duration = _probe_duration(clip_path)
    if duration <= 0:
        return {
            "trim_in_sec": 0.0,
            "trim_out_sec": 0.0,
            "usable_duration_sec": 0.0,
            "reason": "could_not_probe",
        }

    with tempfile.TemporaryDirectory() as tmp:
        sampled = extract_fn(clip_path, interval_sec, Path(tmp))
        if not sampled:
            return {
                "trim_in_sec": 0.0,
                "trim_out_sec": duration,
                "usable_duration_sec": duration,
                "reason": "no_frames_extracted",
            }
        scores = _score_frame_sequence([p for _, p in sampled], [t for t, _ in sampled])

    return _trim_window_from_scores(scores, duration, interval_sec)


def _score_frame_sequence(frame_paths: list[Path], times: list[float]) -> list[dict]:
    """Score each sampled frame: sharpness + stability vs. previous frame."""
    out = []
    prev_img = None
    for ts, p in zip(times, frame_paths):
        img = cv2.imread(str(p))
        if img is None:
            out.append({"time_sec": ts, "sharp": False, "stable": False})
            prev_img = None
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if prev_img is None:
            motion = 0.0
        else:
            motion = motion_magnitude(prev_img, img)
        out.append(
            {
                "time_sec": ts,
                "sharp": sharpness > 40,
                "stable": motion < 5.0,
                "laplacian": round(sharpness, 2),
                "motion": round(motion, 3),
            }
        )
        prev_img = img
    return out


def _trim_window_from_scores(scores: list[dict], duration: float, interval_sec: float) -> dict:
    """Walk forward to first sharp+stable frame, backward to last sharp+stable
    frame. Pure function — exposed so it's directly testable."""
    if not scores:
        return {
            "trim_in_sec": 0.0,
            "trim_out_sec": duration,
            "usable_duration_sec": duration,
            "reason": "no_scores",
        }

    trim_in = 0.0
    in_trimmed = False
    for s in scores:
        if s["sharp"] and s["stable"]:
            trim_in = s["time_sec"]
            in_trimmed = trim_in > 0
            break
    else:
        # Nothing usable. Caller decides whether to reject.
        return {
            "trim_in_sec": 0.0,
            "trim_out_sec": 0.0,
            "usable_duration_sec": 0.0,
            "reason": "no_stable_frames",
        }

    trim_out = scores[-1]["time_sec"] + interval_sec
    out_trimmed = False
    for s in reversed(scores):
        if s["sharp"] and s["stable"]:
            new_out = s["time_sec"] + interval_sec
            out_trimmed = new_out < scores[-1]["time_sec"] + interval_sec
            trim_out = new_out
            break

    trim_out = min(trim_out, duration)
    if trim_out < trim_in:
        trim_out = trim_in
    reason = "shaky_start" if in_trimmed else ("shaky_end" if out_trimmed else "clean")
    return {
        "trim_in_sec": round(trim_in, 3),
        "trim_out_sec": round(trim_out, 3),
        "usable_duration_sec": round(max(0.0, trim_out - trim_in), 3),
        "reason": reason,
    }


def speech_trim_from_transcript(
    transcript: dict | None, clip_duration: float, pad_before: float = 0.5, pad_after: float = 1.0
) -> dict | None:
    """Compute trim_in / trim_out from WhisperX-style word timings.
    Returns None if there are no usable word timings."""
    if not transcript:
        return None
    words: list[dict] = []
    for seg in transcript.get("segments") or []:
        for w in seg.get("words") or []:
            if "start" in w and "end" in w:
                words.append(w)
    if not words:
        return None
    first = max(0.0, float(words[0]["start"]) - pad_before)
    last = min(clip_duration, float(words[-1]["end"]) + pad_after)
    if last < first:
        last = first
    return {
        "trim_in_sec": round(first, 3),
        "trim_out_sec": round(last, 3),
        "usable_duration_sec": round(max(0.0, last - first), 3),
        "reason": "speech_boundaries",
    }


# ---------------------------------------------------------------------------
# Clip path mapping (proxy → camera-original).
# ---------------------------------------------------------------------------


def map_to_original(
    proxy_path: Path,
    proxy_dir: str = "02-proxies",
    original_dir: str = "01-camera-originals",
    proxy_suffix: str = "_proxy",
    original_ext: str = ".MXF",
) -> str:
    """Best-effort mapping of a proxy path back to the camera original."""
    s = str(proxy_path)
    s = s.replace(f"/{proxy_dir}/", f"/{original_dir}/")
    name = Path(s).name
    stem = Path(name).stem
    if stem.endswith(proxy_suffix):
        stem = stem[: -len(proxy_suffix)]
    return str(Path(s).parent / (stem + original_ext))


# ---------------------------------------------------------------------------
# Top-level: score a directory or single clip.
# ---------------------------------------------------------------------------


def score_clip(
    clip_path: Path,
    shot_profile: dict,
    samples_per_clip: int = 5,
    detect_trims_flag: bool = False,
    scene: str | None = None,
    transcripts: dict | None = None,
    emotion_scene_weights: dict[str, float] | None = None,
    analyze_frame_fn=None,
    analyze_emotion_fn=None,
    extract_fn=None,
) -> dict:
    """Score one clip. The injectable functions make this directly testable."""
    analyze_frame_fn = analyze_frame_fn or analyze_frame
    analyze_emotion_fn = analyze_emotion_fn or analyze_emotions
    extract_fn = extract_fn or extract_sample_frames

    duration = _probe_duration(clip_path)

    with tempfile.TemporaryDirectory() as tmp:
        frame_paths = extract_fn(clip_path, samples_per_clip, Path(tmp))
        frame_results: list[dict] = []
        emotion_results: list[dict] = []
        prev_img = None
        motions: list[float] = []
        for fp in frame_paths:
            comp = analyze_frame_fn(fp)
            if "error" in comp:
                continue
            emo = analyze_emotion_fn(fp)
            comp["emotion_frame"] = emo
            frame_results.append(comp)
            emotion_results.append(emo)
            img = cv2.imread(str(fp))
            if img is not None:
                if prev_img is not None:
                    motions.append(motion_magnitude(prev_img, img))
                prev_img = img

    aggregated = aggregate_clip_frames(frame_results, motions)
    aggregated["emotion"] = aggregate_clip_emotions(emotion_results)
    aggregated["penalties_applied"] = collect_penalties(
        aggregated, has_person=aggregated.get("has_person", False)
    )
    score, rejection = compute_clip_score(
        aggregated,
        shot_profile,
        scene=scene,
        emotion_scene_weights=emotion_scene_weights,
    )

    record = {
        "file": str(clip_path),
        "original": map_to_original(clip_path),
        "duration_sec": round(duration, 2),
        "score": score,
        "rejection": rejection,
        "scene": scene,
        "analysis": {
            k: v for k, v in aggregated.items() if k not in ("emotion", "penalties_applied")
        },
        "emotion": aggregated["emotion"],
        "penalties_applied": aggregated["penalties_applied"],
    }

    if detect_trims_flag:
        transcript = (transcripts or {}).get(clip_path.name) if transcripts else None
        speech = speech_trim_from_transcript(transcript, duration) if transcript else None
        if speech:
            record["trim"] = speech
        else:
            record["trim"] = detect_trim_points(clip_path)

    return record


def score_directory(
    target: Path,
    shot_profile: dict,
    samples_per_clip: int = 5,
    detect_trims_flag: bool = False,
    scene_context: dict | None = None,
    transcripts: dict | None = None,
    emotion_scene_weights: dict[str, float] | None = None,
    progress_cb=None,
    score_clip_fn=None,
) -> dict:
    """Top-level scorer. `target` may be a single clip or a directory."""
    score_clip_fn = score_clip_fn or score_clip

    extensions = {".mp4", ".mov", ".m4v", ".mkv", ".mxf"}
    if target.is_file():
        clips = [target] if target.suffix.lower() in extensions else []
    else:
        clips = sorted(
            p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in extensions
        )

    records = []
    rejected = 0
    distribution = {
        f"{lo}-{hi}": 0
        for lo, hi in [
            (0, 9),
            (10, 19),
            (20, 29),
            (30, 39),
            (40, 49),
            (50, 59),
            (60, 69),
            (70, 79),
            (80, 89),
            (90, 100),
        ]
    }
    distribution["rejected"] = 0

    for i, c in enumerate(clips):
        scene = (scene_context or {}).get(c.name) or (scene_context or {}).get(str(c))
        try:
            rec = score_clip_fn(
                c,
                shot_profile,
                samples_per_clip=samples_per_clip,
                detect_trims_flag=detect_trims_flag,
                scene=scene,
                transcripts=transcripts,
                emotion_scene_weights=emotion_scene_weights,
            )
        except Exception as e:
            logger.warning("scoring failed for %s: %s", c.name, e)
            continue
        records.append(rec)
        if rec.get("rejection"):
            rejected += 1
            distribution["rejected"] += 1
        else:
            s = rec.get("score", 0)
            for lo, hi in [
                (90, 100),
                (80, 89),
                (70, 79),
                (60, 69),
                (50, 59),
                (40, 49),
                (30, 39),
                (20, 29),
                (10, 19),
                (0, 9),
            ]:
                if lo <= s <= hi:
                    distribution[f"{lo}-{hi}"] += 1
                    break
        if progress_cb:
            progress_cb(i + 1, len(clips), c.name)

    return {
        "version": "1.0",
        "analyzer_version": __version__,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "shot_profile_used": shot_profile.get("path", "shot-profile.json"),
        "total_clips": len(records),
        "clips_rejected": rejected,
        "score_distribution": distribution,
        "clips": records,
    }


def write_scores(result: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, default=str))
