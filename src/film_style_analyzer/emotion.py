"""Emotion detection via DeepFace, with genre-pack-driven scoring.

Per-frame: returns the dominant emotion plus a genre-weighted score.
A multi-face bonus rewards crowd reactions.

Per-clip: aggregates frame results using PEAK rather than mean — one
genuine moment in a 10-second clip is enough to make the clip useful.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .genre_pack import GenrePack

# Backward-compatible module-level defaults (wedding).
from .genre_pack import DEFAULT_EMOTION_WEIGHTS, DEFAULT_WEDDING_SCENE_WEIGHTS

EMOTION_WEIGHTS = DEFAULT_EMOTION_WEIGHTS
EMOTION_SCENE_WEIGHT = DEFAULT_WEDDING_SCENE_WEIGHTS

MULTI_FACE_BONUS_PER_FACE = 5
MULTI_FACE_BONUS_MAX = 15


def _empty_result() -> dict:
    return {
        "faces_analyzed": 0,
        "emotions": [],
        "emotional_intensity": 0.0,
        "multi_face_bonus": 0,
        "dominant_emotion": "none",
        "emotion_score": 0.0,
        "wedding_emotion_score": 0.0,
    }


def _emotion_weights(pack: "GenrePack | None") -> dict[str, float]:
    if pack is not None:
        return pack.emotion_weights
    return EMOTION_WEIGHTS


def analyze_emotions(frame_path: str | Path, pack: "GenrePack | None" = None) -> dict:
    """Run DeepFace emotion analysis on a frame. Returns a genre-scored summary."""
    try:
        from deepface import DeepFace
    except ImportError:
        return _empty_result()

    try:
        results = DeepFace.analyze(
            img_path=str(frame_path),
            actions=["emotion"],
            enforce_detection=False,
            detector_backend="mediapipe",
            silent=True,
        )
    except Exception as e:
        logger.debug("DeepFace.analyze failed for %s: %s", frame_path, e)
        return _empty_result()

    return _score_emotion_payload(results, weights=_emotion_weights(pack))


def _score_emotion_payload(results, *, weights: dict[str, float] | None = None) -> dict:
    """Convert a DeepFace result into a genre-scored summary."""
    weights = weights or EMOTION_WEIGHTS
    if not isinstance(results, list):
        results = [results] if results else []

    faces: list[dict] = []
    for face in results:
        emo = face.get("emotion", {}) or {}
        faces.append(
            {
                "dominant_emotion": face.get("dominant_emotion", "neutral"),
                "happy": round(float(emo.get("happy", 0)), 1),
                "surprise": round(float(emo.get("surprise", 0)), 1),
                "sad": round(float(emo.get("sad", 0)), 1),
                "neutral": round(float(emo.get("neutral", 0)), 1),
                "angry": round(float(emo.get("angry", 0)), 1),
                "fear": round(float(emo.get("fear", 0)), 1),
                "disgust": round(float(emo.get("disgust", 0)), 1),
            }
        )

    if not faces:
        return _empty_result()

    emotion_scores: list[float] = []
    for f in faces:
        s = sum(f[k] * weights.get(k, 0.0) for k in f if k != "dominant_emotion")
        emotion_scores.append(max(0.0, s))

    avg_score = sum(emotion_scores) / len(emotion_scores) if emotion_scores else 0.0
    if len(emotion_scores) > 1:
        bonus = min(len(emotion_scores) - 1, 3) * MULTI_FACE_BONUS_PER_FACE
    else:
        bonus = 0

    counts: dict[str, int] = {}
    for f in faces:
        counts[f["dominant_emotion"]] = counts.get(f["dominant_emotion"], 0) + 1
    dominant = max(counts, key=counts.get) if counts else "none"

    total = round(avg_score + bonus, 1)
    return {
        "faces_analyzed": len(faces),
        "emotions": faces,
        "emotional_intensity": round(avg_score, 1),
        "multi_face_bonus": bonus,
        "dominant_emotion": dominant,
        "emotion_score": total,
        "wedding_emotion_score": total,
    }


def aggregate_clip_emotions(frame_emotions: list[dict]) -> dict:
    """Across a clip's sampled frames, take PEAK emotion (not average)."""
    if not frame_emotions:
        empty = {
            "peak_emotion_score": 0.0,
            "peak_emotion_type": "none",
            "avg_emotion_score": 0.0,
            "emotional_frames_pct": 0.0,
            "peak_wedding_emotion": 0.0,
            "avg_wedding_emotion": 0.0,
        }
        return empty

    scores = [
        float(f.get("emotion_score", f.get("wedding_emotion_score", 0))) for f in frame_emotions
    ]
    peak_idx = scores.index(max(scores))
    peak_frame = frame_emotions[peak_idx]
    emotional_pct = len([s for s in scores if s > 20]) / len(scores) * 100
    peak = round(max(scores), 1)
    avg = round(sum(scores) / len(scores), 1)
    return {
        "peak_emotion_score": peak,
        "peak_emotion_type": peak_frame.get("dominant_emotion", "none"),
        "avg_emotion_score": avg,
        "emotional_frames_pct": round(emotional_pct, 1),
        "peak_wedding_emotion": peak,
        "avg_wedding_emotion": avg,
    }


def scene_emotion_weight(scene: str | None, pack: "GenrePack | None") -> float:
    if not scene:
        return 1.0
    if pack is not None:
        return pack.emotion_scene_weights.get(scene, 1.0)
    return EMOTION_SCENE_WEIGHT.get(scene, 1.0)
