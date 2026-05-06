"""Footage matchmaker — embed each film as a feature vector and rank
similarity by cosine distance.

Vector dimensions cover the things that actually distinguish wedding films
in this archive:
  - pacing (avg, std-dev, min, max)
  - transition mix (hard-cut / dissolve / fade ratios)
  - audio mix (music-only %, speech-over-music %, ambient %, first-speech %)
  - color (luminance, contrast, warm/cool, saturation)
  - shot mix (proportion of each shot-size label)
  - music (tempo BPM)

Each dimension is normalized to a [0, 1] range using fixed scales (so vectors
are comparable across films and across runs of the tool).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .schemas import FilmAnalysis
from .shot_size import SHOT_LABELS


@dataclass
class FilmVector:
    stem: str
    filename: str
    dimensions: dict[str, float]

    def values(self) -> list[float]:
        return [self.dimensions[k] for k in sorted(self.dimensions)]


# ---- normalization scales --------------------------------------------------
# Picked to be wide enough that real wedding-film values land comfortably in
# [0, 1] without saturating.

_SCALES = {
    "pacing.avg":      (0.5, 8.0),
    "pacing.std":      (0.0, 4.0),
    "pacing.min":      (0.2, 5.0),
    "pacing.max":      (1.0, 30.0),
    "trans.hard":      (0.0, 100.0),
    "trans.dissolve":  (0.0, 100.0),
    "trans.fade":      (0.0, 100.0),
    "audio.music":     (0.0, 100.0),
    "audio.spm":       (0.0, 100.0),
    "audio.ambient":   (0.0, 100.0),
    "audio.first_pct": (0.0, 100.0),
    "color.lum":       (0.0, 255.0),
    "color.contrast":  (0.0, 80.0),
    "color.wc":        (-1.0, 1.0),
    "color.sat":       (0.0, 255.0),
    "music.tempo":     (50.0, 180.0),
}


def _norm(name: str, val: float | None) -> float:
    if val is None:
        return 0.0
    lo, hi = _SCALES[name]
    if hi == lo:
        return 0.0
    return max(0.0, min(1.0, (val - lo) / (hi - lo)))


def build_vector(film: FilmAnalysis) -> FilmVector:
    dims: dict[str, float] = {}

    # Pacing
    p = film.pacing
    dims["pacing.avg"]   = _norm("pacing.avg",   p.avg_clip_duration_sec)
    dims["pacing.std"]   = _norm("pacing.std",   p.std_dev_sec)
    dims["pacing.min"]   = _norm("pacing.min",   p.min_clip_sec)
    dims["pacing.max"]   = _norm("pacing.max",   p.max_clip_sec)

    # Transitions (raw counts → percentages).
    t = film.transitions
    total = (t.hard_cut + t.dissolve + t.fade_in + t.fade_out) or 1
    dims["trans.hard"]     = _norm("trans.hard",     100 * t.hard_cut / total)
    dims["trans.dissolve"] = _norm("trans.dissolve", 100 * t.dissolve / total)
    dims["trans.fade"]     = _norm("trans.fade",     100 * (t.fade_in + t.fade_out) / total)

    # Audio mix
    a = (film.audio or {}).get("summary") or {}
    dims["audio.music"]     = _norm("audio.music",     a.get("music_only_pct"))
    dims["audio.spm"]       = _norm("audio.spm",       a.get("speech_over_music_pct"))
    dims["audio.ambient"]   = _norm("audio.ambient",   a.get("ambient_pct"))
    dims["audio.first_pct"] = _norm("audio.first_pct", a.get("first_speech_at_pct"))

    # Color
    c = film.color or {}
    dims["color.lum"]      = _norm("color.lum",      c.get("mean_luminance"))
    dims["color.contrast"] = _norm("color.contrast", c.get("mean_contrast"))
    dims["color.wc"]       = _norm("color.wc",       c.get("mean_warm_cool"))
    dims["color.sat"]      = _norm("color.sat",      c.get("mean_saturation"))

    # Music
    m = film.music or {}
    dims["music.tempo"] = _norm("music.tempo", m.get("tempo_bpm"))

    # Shot mix — one dim per label, value = proportion of clips with that label.
    n_labeled = sum(1 for cl in film.cuts.clips if cl.shot_size)
    for label in SHOT_LABELS:
        if n_labeled:
            count = sum(1 for cl in film.cuts.clips if cl.shot_size == label)
            dims[f"shot.{label}"] = count / n_labeled
        else:
            dims[f"shot.{label}"] = 0.0

    return FilmVector(
        stem=film.film.filename.rsplit(".", 1)[0],
        filename=film.film.filename,
        dimensions=dims,
    )


def cosine_similarity(a: FilmVector, b: FilmVector) -> float:
    """Cosine similarity in [0, 1]. Both vectors live in [0, 1] per dim, so
    the angle stays in the first quadrant and the score is non-negative."""
    keys = sorted(set(a.dimensions) | set(b.dimensions))
    av = [a.dimensions.get(k, 0.0) for k in keys]
    bv = [b.dimensions.get(k, 0.0) for k in keys]
    dot = sum(x * y for x, y in zip(av, bv))
    na = math.sqrt(sum(x * x for x in av))
    nb = math.sqrt(sum(x * x for x in bv))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def euclidean_distance(a: FilmVector, b: FilmVector) -> float:
    keys = sorted(set(a.dimensions) | set(b.dimensions))
    return math.sqrt(
        sum((a.dimensions.get(k, 0.0) - b.dimensions.get(k, 0.0)) ** 2 for k in keys)
    )


def find_similar(target: FilmAnalysis, archive: list[FilmAnalysis], top_n: int = 3
                 ) -> list[dict]:
    """Return top-N most similar films from the archive. Self is excluded if
    present (matched by filename)."""
    target_vec = build_vector(target)
    out = []
    for f in archive:
        if f.film.filename == target.film.filename:
            continue
        v = build_vector(f)
        out.append({
            "stem": v.stem,
            "filename": v.filename,
            "similarity": round(cosine_similarity(target_vec, v), 4),
            "distance": round(euclidean_distance(target_vec, v), 4),
        })
    out.sort(key=lambda x: -x["similarity"])
    return out[:top_n]


def biggest_differences(a: FilmAnalysis, b: FilmAnalysis, top_n: int = 5
                        ) -> list[dict]:
    """Per-dimension absolute difference, sorted descending. Useful for
    explaining why two films are NOT similar."""
    va = build_vector(a)
    vb = build_vector(b)
    diffs = []
    for k in sorted(set(va.dimensions) | set(vb.dimensions)):
        d = abs(va.dimensions.get(k, 0.0) - vb.dimensions.get(k, 0.0))
        diffs.append({"dimension": k, "delta": round(d, 4)})
    diffs.sort(key=lambda x: -x["delta"])
    return diffs[:top_n]
