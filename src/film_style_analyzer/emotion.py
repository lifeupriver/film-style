"""Emotion detection via DeepFace, with wedding-specific scoring.

Per-frame: returns the dominant emotion plus a wedding score that boosts
happy, surprise, and sad (happy tears) and penalizes angry/fear/disgust.
A multi-face bonus rewards crowd reactions.

Per-clip: aggregates frame results using PEAK rather than mean — one
genuine moment in a 10-second clip is enough to make the clip useful.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# Wedding scoring weights. Happy is the obvious primary, surprise picks
# up first-look reactions, and a measured sad-positive captures happy tears.
EMOTION_WEIGHTS = {
    "happy": 1.0,
    "surprise": 0.6,
    "sad": 0.4,
    "neutral": 0.0,
    "angry": -0.5,
    "fear": -0.3,
    "disgust": -0.5,
}


# Multi-face bonus: each additional emotional face adds 5 points, capped.
MULTI_FACE_BONUS_PER_FACE = 5
MULTI_FACE_BONUS_MAX = 15


# Scene-aware emotion weighting consumed by clip_scoring. Wedding scenes
# where emotion is the whole point get >1.0; details / B-roll get 0.0
# because emotion shouldn't influence whether a sunset is keeper-worthy.
EMOTION_SCENE_WEIGHT = {
    "first_look": 1.5,
    "ceremony": 1.5,
    "speeches": 1.5,
    "parent_dances": 1.3,
    "first_dance": 1.2,
    "dancing": 1.0,
    "couple_photos": 1.0,
    "getting_ready_bride": 0.8,
    "getting_ready_groom": 0.8,
    "cocktail_hour": 0.7,
    "family_photos": 0.8,
    "reception_details": 0.0,
    "b_roll": 0.0,
    "exit": 1.0,
}


def _empty_result() -> dict:
    return {
        "faces_analyzed": 0,
        "emotions": [],
        "emotional_intensity": 0.0,
        "multi_face_bonus": 0,
        "dominant_emotion": "none",
        "wedding_emotion_score": 0.0,
    }


def analyze_emotions(frame_path: str | Path) -> dict:
    """Run DeepFace emotion analysis on a frame. Returns a wedding-scored
    summary. Returns the empty result on any DeepFace failure (no face
    found, missing model, OOM, etc.)."""
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

    return _score_emotion_payload(results)


def _score_emotion_payload(results) -> dict:
    """Convert a DeepFace result (single dict or list of dicts) into the
    wedding-scored summary. Pure function — kept separate from analyze_emotions
    so tests can stub the DeepFace return value."""
    if not isinstance(results, list):
        results = [results] if results else []

    faces: list[dict] = []
    for face in results:
        emo = face.get("emotion", {}) or {}
        faces.append({
            "dominant_emotion": face.get("dominant_emotion", "neutral"),
            "happy": round(float(emo.get("happy", 0)), 1),
            "surprise": round(float(emo.get("surprise", 0)), 1),
            "sad": round(float(emo.get("sad", 0)), 1),
            "neutral": round(float(emo.get("neutral", 0)), 1),
            "angry": round(float(emo.get("angry", 0)), 1),
            "fear": round(float(emo.get("fear", 0)), 1),
            "disgust": round(float(emo.get("disgust", 0)), 1),
        })

    if not faces:
        return _empty_result()

    wedding_scores: list[float] = []
    for f in faces:
        s = sum(f[k] * w for k, w in EMOTION_WEIGHTS.items())
        wedding_scores.append(max(0.0, s))

    avg_score = sum(wedding_scores) / len(wedding_scores) if wedding_scores else 0.0
    if len(wedding_scores) > 1:
        bonus = min(len(wedding_scores) - 1, 3) * MULTI_FACE_BONUS_PER_FACE
    else:
        bonus = 0

    counts: dict[str, int] = {}
    for f in faces:
        counts[f["dominant_emotion"]] = counts.get(f["dominant_emotion"], 0) + 1
    dominant = max(counts, key=counts.get) if counts else "none"

    return {
        "faces_analyzed": len(faces),
        "emotions": faces,
        "emotional_intensity": round(avg_score, 1),
        "multi_face_bonus": bonus,
        "dominant_emotion": dominant,
        "wedding_emotion_score": round(avg_score + bonus, 1),
    }


def aggregate_clip_emotions(frame_emotions: list[dict]) -> dict:
    """Across a clip's sampled frames, take PEAK emotion (not average).
    A single genuine moment makes a clip worth including."""
    if not frame_emotions:
        return {
            "peak_wedding_emotion": 0.0,
            "peak_emotion_type": "none",
            "avg_wedding_emotion": 0.0,
            "emotional_frames_pct": 0.0,
        }

    scores = [float(f.get("wedding_emotion_score", 0)) for f in frame_emotions]
    peak_idx = scores.index(max(scores))
    peak_frame = frame_emotions[peak_idx]
    emotional_pct = (
        len([s for s in scores if s > 20]) / len(scores) * 100
    )
    return {
        "peak_wedding_emotion": round(max(scores), 1),
        "peak_emotion_type": peak_frame.get("dominant_emotion", "none"),
        "avg_wedding_emotion": round(sum(scores) / len(scores), 1),
        "emotional_frames_pct": round(emotional_pct, 1),
    }
