"""Shot profile aggregation — synthetic frame inputs, no MediaPipe."""

from film_style_analyzer.shot_profile import aggregate_frames, learn_from_thumbnails


def _frame(
    framing="medium",
    faces=1,
    face_size=8.0,
    face_x=0.33,
    face_y=0.4,
    headroom=10.0,
    thirds=0.7,
    brightness=0.5,
    lap=150.0,
    sep=2.5,
    exposure="good",
    focus="sharp",
    head_cutoff=False,
    facing=True,
    dominant_emotion="happy",
    emotion_score=45.0,
):
    return {
        "framing": framing,
        "faces_detected": faces,
        "face_size_pct": face_size,
        "face_center_x": face_x,
        "face_center_y": face_y,
        "facing_camera": facing,
        "head_cutoff": head_cutoff,
        "headroom_pct": headroom,
        "thirds_score": thirds,
        "lead_room_ratio": 1.5,
        "horizon_tilt_degrees": 0.5,
        "horizon_lines_detected": True,
        "mean_brightness": brightness,
        "exposure_rating": exposure,
        "laplacian_variance": lap,
        "focus_rating": focus,
        "subject_separation_ratio": sep,
        "backlit": False,
        "motion_blur_on_subject": False,
        "emotion": {
            "faces_analyzed": faces,
            "dominant_emotion": dominant_emotion,
            "wedding_emotion_score": emotion_score,
        },
    }


class TestAggregate:
    def test_empty_frames(self):
        result = aggregate_frames([])
        assert result["total_frames_analyzed"] == 0

    def test_preferred_framing_is_most_common(self):
        frames = [_frame(framing="medium")] * 3 + [_frame(framing="close-up")]
        result = aggregate_frames(frames)
        assert result["preferred_framing"] == "medium"
        assert result["framing_distribution"]["medium"] == 0.75

    def test_face_presence_pct(self):
        frames = [_frame(faces=1)] * 7 + [_frame(faces=0)] * 3
        result = aggregate_frames(frames)
        assert result["face_presence"]["frames_with_faces_pct"] == 70.0

    def test_emotion_above_thresholds(self):
        frames = [
            _frame(emotion_score=15.0),
            _frame(emotion_score=25.0),
            _frame(emotion_score=45.0),
            _frame(emotion_score=65.0),
        ]
        result = aggregate_frames(frames)
        ep = result["emotion_preferences"]
        assert ep["pct_frames_with_emotion_above_20"] == 75.0
        assert ep["pct_frames_with_emotion_above_40"] == 50.0

    def test_rejection_rules_record_pcts(self):
        frames = [_frame()] * 8 + [_frame(head_cutoff=True)] * 2
        result = aggregate_frames(frames)
        assert result["rejection_rules_learned"]["head_cutoff_pct"] == 20.0

    def test_avg_brightness_in_range(self):
        frames = [_frame(brightness=0.30), _frame(brightness=0.50), _frame(brightness=0.70)]
        result = aggregate_frames(frames)
        assert 0.45 <= result["exposure"]["avg_brightness"] <= 0.55

    def test_emotion_distribution(self):
        frames = (
            [_frame(dominant_emotion="happy")] * 5
            + [_frame(dominant_emotion="surprise")] * 3
            + [_frame(dominant_emotion="neutral")] * 2
        )
        result = aggregate_frames(frames)
        dist = result["emotion_preferences"]["dominant_emotions_distribution"]
        assert dist["happy"] == 0.5
        assert dist["surprise"] == 0.3
        assert dist["neutral"] == 0.2


class TestLearnFromThumbnails:
    def test_walks_thumbnails_directory(self, tmp_path):
        # Build fake thumbnails layout: thumbs_root/film1/clip_001.jpg, ...
        film1 = tmp_path / "film1"
        film2 = tmp_path / "film2"
        film1.mkdir()
        film2.mkdir()
        (film1 / "clip_001.jpg").write_bytes(b"fake")
        (film1 / "clip_002.jpg").write_bytes(b"fake")
        (film2 / "clip_001.jpg").write_bytes(b"fake")

        def fake_frame(p):
            return _frame()

        def fake_emotion(p):
            return {"dominant_emotion": "happy", "wedding_emotion_score": 50, "faces_analyzed": 1}

        result = learn_from_thumbnails(
            tmp_path,
            analyze_frame_fn=fake_frame,
            analyze_emotion_fn=fake_emotion,
        )
        assert result["films_analyzed"] == 2
        assert result["total_frames_analyzed"] == 3
        assert result["preferred_framing"] == "medium"

    def test_films_filter(self, tmp_path):
        (tmp_path / "film1").mkdir()
        (tmp_path / "film2").mkdir()
        (tmp_path / "film1" / "a.jpg").write_bytes(b"x")
        (tmp_path / "film2" / "a.jpg").write_bytes(b"x")
        (tmp_path / "film2" / "b.jpg").write_bytes(b"x")

        result = learn_from_thumbnails(
            tmp_path,
            films=["film2"],
            analyze_frame_fn=lambda p: _frame(),
            analyze_emotion_fn=lambda p: {
                "faces_analyzed": 0,
                "wedding_emotion_score": 0,
                "dominant_emotion": "none",
            },
        )
        assert result["films_analyzed"] == 1
        assert result["total_frames_analyzed"] == 2

    def test_missing_thumbs_dir_raises(self, tmp_path):
        import pytest

        with pytest.raises(FileNotFoundError):
            learn_from_thumbnails(tmp_path / "does_not_exist")
