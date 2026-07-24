"""Composition detectors — tested with synthetic frames so MediaPipe isn't
required. The face/framing tests build FaceInfo objects directly; the
OpenCV-based detectors (exposure, sharpness, separation, tilt, motion)
operate on numpy arrays."""

import cv2
import numpy as np
import pytest

from film_style_analyzer.composition import (
    FaceInfo,
    analyze_exposure,
    classify_framing,
    compute_headroom_pct,
    compute_lead_room,
    compute_subject_separation,
    detect_backlit,
    detect_horizon_tilt,
    detect_motion_blur_subject,
    facing_camera,
    head_cut_off,
    laplacian_variance,
    motion_magnitude,
    primary_face_center,
    primary_face_size_pct,
    rate_sharpness,
    thirds_score,
)


def _gray_frame(intensity: int = 128, size=(720, 1280, 3)) -> np.ndarray:
    return np.full(size, intensity, dtype=np.uint8)


def _face(x, y, w, h, **kw) -> FaceInfo:
    return FaceInfo(bbox_x=x, bbox_y=y, bbox_w=w, bbox_h=h, **kw)


# ---------------------------------------------------------------------------
# Framing classification
# ---------------------------------------------------------------------------


class TestFraming:
    def test_no_person(self):
        assert classify_framing([], None, (720, 1280)) == "no-person"

    def test_extreme_close_up_huge_face(self):
        # Face occupies 40% of frame.
        face = _face(0.3, 0.2, 0.5, 0.8)
        assert classify_framing([face], None, (720, 1280)) == "extreme-close-up"

    def test_close_up(self):
        # 16% of frame area
        face = _face(0.3, 0.2, 0.4, 0.4)
        assert classify_framing([face], None, (720, 1280)) == "close-up"

    def test_medium(self):
        # ~5% of frame area
        face = _face(0.4, 0.3, 0.22, 0.22)
        assert classify_framing([face], None, (720, 1280)) == "medium"

    def test_full_body_via_pose(self):
        # Tiny face but ankles visible -> full
        face = _face(0.45, 0.05, 0.05, 0.05)
        pose = {
            "left_shoulder": (0.4, 0.2, 0.9),
            "right_shoulder": (0.5, 0.2, 0.9),
            "left_hip": (0.4, 0.5, 0.9),
            "right_hip": (0.5, 0.5, 0.9),
            "left_knee": (0.4, 0.7, 0.9),
            "right_knee": (0.5, 0.7, 0.9),
            "left_ankle": (0.4, 0.95, 0.9),
            "right_ankle": (0.5, 0.95, 0.9),
        }
        assert classify_framing([face], pose, (720, 1280)) == "full"

    def test_largest_face_used_when_multiple(self):
        small = _face(0.0, 0.0, 0.05, 0.05)
        large = _face(0.3, 0.3, 0.4, 0.4)
        assert classify_framing([small, large], None, (720, 1280)) == "close-up"


# ---------------------------------------------------------------------------
# Headroom
# ---------------------------------------------------------------------------


class TestHeadroom:
    def test_too_close_to_top(self):
        mesh = {"forehead": (0.5, 0.02)}
        assert compute_headroom_pct(mesh, None, []) < 5

    def test_centered_subject_good_headroom(self):
        mesh = {"forehead": (0.5, 0.10)}
        assert 8 <= compute_headroom_pct(mesh, None, []) <= 15

    def test_too_much_headroom(self):
        mesh = {"forehead": (0.5, 0.30)}
        assert compute_headroom_pct(mesh, None, []) > 25

    def test_falls_back_to_face_bbox(self):
        face = _face(0.4, 0.10, 0.2, 0.2)
        assert compute_headroom_pct(None, None, [face]) == pytest.approx(10.0, abs=0.1)

    def test_returns_none_when_nothing(self):
        assert compute_headroom_pct(None, None, []) is None


# ---------------------------------------------------------------------------
# Lead room
# ---------------------------------------------------------------------------


class TestLeadRoom:
    def test_facing_left_with_space_on_left_is_good(self):
        # Subject on the right side of frame, looking left (nose left of eye-mid).
        mesh = {
            "nose_tip": (0.66, 0.5),
            "left_eye": (0.70, 0.5),
            "right_eye": (0.74, 0.5),
        }
        result = compute_lead_room(mesh, [])
        assert result["looking_direction"] == "left"
        assert result["lead_room_ratio"] > 1.5

    def test_facing_left_with_space_on_right_is_bad(self):
        # Subject on the LEFT side, but looking left -> almost no space.
        mesh = {
            "nose_tip": (0.18, 0.5),
            "left_eye": (0.22, 0.5),
            "right_eye": (0.26, 0.5),
        }
        result = compute_lead_room(mesh, [])
        assert result["looking_direction"] == "left"
        assert result["lead_room_ratio"] < 1.0

    def test_facing_right_with_space_on_right_is_good(self):
        mesh = {
            "nose_tip": (0.30, 0.5),
            "left_eye": (0.22, 0.5),
            "right_eye": (0.26, 0.5),
        }
        result = compute_lead_room(mesh, [])
        assert result["looking_direction"] == "right"
        assert result["lead_room_ratio"] > 1.5

    def test_returns_none_when_no_face(self):
        result = compute_lead_room(None, [])
        assert result["looking_direction"] is None
        assert result["lead_room_ratio"] is None


