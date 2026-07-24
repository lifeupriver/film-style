"""Clip scoring + trim detection — pure unit tests."""

from film_style_analyzer.clip_scoring import (
    _trim_window_from_scores,
    aggregate_clip_frames,
    collect_penalties,
    compute_clip_score,
    map_to_original,
    speech_trim_from_transcript,
)


def _profile(preferred="medium", face_size=8.0):
    return {
        "preferred_framing": preferred,
        "face_presence": {"primary_face_avg_size_pct": face_size},
    }


def _good_clip(**overrides):
    base = {
        "has_person": True,
        "framing": "medium",
        "faces_detected": 1,
        "face_size_pct": 9.0,
        "facing_camera": True,
        "head_cutoff": False,
        "headroom_pct": 12.0,
        "lead_room_ratio": 1.5,
        "thirds_score": 0.7,
        "horizon_tilt_degrees": 0.5,
        "horizon_lines_detected": False,
        "exposure_rating": "good",
        "mean_brightness": 0.50,
        "backlit": False,
        "focus_rating": "sharp",
        "laplacian_variance": 200.0,
        "subject_separation_ratio": 2.5,
        "motion_blur_on_subject": False,
        "stability": "stable",
        "avg_motion_magnitude": 1.5,
        "emotion": {
            "peak_wedding_emotion": 50.0,
            "peak_emotion_type": "happy",
            "avg_wedding_emotion": 25.0,
            "emotional_frames_pct": 50.0,
        },
        "penalties_applied": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Hard rejections
# ---------------------------------------------------------------------------


class TestHardRejections:
    def test_severely_underexposed_rejected(self):
        clip = _good_clip(mean_brightness=0.05)
        score, reason = compute_clip_score(clip, _profile())
        assert score == 0
        assert reason == "severely_underexposed"

    def test_severely_overexposed_rejected(self):
        clip = _good_clip(mean_brightness=0.95)
        score, reason = compute_clip_score(clip, _profile())
        assert score == 0
        assert reason == "severely_overexposed"

    def test_completely_out_of_focus_rejected(self):
        clip = _good_clip(laplacian_variance=10.0)
        score, reason = compute_clip_score(clip, _profile())
        assert score == 0
        assert reason == "completely_out_of_focus"

    def test_head_cutoff_rejected_when_face_present(self):
        clip = _good_clip(head_cutoff=True, faces_detected=1)
        score, reason = compute_clip_score(clip, _profile())
        assert score == 0
        assert reason == "head_cut_off"

    def test_head_cutoff_no_face_not_rejected(self):
        clip = _good_clip(head_cutoff=True, faces_detected=0, framing="no-person", has_person=False)
        score, reason = compute_clip_score(clip, _profile())
        assert score > 0
        assert reason is None


# ---------------------------------------------------------------------------
# Composite score
# ---------------------------------------------------------------------------


class TestCompositeScore:
    def test_high_composition_high_emotion_outranks_no_emotion(self):
        # Use a medium-close clip (close to preferred but not exact match)
        # and acceptable focus so the clip doesn't already cap at 100.
        common = dict(
            framing="medium-close",
            thirds_score=0.4,
            subject_separation_ratio=1.5,
            lead_room_ratio=1.0,
            focus_rating="acceptable",
            laplacian_variance=80,
            exposure_rating="acceptable",
        )
        good_with_emotion = _good_clip(**common)
        good_no_emotion = _good_clip(
            **common,
            emotion={
                "peak_wedding_emotion": 5.0,
                "peak_emotion_type": "neutral",
                "avg_wedding_emotion": 5.0,
                "emotional_frames_pct": 0.0,
            },
        )
        s1, _ = compute_clip_score(good_with_emotion, _profile())
        s2, _ = compute_clip_score(good_no_emotion, _profile())
        assert s1 > s2

    def test_baseline_50_for_neutral_clip(self):
        # Strip everything to baseline.
        clip = _good_clip(
            framing="other",
            faces_detected=0,
            has_person=False,
            thirds_score=0.0,
            lead_room_ratio=None,
            subject_separation_ratio=1.0,
            headroom_pct=None,
            exposure_rating="acceptable",
            focus_rating="acceptable",
            emotion={
                "peak_wedding_emotion": 0.0,
                "peak_emotion_type": "none",
                "avg_wedding_emotion": 0.0,
                "emotional_frames_pct": 0.0,
            },
        )
        score, _ = compute_clip_score(clip, _profile())
        # baseline 50 + 5 (acceptable exposure) + 5 (acceptable focus)
        assert 55 <= score <= 70

    def test_score_clamped_to_0_100(self):
        clip = _good_clip(
            penalties_applied=[
                {"name": "x", "value": -200},  # nuclear penalty
            ]
        )
        score, _ = compute_clip_score(clip, _profile())
        assert score >= 0

    def test_perfect_clip_caps_at_100(self):
        clip = _good_clip(
            emotion={
                "peak_wedding_emotion": 80.0,
                "peak_emotion_type": "happy",
                "avg_wedding_emotion": 60.0,
                "emotional_frames_pct": 80.0,
            }
        )
        score, _ = compute_clip_score(clip, _profile(), scene="ceremony")
        assert score <= 100


# ---------------------------------------------------------------------------
# Soft penalties
# ---------------------------------------------------------------------------


class TestPenalties:
    def test_excessive_shake_penalty(self):
        clip = _good_clip(avg_motion_magnitude=10.0)
        pens = collect_penalties(clip, has_person=True)
        names = [p["name"] for p in pens]
        assert "excessive_shake" in names

    def test_moderate_shake_penalty(self):
        clip = _good_clip(avg_motion_magnitude=6.0)
        pens = collect_penalties(clip, has_person=True)
        names = [p["name"] for p in pens]
        assert "moderate_shake" in names

    def test_too_tight_crop(self):
        clip = _good_clip(framing="extreme-close-up")
        pens = collect_penalties(clip, has_person=True)
        names = [p["name"] for p in pens]
        assert "too_tight_crop" in names

    def test_horizon_tilt_only_when_lines_detected(self):
        # Tilted but no architectural lines -> no penalty.
        clip = _good_clip(horizon_tilt_degrees=8.0, horizon_lines_detected=False)
        pens = collect_penalties(clip, has_person=True)
        assert not any(p["name"] == "horizon_tilted" for p in pens)
        # Tilted with lines detected -> penalty applies.
        clip2 = _good_clip(horizon_tilt_degrees=8.0, horizon_lines_detected=True)
        pens2 = collect_penalties(clip2, has_person=True)
        assert any(p["name"] == "horizon_tilted" for p in pens2)

    def test_poor_headroom_penalty(self):
        clip = _good_clip(headroom_pct=2.0)
        pens = collect_penalties(clip, has_person=True)
        assert any(p["name"] == "poor_headroom" for p in pens)

    def test_shooting_from_behind(self):
        clip = _good_clip(
            faces_detected=0,
            framing="medium",
            headroom_pct=None,
            lead_room_ratio=None,
            subject_separation_ratio=2.5,
        )
        pens = collect_penalties(clip, has_person=True)
        assert any(p["name"] == "shooting_from_behind" for p in pens)

    def test_b_roll_no_face_penalties(self):
        # When has_person=False, face/headroom/lead-room penalties skipped.
        clip = _good_clip(
            faces_detected=0,
            framing="no-person",
            headroom_pct=None,
            lead_room_ratio=None,
            has_person=False,
        )
        pens = collect_penalties(clip, has_person=False)
        names = [p["name"] for p in pens]
        assert "shooting_from_behind" not in names
        assert "poor_headroom" not in names

    def test_penalty_stacking_clamped(self):
        clip = _good_clip(
            penalties_applied=[
                {"name": "a", "value": -20},
                {"name": "b", "value": -20},
                {"name": "c", "value": -30},
            ]
        )
        score, _ = compute_clip_score(clip, _profile())
        assert score >= 0


# ---------------------------------------------------------------------------
# Scene-aware emotion weighting
# ---------------------------------------------------------------------------


class TestSceneWeighting:
    def test_ceremony_boosts_emotion_more_than_b_roll(self):
        # Same dampening as the composition+emotion test so the score doesn't
        # cap at 100 before scene weighting matters.
        clip = _good_clip(
            framing="medium-close",
            thirds_score=0.4,
            subject_separation_ratio=1.5,
            lead_room_ratio=1.0,
            focus_rating="acceptable",
            laplacian_variance=80,
            exposure_rating="acceptable",
        )
        s_ceremony, _ = compute_clip_score(clip, _profile(), scene="ceremony")
        s_broll, _ = compute_clip_score(clip, _profile(), scene="b_roll")
        assert s_ceremony > s_broll

    def test_no_scene_uses_default_weight(self):
        clip = _good_clip()
        s_default, _ = compute_clip_score(clip, _profile(), scene=None)
        s_dancing, _ = compute_clip_score(clip, _profile(), scene="dancing")
        assert s_default == s_dancing


# ---------------------------------------------------------------------------
# B-roll handling: no face/emotion penalties
# ---------------------------------------------------------------------------


class TestBRollHandling:
    def test_b_roll_scored_without_face_or_emotion(self):
        clip = _good_clip(
            framing="no-person",
            faces_detected=0,
            has_person=False,
            face_size_pct=0,
            headroom_pct=None,
            lead_room_ratio=None,
            thirds_score=0.0,
            subject_separation_ratio=1.0,
            emotion={
                "peak_wedding_emotion": 0.0,
                "peak_emotion_type": "none",
                "avg_wedding_emotion": 0.0,
                "emotional_frames_pct": 0.0,
            },
        )
        score, reason = compute_clip_score(clip, _profile())
        assert reason is None
        # 50 baseline + 10 (good exposure) + 10 (sharp) = 70
        assert score >= 65


# ---------------------------------------------------------------------------
# Clip frame aggregation: median for composition
# ---------------------------------------------------------------------------


class TestAggregateClipFrames:
    def test_median_used_for_composition(self):
        frames = [
            {
                "has_person": True,
                "framing": "medium",
                "faces_detected": 1,
                "face_size_pct": 5,
                "thirds_score": 0.5,
                "headroom_pct": 8,
                "horizon_tilt_degrees": 0.5,
                "exposure_rating": "good",
                "focus_rating": "sharp",
                "laplacian_variance": 100,
                "subject_separation_ratio": 2.0,
                "mean_brightness": 0.5,
                "facing_camera": True,
                "head_cutoff": False,
            },
            {
                "has_person": True,
                "framing": "medium",
                "faces_detected": 1,
                "face_size_pct": 8,
                "thirds_score": 0.7,
                "headroom_pct": 12,
                "horizon_tilt_degrees": 0.5,
                "exposure_rating": "good",
                "focus_rating": "sharp",
                "laplacian_variance": 150,
                "subject_separation_ratio": 2.5,
                "mean_brightness": 0.5,
                "facing_camera": True,
                "head_cutoff": False,
            },
            {
                "has_person": True,
                "framing": "medium",
                "faces_detected": 1,
                "face_size_pct": 50,
                "thirds_score": 0.9,
                "headroom_pct": 30,
                "horizon_tilt_degrees": 0.5,
                "exposure_rating": "good",
                "focus_rating": "sharp",
                "laplacian_variance": 200,
                "subject_separation_ratio": 3.0,
                "mean_brightness": 0.5,
                "facing_camera": True,
                "head_cutoff": False,
            },
        ]
        agg = aggregate_clip_frames(frames, motion_values=[1.0, 1.5])
        # Median of [5, 8, 50] -> 8 (outlier rejected)
        assert agg["face_size_pct"] == 8.0
        assert agg["headroom_pct"] == 12.0


# ---------------------------------------------------------------------------
# Trim detection
# ---------------------------------------------------------------------------


class TestTrimWindow:
    def test_shaky_start_trimmed(self):
        # First two frames are shaky/soft, rest are good.
        scores = [
            {"time_sec": 0.0, "sharp": False, "stable": False},
            {"time_sec": 0.5, "sharp": False, "stable": True},
            {"time_sec": 1.0, "sharp": True, "stable": True},
            {"time_sec": 1.5, "sharp": True, "stable": True},
            {"time_sec": 2.0, "sharp": True, "stable": True},
        ]
        result = _trim_window_from_scores(scores, duration=2.5, interval_sec=0.5)
        assert result["trim_in_sec"] == 1.0
        assert result["reason"] == "shaky_start"

    def test_shaky_end_trimmed(self):
        scores = [
            {"time_sec": 0.0, "sharp": True, "stable": True},
            {"time_sec": 0.5, "sharp": True, "stable": True},
            {"time_sec": 1.0, "sharp": True, "stable": True},
            {"time_sec": 1.5, "sharp": False, "stable": False},
            {"time_sec": 2.0, "sharp": False, "stable": False},
        ]
        result = _trim_window_from_scores(scores, duration=2.5, interval_sec=0.5)
        assert result["trim_in_sec"] == 0.0
        assert result["trim_out_sec"] == 1.5
        assert result["reason"] == "shaky_end"

    def test_clean_clip_no_trim(self):
        scores = [
            {"time_sec": 0.0, "sharp": True, "stable": True},
            {"time_sec": 0.5, "sharp": True, "stable": True},
            {"time_sec": 1.0, "sharp": True, "stable": True},
        ]
        result = _trim_window_from_scores(scores, duration=1.5, interval_sec=0.5)
        assert result["trim_in_sec"] == 0.0
        assert result["reason"] == "clean"

    def test_no_stable_frames(self):
        scores = [
            {"time_sec": 0.0, "sharp": False, "stable": False},
            {"time_sec": 0.5, "sharp": False, "stable": True},
        ]
        result = _trim_window_from_scores(scores, duration=1.0, interval_sec=0.5)
        assert result["reason"] == "no_stable_frames"


class TestSpeechTrim:
    def test_trims_to_speech_boundaries(self):
        transcript = {
            "segments": [
                {
                    "words": [
                        {"word": "hello", "start": 1.5, "end": 1.8},
                        {"word": "world", "start": 2.0, "end": 2.4},
                    ]
                },
                {
                    "words": [
                        {"word": "again", "start": 3.0, "end": 3.5},
                    ]
                },
            ]
        }
        result = speech_trim_from_transcript(transcript, clip_duration=5.0)
        # 1.5 - 0.5 pad = 1.0, 3.5 + 1.0 pad = 4.5
        assert result["trim_in_sec"] == 1.0
        assert result["trim_out_sec"] == 4.5
        assert result["reason"] == "speech_boundaries"

    def test_no_words_returns_none(self):
        assert speech_trim_from_transcript({"segments": []}, clip_duration=5.0) is None

    def test_none_transcript(self):
        assert speech_trim_from_transcript(None, clip_duration=5.0) is None


# ---------------------------------------------------------------------------
# Path mapping
# ---------------------------------------------------------------------------


class TestMapToOriginal:
    def test_swaps_proxy_dir_and_extension(self):
        from pathlib import Path

        result = map_to_original(Path("/wedding/02-proxies/card-A/CLIP0001_proxy.mp4"))
        assert "01-camera-originals" in result
        assert result.endswith("CLIP0001.MXF")

    def test_keeps_original_basename_when_no_proxy_suffix(self):
        from pathlib import Path

        result = map_to_original(Path("/wedding/02-proxies/CLIP0002.mp4"))
        assert result.endswith("CLIP0002.MXF")
