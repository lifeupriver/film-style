"""Detect actual fade-in / fade-out at the film's start and end via brightness ramp.

A fade-from-black has the first frames near zero luminance ramping up over ~0.5-2s.
A fade-to-black has the last frames ramping down to near zero. Without a ramp the
edge is treated as a hard boundary instead of a fade.
"""

from __future__ import annotations

from pathlib import Path

DARK_THRESHOLD = 25.0  # mean luminance below which a frame is "near black"
RAMP_MIN_FRAMES = 4    # minimum elevated-ramp run length to count as a fade


def _open(path: Path):
    import cv2  # type: ignore
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {path}")
    return cap, cv2


def _frame_luminance(frame, cv2) -> float:
    import numpy as np  # type: ignore
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))


def detect_edges(film_path: Path, fps: float, scan_seconds: float = 2.5) -> tuple[bool, bool]:
    """Return (has_fade_in, has_fade_out)."""
    if fps <= 0:
        return False, False
    try:
        cap, cv2 = _open(film_path)
    except Exception:
        return False, False

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    scan_frames = max(RAMP_MIN_FRAMES + 2, int(scan_seconds * fps))

    has_fade_in = False
    has_fade_out = False
    try:
        # Fade-in: read first scan_frames, look for dark→bright ramp.
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        leading = []
        for _ in range(scan_frames):
            ok, frame = cap.read()
            if not ok:
                break
            leading.append(_frame_luminance(frame, cv2))
        if len(leading) >= RAMP_MIN_FRAMES and leading[0] < DARK_THRESHOLD:
            # Strictly increasing over the first half (rough monotone check).
            half = leading[:max(RAMP_MIN_FRAMES, len(leading) // 2)]
            if half[-1] > half[0] + DARK_THRESHOLD:
                has_fade_in = True

        # Fade-out: read last scan_frames.
        if total_frames > scan_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames - scan_frames))
            trailing = []
            for _ in range(scan_frames):
                ok, frame = cap.read()
                if not ok:
                    break
                trailing.append(_frame_luminance(frame, cv2))
            if len(trailing) >= RAMP_MIN_FRAMES and trailing[-1] < DARK_THRESHOLD:
                half = trailing[-max(RAMP_MIN_FRAMES, len(trailing) // 2):]
                if half[0] > half[-1] + DARK_THRESHOLD:
                    has_fade_out = True
    finally:
        cap.release()

    return has_fade_in, has_fade_out
