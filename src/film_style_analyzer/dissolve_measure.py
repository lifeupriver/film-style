"""Measure transition duration by sampling frames around a cut boundary.

A hard cut produces a single-frame **spike** in inter-frame mean absolute
difference: the top-1 MAD is far higher than every other MAD in the window.
A dissolve produces a **plateau**: several adjacent frames show comparable
MAD values as the blend ramps up and down.

We use the spike-vs-plateau ratio (top-1 / top-2) to classify, plus the
estimated number of frames in the dominant cluster. This is robust to
wedding-film footage where intra-shot motion produces many frames with
moderately-elevated MAD.
"""

from __future__ import annotations

from pathlib import Path


def _open_capture(path: Path):
    import cv2  # type: ignore
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {path}")
    return cap, cv2


def classify_boundaries(
    film_path: Path,
    boundary_times_sec: list[float],
    fps: float,
    *,
    window_frames: int = 12,
    spike_ratio: float = 1.6,
    still_threshold: float = 1.5,
) -> list[dict]:
    """Sample frames around each boundary, return a list of:
        {"type": "hard_cut" | "dissolve" | "still_hold", "duration_sec": float}

    Algorithm:
      - If one side of the boundary has near-zero MAD (mean < `still_threshold`)
        and the other side has higher MAD, classify as `still_hold` — one side
        of the cut is a held still photograph.
      - Otherwise look for a SPIKE (top-1 ÷ top-2 ratio): hard cut.
      - Otherwise it's a dissolve plateau; measure plateau width.
    """
    results: list[dict] = []
    if not boundary_times_sec or fps <= 0:
        return [{"type": "hard_cut", "duration_sec": 1.0 / fps if fps > 0 else 0.04}
                for _ in boundary_times_sec]

    try:
        cap, cv2 = _open_capture(film_path)
    except Exception:
        return [{"type": "hard_cut", "duration_sec": 1.0 / fps}
                for _ in boundary_times_sec]

    try:
        import numpy as np  # type: ignore
    except ImportError:
        cap.release()
        return [{"type": "hard_cut", "duration_sec": 1.0 / fps}
                for _ in boundary_times_sec]

    one_frame = 1.0 / fps
    try:
        for t in boundary_times_sec:
            center_frame = int(round(t * fps))
            start_frame = max(0, center_frame - window_frames)
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

            diffs: list[float] = []
            prev_gray = None
            for _ in range(window_frames * 2):
                ok, frame = cap.read()
                if not ok:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if prev_gray is not None:
                    diffs.append(float(
                        np.mean(np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16)))
                    ))
                prev_gray = gray

            if len(diffs) < 4:
                results.append({"type": "hard_cut", "duration_sec": one_frame})
                continue

            # Check for still-hold: one half near-zero MAD, the other not.
            half = len(diffs) // 2
            mad_before = sum(diffs[:half]) / max(1, half)
            mad_after = sum(diffs[half:]) / max(1, len(diffs) - half)
            min_side, max_side = min(mad_before, mad_after), max(mad_before, mad_after)
            if (
                min_side < still_threshold
                and max_side > still_threshold * 2
            ):
                results.append({
                    "type": "still_hold",
                    "duration_sec": one_frame,
                })
                continue

            sorted_diffs = sorted(diffs, reverse=True)
            top1 = sorted_diffs[0]
            top2 = sorted_diffs[1]

            if top2 <= 0 or top1 / max(top2, 0.01) >= spike_ratio:
                results.append({"type": "hard_cut", "duration_sec": one_frame})
                continue

            plateau_threshold = top1 * 0.6
            plateau_frames = sum(1 for d in diffs if d >= plateau_threshold)
            results.append({
                "type": "dissolve",
                "duration_sec": round(max(plateau_frames / fps, one_frame), 3),
            })
    finally:
        cap.release()

    return results


def measure_dissolves(
    film_path: Path,
    boundary_times_sec: list[float],
    fps: float,
    window_frames: int = 12,
    spike_ratio: float = 1.6,
) -> list[float]:
    """For each boundary, classify as hard cut or dissolve and return the
    estimated transition duration in seconds.

    Algorithm: sample 2 * `window_frames` frames around the boundary, compute
    inter-frame MAD for each adjacent pair. If the largest MAD is at least
    `spike_ratio` times the second-largest MAD, the boundary is a hard cut
    (returns 1/fps). Otherwise it's a dissolve and we count how many frames
    are within 0.6 * top-MAD of the maximum (the plateau width).
    """
    if not boundary_times_sec or fps <= 0:
        return [1.0 / fps if fps > 0 else 0.04 for _ in boundary_times_sec]

    try:
        cap, cv2 = _open_capture(film_path)
    except Exception:
        return [1.0 / fps for _ in boundary_times_sec]

    durations: list[float] = []
    try:
        import numpy as np  # type: ignore
    except ImportError:
        cap.release()
        return [1.0 / fps for _ in boundary_times_sec]

    one_frame = 1.0 / fps
    try:
        for t in boundary_times_sec:
            center_frame = int(round(t * fps))
            start_frame = max(0, center_frame - window_frames)
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

            diffs: list[float] = []
            prev_gray = None
            for _ in range(window_frames * 2):
                ok, frame = cap.read()
                if not ok:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if prev_gray is not None:
                    diffs.append(float(
                        np.mean(np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16)))
                    ))
                prev_gray = gray

            if len(diffs) < 3:
                durations.append(one_frame)
                continue

            sorted_diffs = sorted(diffs, reverse=True)
            top1 = sorted_diffs[0]
            top2 = sorted_diffs[1]

            # Spike — single-frame jump dwarfs everything else → hard cut.
            if top2 <= 0 or top1 / max(top2, 0.01) >= spike_ratio:
                durations.append(one_frame)
                continue

            # Plateau — measure the run of frames above 60% of the max.
            plateau_threshold = top1 * 0.6
            plateau_frames = sum(1 for d in diffs if d >= plateau_threshold)
            durations.append(round(max(plateau_frames / fps, one_frame), 3))
    finally:
        cap.release()

    return durations
