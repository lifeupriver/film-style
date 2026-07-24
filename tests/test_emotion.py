"""Emotion scoring — pure functions tested via stubbed DeepFace payloads."""

from film_style_analyzer.emotion import (
    EMOTION_SCENE_WEIGHT,
    _score_emotion_payload,
    aggregate_clip_emotions,
)


def _df_face(dominant="happy", **emotions):
    base = {"happy": 0, "surprise": 0, "sad": 0, "neutral": 0, "angry": 0, "fear": 0, "disgust": 0}
    base.update(emotions)
    return {"dominant_emotion": dominant, "emotion": base}


# ---------------------------------------------------------------------------
# Per-frame scoring
# ---------------------------------------------------------------------------


class TestEmotionScoring:
    def test_smiling_face_scores_high(self):
        result = _score_emotion_payload(_df_face("happy", happy=85.0, neutral=10.0))
        assert result["dominant_emotion"] == "happy"
        assert result["wedding_emotion_score"] > 60

    def test_neutral_face_scores_low(self):
        result = _score_emotion_payload(_df_face("neutral", neutral=80.0, happy=10.0))
        assert result["dominant_emotion"] == "neutral"
        assert result["wedding_emotion_score"] < 20

    def test_angry_face_negative_weighted_to_zero(self):
        result = _score_emotion_payload(_df_face("angry", angry=80.0))
        # Negative scores are clamped to 0 per face
        assert result["wedding_emotion_score"] == 0
        assert result["emotional_intensity"] == 0

    def test_surprise_with_some_happy(self):
        result = _score_emotion_payload(_df_face("surprise", surprise=60.0, happy=20.0))
        # 60*0.6 + 20*1.0 = 56
        assert 50 <= result["wedding_emotion_score"] <= 65

    def test_happy_tears_sad_weighted_positive(self):
        # Sad weighted positive (0.4) for happy-tears moments.
        result = _score_emotion_payload(_df_face("sad", sad=70.0, happy=20.0))
        # 70*0.4 + 20*1.0 = 48
        assert 40 <= result["wedding_emotion_score"] <= 55

    def test_no_face_returns_empty(self):
        result = _score_emotion_payload([])
        assert result["faces_analyzed"] == 0
        assert result["wedding_emotion_score"] == 0
        assert result["dominant_emotion"] == "none"

    def test_handles_single_dict_input(self):
        # DeepFace returns a single dict when only one face found.
        single = _df_face("happy", happy=70.0)
        result = _score_emotion_payload(single)
        assert result["faces_analyzed"] == 1


# ---------------------------------------------------------------------------
# Multi-face bonus
# ---------------------------------------------------------------------------


class TestMultiFaceBonus:
    def test_two_happy_faces_score_higher_than_one(self):
        single = _score_emotion_payload(_df_face("happy", happy=70.0))
        double = _score_emotion_payload(
            [
                _df_face("happy", happy=70.0),
                _df_face("happy", happy=70.0),
            ]
        )
        assert double["wedding_emotion_score"] > single["wedding_emotion_score"]
        assert double["multi_face_bonus"] == 5

    def test_three_faces_bonus_capped(self):
        result = _score_emotion_payload([_df_face("happy", happy=80.0) for _ in range(5)])
        # Bonus capped at 3 extra faces * 5 = 15.
        assert result["multi_face_bonus"] == 15

    def test_single_face_no_bonus(self):
        result = _score_emotion_payload(_df_face("happy", happy=70.0))
        assert result["multi_face_bonus"] == 0


# ---------------------------------------------------------------------------
# Per-clip aggregation: PEAK not average
# ---------------------------------------------------------------------------


class TestClipAggregation:
    def test_peak_used_not_average(self):
        # 3 neutral frames, 1 strongly emotional frame.
        frames = [
            {"wedding_emotion_score": 5.0, "dominant_emotion": "neutral"},
            {"wedding_emotion_score": 3.0, "dominant_emotion": "neutral"},
            {"wedding_emotion_score": 65.0, "dominant_emotion": "happy"},
            {"wedding_emotion_score": 8.0, "dominant_emotion": "neutral"},
        ]
        result = aggregate_clip_emotions(frames)
        assert result["peak_wedding_emotion"] == 65.0
        assert result["peak_emotion_type"] == "happy"
        # avg ~ 20.25
        assert 15 <= result["avg_wedding_emotion"] <= 25

    def test_emotional_frames_pct(self):
        frames = [
            {"wedding_emotion_score": 30.0, "dominant_emotion": "happy"},
            {"wedding_emotion_score": 5.0, "dominant_emotion": "neutral"},
            {"wedding_emotion_score": 25.0, "dominant_emotion": "happy"},
            {"wedding_emotion_score": 10.0, "dominant_emotion": "neutral"},
        ]
        result = aggregate_clip_emotions(frames)
        # 2 of 4 are above 20.
        assert result["emotional_frames_pct"] == 50.0

    def test_empty_frames(self):
        result = aggregate_clip_emotions([])
        assert result["peak_wedding_emotion"] == 0
        assert result["peak_emotion_type"] == "none"


# ---------------------------------------------------------------------------
# Scene-aware weighting
# ---------------------------------------------------------------------------


class TestSceneWeights:
    def test_ceremony_weighted_above_one(self):
        assert EMOTION_SCENE_WEIGHT["ceremony"] == 1.5

    def test_b_roll_zero(self):
        assert EMOTION_SCENE_WEIGHT["b_roll"] == 0.0

    def test_reception_details_zero(self):
        assert EMOTION_SCENE_WEIGHT["reception_details"] == 0.0

    def test_first_look_high(self):
        assert EMOTION_SCENE_WEIGHT["first_look"] == 1.5
