"""Aggregate per-frame composition + emotion data from analyzed films into
a single shot-profile.json — the editor's learned aesthetic, used by
score-clips to rate raw footage."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .composition import analyze_frame
from .emotion import analyze_emotions


def _pct(num: int, denom: int, decimals: int = 1) -> float:
    if denom == 0:
        return 0.0
    return round(num / denom * 100, decimals)


def _distribution(values: list[str]) -> dict[str, float]:
    if not values:
        return {}
    counts = Counter(values)
    n = len(values)
    return {k: round(v / n, 3) for k, v in counts.most_common()}


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


def aggregate_frames(frame_results: list[dict]) -> dict:
    """Pure aggregation: takes per-frame composition+emotion dicts and
    returns the shot-profile structure. Kept separate from the file-walking
    code so tests can call it with synthetic frame data."""
    n = len(frame_results)
    if n == 0:
        return {
            "version": "1.0",
            "analyzer_version": __version__,
            "films_analyzed": 0,
            "total_frames_analyzed": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    framings = [f.get("framing", "no-person") for f in frame_results]
    framing_dist = _distribution(framings)
    preferred = next(iter(framing_dist), "medium")

    with_faces = [f for f in frame_results if f.get("faces_detected", 0) > 0]
    facing_camera = [f for f in with_faces if f.get("facing_camera")]
    avg_faces = statistics.fmean(f.get("faces_detected", 0) for f in frame_results) if n else 0
    primary_face_sizes = [f["face_size_pct"] for f in with_faces if f.get("face_size_pct", 0) > 0]

    thirds_scores = [
        f["thirds_score"]
        for f in frame_results
        if f.get("thirds_score") is not None and f.get("face_center_x") is not None
    ]
    face_center_ys = [f["face_center_y"] for f in with_faces if f.get("face_center_y") is not None]
    headrooms = [f["headroom_pct"] for f in with_faces if f.get("headroom_pct") is not None]

    brightnesses = [
        f["mean_brightness"] for f in frame_results if f.get("mean_brightness") is not None
    ]
    laps = [
        f["laplacian_variance"] for f in frame_results if f.get("laplacian_variance") is not None
    ]
    seps = [
        f["subject_separation_ratio"]
        for f in frame_results
        if f.get("subject_separation_ratio") is not None
    ]

    head_cutoff_count = sum(1 for f in frame_results if f.get("head_cutoff"))
    no_face_count = sum(
        1
        for f in frame_results
        if f.get("faces_detected", 0) == 0 and f.get("framing") != "no-person"
    )
    very_soft_count = sum(1 for f in frame_results if f.get("focus_rating") == "very-soft")
    sev_under_count = sum(
        1 for f in frame_results if f.get("exposure_rating") == "severely-underexposed"
    )
    sev_over_count = sum(
        1 for f in frame_results if f.get("exposure_rating") == "severely-overexposed"
    )

    # Emotion aggregation. Frame results may carry an `emotion` sub-dict.
    emotion_frames = [f.get("emotion") for f in frame_results if f.get("emotion")]
    intensities = [
        e.get("emotion_score", e.get("wedding_emotion_score", 0))
        for e in emotion_frames
        if e.get("emotion_score") is not None or e.get("wedding_emotion_score") is not None
    ]
    dominant_emotions = [
        e.get("dominant_emotion", "none") for e in emotion_frames if e.get("faces_analyzed", 0) > 0
    ]
    emotion_dist = _distribution(dominant_emotions) if dominant_emotions else {}

    above_20 = sum(1 for s in intensities if s > 20)
    above_40 = sum(1 for s in intensities if s > 40)
    neutral_count = sum(1 for d in dominant_emotions if d == "neutral")

    return {
        "version": "1.0",
        "analyzer_version": __version__,
        "films_analyzed": 0,  # filled in by caller
        "total_frames_analyzed": n,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "framing_distribution": framing_dist,
        "preferred_framing": preferred,
        "face_presence": {
            "frames_with_faces_pct": _pct(len(with_faces), n),
            "avg_faces_per_frame": round(avg_faces, 2),
            "primary_face_avg_size_pct": (
                round(statistics.fmean(primary_face_sizes), 2) if primary_face_sizes else 0.0
            ),
            "facing_camera_pct": _pct(len(facing_camera), max(1, len(with_faces))),
        },
        "composition": {
            "avg_thirds_score": (
                round(statistics.fmean(thirds_scores), 3) if thirds_scores else 0.0
            ),
            "preferred_face_center_y": (
                round(statistics.fmean(face_center_ys), 3) if face_center_ys else 0.5
            ),
            "preferred_face_center_y_range": (
                [
                    round(_percentile(face_center_ys, 10), 3),
                    round(_percentile(face_center_ys, 90), 3),
                ]
                if face_center_ys
                else [0.0, 1.0]
            ),
            "avg_headroom_pct": (round(statistics.fmean(headrooms), 2) if headrooms else 0.0),
            "headroom_range": (
                [round(_percentile(headrooms, 10), 1), round(_percentile(headrooms, 90), 1)]
                if headrooms
                else [0.0, 100.0]
            ),
        },
        "exposure": {
            "avg_brightness": (round(statistics.fmean(brightnesses), 3) if brightnesses else 0.0),
            "brightness_range": (
                [round(_percentile(brightnesses, 10), 3), round(_percentile(brightnesses, 90), 3)]
                if brightnesses
                else [0.0, 1.0]
            ),
        },
        "sharpness": {
            "avg_laplacian": round(statistics.fmean(laps), 2) if laps else 0.0,
            "min_laplacian_used": round(_percentile(laps, 5), 2) if laps else 0.0,
        },
        "subject_separation": {
            "avg_center_to_edge_ratio": (round(statistics.fmean(seps), 2) if seps else 1.0),
            "min_ratio_used": round(_percentile(seps, 10), 2) if seps else 1.0,
        },
        "emotion_preferences": {
            "avg_peak_emotion_in_finished_films": (
                round(statistics.fmean(intensities), 1) if intensities else 0.0
            ),
            "pct_frames_with_emotion_above_20": _pct(above_20, max(1, len(intensities))),
            "pct_frames_with_emotion_above_40": _pct(above_40, max(1, len(intensities))),
            "pct_frames_neutral": _pct(neutral_count, max(1, len(dominant_emotions))),
            "dominant_emotions_distribution": emotion_dist,
        },
        "rejection_rules_learned": {
            "head_cutoff_pct": _pct(head_cutoff_count, n, 2),
            "no_face_in_people_shots_pct": _pct(no_face_count, n, 2),
            "very_soft_focus_pct": _pct(very_soft_count, n, 2),
            "severely_underexposed_pct": _pct(sev_under_count, n, 2),
            "severely_overexposed_pct": _pct(sev_over_count, n, 2),
        },
    }


def learn_from_thumbnails(
    thumbs_root: Path,
    films: list[str] | None = None,
    progress_cb=None,
    analyze_frame_fn=None,
    analyze_emotion_fn=None,
) -> dict:
    """Walk the thumbnail directories and aggregate. `films` is an optional
    list of film stems (subdirectory names) to restrict to. The two `_fn`
    parameters let tests inject deterministic detectors."""
    analyze_frame_fn = analyze_frame_fn or analyze_frame
    analyze_emotion_fn = analyze_emotion_fn or analyze_emotions

    if not thumbs_root.exists():
        raise FileNotFoundError(f"thumbs directory does not exist: {thumbs_root}")

    if films:
        film_dirs = []
        for f in films:
            stem = Path(f).stem
            d = thumbs_root / stem
            if d.is_dir():
                film_dirs.append(d)
    else:
        film_dirs = sorted(p for p in thumbs_root.iterdir() if p.is_dir())

    if not film_dirs:
        raise FileNotFoundError(
            f"no analyzed films found under {thumbs_root}; run `film-style analyze` first."
        )

    frame_results: list[dict] = []
    total_frames = sum(len(list(d.glob("*.jpg"))) for d in film_dirs)
    seen = 0

    for film_dir in film_dirs:
        for jpg in sorted(film_dir.glob("*.jpg")):
            comp = analyze_frame_fn(jpg)
            if "error" in comp:
                seen += 1
                if progress_cb:
                    progress_cb(seen, total_frames, jpg.name)
                continue
            emo = analyze_emotion_fn(jpg)
            comp["emotion"] = emo
            frame_results.append(comp)
            seen += 1
            if progress_cb:
                progress_cb(seen, total_frames, jpg.name)

    profile = aggregate_frames(frame_results)
    profile["films_analyzed"] = len(film_dirs)
    return profile


def write_profile(profile: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, indent=2))