# ---------------------------------------------------------------------------
# Rule of thirds
# ---------------------------------------------------------------------------


class TestThirds:
    def test_at_intersection_scores_high(self):
        score = thirds_score((1 / 3, 1 / 3))
        assert score == 1.0

    def test_dead_center_scores_low(self):
        score = thirds_score((0.5, 0.5))
        assert score < 0.5

    def test_corner_scores_zero(self):
        score = thirds_score((0.0, 0.0))
        assert score < 0.1

    def test_none_face_center(self):
        assert thirds_score(None) == 0.0


# ---------------------------------------------------------------------------
# Horizon tilt
# ---------------------------------------------------------------------------


class TestHorizonTilt:
    def test_perfectly_horizontal(self):
        img = np.full((720, 1280, 3), 200, dtype=np.uint8)
        cv2.line(img, (50, 360), (1230, 360), (0, 0, 0), 3)
        result = detect_horizon_tilt(img)
        assert result["lines_detected"] is True
        assert abs(result["tilt_degrees"]) < 1.0

    def test_tilted_5_degrees(self):
        img = np.full((720, 1280, 3), 200, dtype=np.uint8)
        # Draw a line tilted ~5 degrees down.
        x1, y1 = 50, 300
        x2, y2 = 1230, 300 + int((1230 - 50) * np.tan(np.deg2rad(5)))
        cv2.line(img, (x1, y1), (x2, y2), (0, 0, 0), 3)
        result = detect_horizon_tilt(img)
        assert result["lines_detected"] is True
        assert 3.5 <= abs(result["tilt_degrees"]) <= 6.5

    def test_no_lines(self):
        img = np.full((720, 1280, 3), 128, dtype=np.uint8)
        result = detect_horizon_tilt(img)
        assert result["lines_detected"] is False
        assert result["tilt_degrees"] is None


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------


class TestExposure:
    def test_severely_underexposed(self):
        img = _gray_frame(10)
        r = analyze_exposure(img)
        assert r["exposure_rating"] == "severely-underexposed"
        assert r["mean_brightness"] < 0.12

    def test_severely_overexposed(self):
        img = _gray_frame(245)
        r = analyze_exposure(img)
        assert r["exposure_rating"] == "severely-overexposed"

    def test_underexposed(self):
        img = _gray_frame(50)
        r = analyze_exposure(img)
        assert r["exposure_rating"] == "underexposed"

    def test_good_exposure(self):
        img = _gray_frame(128)
        r = analyze_exposure(img)
        assert r["exposure_rating"] in ("good", "acceptable")

    def test_overexposed(self):
        img = _gray_frame(210)
        r = analyze_exposure(img)
        assert r["exposure_rating"] in ("overexposed", "severely-overexposed")


# ---------------------------------------------------------------------------
# Backlit detection
# ---------------------------------------------------------------------------


class TestBacklit:
    def test_dark_face_bright_background(self):
        # Bright background, dark face region in center.
        img = np.full((720, 1280, 3), 220, dtype=np.uint8)
        cv2.rectangle(img, (560, 280), (720, 440), (30, 30, 30), -1)
        face = _face(560 / 1280, 280 / 720, (720 - 560) / 1280, (440 - 280) / 720)
        assert detect_backlit(img, [face]) is True

    def test_face_brighter_than_bg(self):
        img = np.full((720, 1280, 3), 60, dtype=np.uint8)
        cv2.rectangle(img, (560, 280), (720, 440), (200, 200, 200), -1)
        face = _face(560 / 1280, 280 / 720, (720 - 560) / 1280, (440 - 280) / 720)
        assert detect_backlit(img, [face]) is False

    def test_no_face(self):
        img = _gray_frame(128)
        assert detect_backlit(img, []) is False


# ---------------------------------------------------------------------------
# Sharpness
# ---------------------------------------------------------------------------


class TestSharpness:
    def test_blurred_image_low_variance(self):
        img = np.full((720, 1280, 3), 128, dtype=np.uint8)
        # Add some structure then blur it to mush.
        cv2.rectangle(img, (100, 100), (400, 400), (200, 200, 200), -1)
        blurred = cv2.GaussianBlur(img, (51, 51), 30)
        v = laplacian_variance(blurred)
        assert v < 50

    def test_sharp_image_high_variance(self):
        img = np.full((720, 1280, 3), 128, dtype=np.uint8)
        # Many sharp edges -> high Laplacian variance.
        for i in range(0, 1280, 30):
            cv2.line(img, (i, 0), (i, 720), (0, 0, 0), 2)
        v = laplacian_variance(img)
        assert v > 100

    def test_rate_sharpness_thresholds(self):
        assert rate_sharpness(5) == "very-soft"
        assert rate_sharpness(30) == "soft"
        assert rate_sharpness(75) == "acceptable"
        assert rate_sharpness(200) == "sharp"


