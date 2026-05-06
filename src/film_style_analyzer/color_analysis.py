"""Per-clip color analysis. Uses cv2 (already a dep via scenedetect[opencv]).

Extracts for each clip a sampled middle frame:
  - dominant_palette: k-means top-N colors as hex + weight
  - mean_luminance:   exposure proxy (0-255)
  - luminance_std:    contrast proxy (0-255)
  - warm_cool:        signed score in [-1, 1]; +warm, -cool
  - saturation:       mean S in HSV (0-255)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ClipColor:
    palette: list[dict]           # [{"hex": "#aabbcc", "weight": 0.42}, ...]
    mean_luminance: float         # 0–255
    luminance_std: float          # 0–255
    warm_cool: float              # -1 (cool) to +1 (warm)
    saturation: float             # 0–255


def _to_hex(b: int, g: int, r: int) -> str:
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def _kmeans_palette(frame_bgr, k: int, sample_max: int = 8000):
    """Run cv2.kmeans on a downsampled pixel set. Returns list of (bgr, weight)."""
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    h, w = frame_bgr.shape[:2]
    if h * w > sample_max:
        scale = (sample_max / (h * w)) ** 0.5
        small = cv2.resize(frame_bgr, (max(1, int(w * scale)), max(1, int(h * scale))),
                           interpolation=cv2.INTER_AREA)
    else:
        small = frame_bgr
    pixels = small.reshape(-1, 3).astype(np.float32)

    # Use a stricter k if the frame has very few pixels.
    k = max(1, min(k, max(1, pixels.shape[0] // 4)))

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    _, labels, centers = cv2.kmeans(
        pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
    )
    centers = centers.astype(int)
    counts = np.bincount(labels.flatten(), minlength=k)
    total = counts.sum() or 1

    out = []
    for i in range(k):
        b, g, r = centers[i]
        out.append({
            "hex": _to_hex(int(b), int(g), int(r)),
            "weight": round(float(counts[i]) / float(total), 4),
        })
    out.sort(key=lambda x: -x["weight"])
    return out


def _warm_cool_index(frame_bgr) -> float:
    """+1 = pure warm, -1 = pure cool, 0 = neutral. Mean (R-B) over saturated pixels."""
    import numpy as np  # type: ignore
    b, g, r = frame_bgr[..., 0].astype("int16"), frame_bgr[..., 1].astype("int16"), frame_bgr[..., 2].astype("int16")
    diff = r - b
    # Normalize by typical max range (~255). Clip to [-1, 1].
    return float(np.clip(diff.mean() / 128.0, -1.0, 1.0))


def _seek_frame(path: Path, sec: float):
    """Read a single frame at `sec` seconds. Returns BGR np array or None."""
    import cv2  # type: ignore
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, sec) * 1000.0)
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def analyze_clip(film_path: Path, clip_start_sec: float, clip_duration_sec: float,
                 k: int = 5) -> ClipColor | None:
    """Analyze one clip. Samples the middle of the clip (avoids cut artifacts)."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return None

    sample_at = clip_start_sec + max(0.05, clip_duration_sec / 2)
    frame = _seek_frame(film_path, sample_at)
    if frame is None or frame.size == 0:
        return None

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    palette = _kmeans_palette(frame, k=k)

    return ClipColor(
        palette=palette,
        mean_luminance=round(float(gray.mean()), 1),
        luminance_std=round(float(gray.std()), 1),
        warm_cool=round(_warm_cool_index(frame), 3),
        saturation=round(float(hsv[..., 1].mean()), 1),
    )


def analyze_film_color(film_path: Path, clips: list, *, every_n: int = 1, k: int = 5) -> dict:
    """Aggregate color for a film. Returns per-clip + per-film summary.

    `every_n`: sample one out of every N clips (set higher to speed up).
    """
    per_clip = []
    sampled = []

    for i, c in enumerate(clips):
        if i % every_n != 0:
            per_clip.append(None)
            continue
        cc = analyze_clip(film_path, c.start_sec, c.duration_sec, k=k)
        per_clip.append(cc.__dict__ if cc else None)
        if cc:
            sampled.append(cc)

    if not sampled:
        return {"per_clip": per_clip, "summary": None}

    n = len(sampled)
    summary = {
        "samples": n,
        "mean_luminance": round(sum(s.mean_luminance for s in sampled) / n, 1),
        "mean_contrast": round(sum(s.luminance_std for s in sampled) / n, 1),
        "mean_warm_cool": round(sum(s.warm_cool for s in sampled) / n, 3),
        "mean_saturation": round(sum(s.saturation for s in sampled) / n, 1),
        "dominant_palette": _aggregate_palette(sampled, top=8),
        "tone_label": _tone_label(
            sum(s.warm_cool for s in sampled) / n,
            sum(s.mean_luminance for s in sampled) / n,
            sum(s.saturation for s in sampled) / n,
        ),
    }
    return {"per_clip": per_clip, "summary": summary}


def _aggregate_palette(sampled: list[ClipColor], top: int = 8) -> list[dict]:
    """Combine palettes across sampled clips, weighted by clip presence."""
    bucket: dict[str, float] = {}
    for s in sampled:
        for entry in s.palette:
            bucket[entry["hex"]] = bucket.get(entry["hex"], 0.0) + entry["weight"]
    total = sum(bucket.values()) or 1.0
    items = sorted(bucket.items(), key=lambda kv: -kv[1])[:top]
    return [{"hex": h, "weight": round(w / total, 4)} for h, w in items]


def _tone_label(wc: float, lum: float, sat: float) -> str:
    """Human-friendly editorial tone label."""
    parts = []
    if lum < 80:
        parts.append("low-key")
    elif lum > 165:
        parts.append("high-key")
    else:
        parts.append("mid-key")
    if wc > 0.18:
        parts.append("warm")
    elif wc < -0.18:
        parts.append("cool")
    else:
        parts.append("neutral")
    if sat < 60:
        parts.append("desaturated")
    elif sat > 130:
        parts.append("saturated")
    return " · ".join(parts)
