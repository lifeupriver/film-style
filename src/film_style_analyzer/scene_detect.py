"""PySceneDetect wrapper. Returns clip list with transition tags.

For wedding-film aesthetics we use ContentDetector (HSV-difference based)
rather than AdaptiveDetector. Adaptive plateaus at 5–10 scenes regardless of
sensitivity on soft-cut/dissolve-heavy content; ContentDetector at threshold
~8 produces realistic clip counts (~3 sec avg).

Transition classification:
  - Boundaries detected by both the sensitive primary AND a strict secondary
    pass → hard cuts (large pixel delta).
  - Boundaries detected only by the sensitive primary → dissolves
    (small/gradual pixel delta).
"""

from __future__ import annotations

from pathlib import Path

from scenedetect import ContentDetector, open_video, SceneManager

from .fade_detect import detect_edges
from .schemas import Clip

DEFAULT_CONTENT_THRESHOLD = 8.0  # tuned for wedding-film soft cuts
HARD_CUT_THRESHOLD = 22.0        # secondary pass — only the strongest cuts


def _detect_scenes(path: Path, detector, min_scene_len_frames: int) -> list[tuple[float, float]]:
    video = open_video(str(path))
    sm = SceneManager()
    sm.add_detector(detector)
    sm.detect_scenes(video, show_progress=False)
    scenes = sm.get_scene_list()
    return [(s.get_seconds(), e.get_seconds()) for s, e in scenes]


def detect_clips(
    path: Path,
    min_scene_length_sec: float = 0.5,
    threshold: float | None = None,
) -> list[Clip]:
    """Detect cuts and classify each as hard_cut / dissolve / fade_in / fade_out.

    Args:
      threshold: ContentDetector primary threshold. Lower = more sensitive.
        Default 8.0 (wedding-film tuning). Try 12-15 for more aggressive
        narrative content; 5-6 for very soft/montage edits.
    """
    # Use the clip's real frame rate to convert the min-scene-length from
    # seconds to frames; fall back to 24 fps only if probing fails.
    from .media_probe import probe as _probe
    fps_hint = 24.0
    try:
        fps_hint = _probe(path).frame_rate or 24.0
    except Exception:
        fps_hint = 24.0
    min_frames = max(1, int(min_scene_length_sec * fps_hint))

    primary_threshold = threshold if threshold is not None else DEFAULT_CONTENT_THRESHOLD
    primary = _detect_scenes(
        path,
        ContentDetector(threshold=primary_threshold, min_scene_len=min_frames),
        min_frames,
    )

    if not primary:
        # No cuts detected — single clip.
        from .media_probe import probe
        meta = probe(path)
        try:
            has_fade_in, has_fade_out = detect_edges(path, fps=meta.frame_rate)
        except Exception:
            has_fade_in, has_fade_out = False, False
        return [Clip(
            index=0, start_sec=0.0, end_sec=meta.duration_sec,
            duration_sec=meta.duration_sec,
            transition_in="fade_in" if has_fade_in else "hard_cut",
            transition_out="fade_out" if has_fade_out else "hard_cut",
        )]

    # Classify each boundary by its actual frame-gradient signature: hard
    # cut (single-frame spike), dissolve (multi-frame plateau), or still_hold
    # (one side near-zero MAD because it's a held photograph).
    from .dissolve_measure import classify_boundaries
    from .media_probe import probe
    try:
        meta = probe(path)
        has_fade_in, has_fade_out = detect_edges(path, fps=meta.frame_rate)
    except Exception:
        meta = None
        has_fade_in, has_fade_out = False, False

    boundary_times = [s for s, _ in primary[1:]]  # skip first clip's start
    boundary_class: dict[float, str] = {}
    if meta and boundary_times:
        try:
            classified = classify_boundaries(path, boundary_times, fps=meta.frame_rate)
            for t, info in zip(boundary_times, classified):
                boundary_class[round(t, 2)] = info["type"]
        except Exception:
            pass

    clips: list[Clip] = []
    for i, (start, end) in enumerate(primary):
        is_first = i == 0
        is_last = i == len(primary) - 1
        in_key = round(start, 2)
        out_key = round(end, 2)
        if is_first:
            t_in = "fade_in" if has_fade_in else "hard_cut"
        else:
            t_in = boundary_class.get(in_key, "hard_cut")
        if is_last:
            t_out = "fade_out" if has_fade_out else "hard_cut"
        else:
            t_out = boundary_class.get(out_key, "hard_cut")
        clips.append(Clip(
            index=i, start_sec=start, end_sec=end,
            duration_sec=end - start,
            transition_in=t_in, transition_out=t_out,
        ))
    return clips