# ---------------------------------------------------------------------------
# Subject separation
# ---------------------------------------------------------------------------


class TestSubjectSeparation:
    def test_sharp_center_blurred_edges_high_ratio(self):
        # Build a frame with sharp content in the middle, blurred on the edges.
        img = np.full((720, 1280, 3), 128, dtype=np.uint8)
        # Sharp center: high-frequency lines in the middle 40%.
        cx0, cx1 = int(1280 * 0.30), int(1280 * 0.70)
        for x in range(cx0, cx1, 8):
            cv2.line(img, (x, 100), (x, 620), (0, 0, 0), 1)
        # Blur the edges.
        left = cv2.GaussianBlur(img[:, :cx0], (31, 31), 12)
        right = cv2.GaussianBlur(img[:, cx1:], (31, 31), 12)
        img[:, :cx0] = left
        img[:, cx1:] = right
        ratio = compute_subject_separation(img)
        assert ratio > 2.0

    def test_uniform_sharpness_ratio_near_one(self):
        img = np.full((720, 1280, 3), 128, dtype=np.uint8)
        for x in range(0, 1280, 8):
            cv2.line(img, (x, 0), (x, 720), (0, 0, 0), 1)
        ratio = compute_subject_separation(img)
        assert 0.5 <= ratio <= 1.8


# ---------------------------------------------------------------------------
# Motion blur on subject
# ---------------------------------------------------------------------------


class TestMotionBlurSubject:
    def test_blurry_face_sharp_background(self):
        img = np.full((720, 1280, 3), 128, dtype=np.uint8)
        # Sharp background pattern.
        for x in range(0, 1280, 6):
            cv2.line(img, (x, 0), (x, 720), (0, 0, 0), 1)
        # Now blur out a face region.
        x0, y0, x1, y1 = 540, 260, 740, 460
        face_region = cv2.GaussianBlur(img[y0:y1, x0:x1], (51, 51), 30)
        img[y0:y1, x0:x1] = face_region
        face = _face(x0 / 1280, y0 / 720, (x1 - x0) / 1280, (y1 - y0) / 720)
        assert detect_motion_blur_subject(img, [face]) is True

    def test_no_face_returns_false(self):
        assert detect_motion_blur_subject(_gray_frame(), []) is False


# ---------------------------------------------------------------------------
# Camera stability
# ---------------------------------------------------------------------------


class TestMotionMagnitude:
    def test_identical_frames_zero_motion(self):
        img = _gray_frame(128)
        # Add some structure so optical flow has something to track.
        cv2.rectangle(img, (200, 200), (400, 400), (50, 50, 50), -1)
        m = motion_magnitude(img, img.copy())
        assert m == pytest.approx(0.0, abs=0.5)

    def test_no_prev_frame_zero_motion(self):
        assert motion_magnitude(None, _gray_frame()) == 0.0

    def test_shifted_frame_has_motion(self):
        img1 = np.full((360, 640, 3), 128, dtype=np.uint8)
        cv2.rectangle(img1, (100, 100), (300, 300), (220, 220, 220), -1)
        img2 = np.full((360, 640, 3), 128, dtype=np.uint8)
        cv2.rectangle(img2, (140, 100), (340, 300), (220, 220, 220), -1)  # shift 40px
        m = motion_magnitude(img1, img2)
        assert m > 1.0


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_primary_face_center(self):
        small = _face(0.0, 0.0, 0.1, 0.1)
        large = _face(0.4, 0.4, 0.2, 0.2)
        c = primary_face_center([small, large])
        assert c == (0.5, 0.5)

    def test_primary_face_size_pct(self):
        face = _face(0.3, 0.3, 0.2, 0.4)  # 8% of area
        assert primary_face_size_pct([face]) == pytest.approx(8.0, abs=0.1)

    def test_head_cut_off_when_forehead_at_top(self):
        mesh = {"forehead": (0.5, 0.01)}
        assert head_cut_off([], mesh) is True

    def test_head_not_cut_off(self):
        mesh = {"forehead": (0.5, 0.10)}
        assert head_cut_off([], mesh) is False

    def test_facing_camera_with_eyes_and_centered_nose(self):
        mesh = {
            "nose_tip": (0.5, 0.5),
            "left_eye": (0.45, 0.48),
            "right_eye": (0.55, 0.48),
        }
        assert facing_camera([], mesh) is True

    def test_not_facing_camera_profile_view(self):
        mesh = {
            "nose_tip": (0.40, 0.5),
            "left_eye": (0.46, 0.48),
            "right_eye": (0.50, 0.48),
        }
        assert facing_camera([], mesh) is False
