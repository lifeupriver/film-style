"""Per-frame composition analysis: faces, framing, headroom, lead room,
thirds, horizon tilt, exposure, sharpness, subject separation, motion blur.

Designed for 720p proxies. Uses MediaPipe (Face Detection, Face Mesh, Pose)
for subject detection and OpenCV for everything else. MediaPipe imports are
lazy so unit tests can exercise the pure-OpenCV detectors and the framing /
headroom logic with synthetic detection results.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MediaPipe lazy loaders
# ---------------------------------------------------------------------------

_mp_face_detection = None
_mp_face_mesh = None
_mp_pose = None
_mp_unavailable = False


def _load_mediapipe():
    """Return (face_detection_module, face_mesh_module, pose_module) or
    (None, None, None) if MediaPipe is unavailable."""
    global _mp_face_detection, _mp_face_mesh, _mp_pose, _mp_unavailable
    if _mp_unavailable:
        return None, None, None
    if _mp_face_detection is not None:
        return _mp_face_detection, _mp_face_mesh, _mp_pose
    try:
        from mediapipe import solutions
        _mp_face_detection = solutions.face_detection
        _mp_face_mesh = solutions.face_mesh
        _mp_pose = solutions.pose
    except (ImportError, AttributeError) as e:
        logger.info("MediaPipe solutions API not available: %s", e)
        _mp_unavailable = True
        return None, None, None
    return _mp_face_detection, _mp_face_mesh, _mp_pose


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FaceInfo:
    """Normalized face detection result. All bounds in [0, 1]."""
    bbox_x: float
    bbox_y: float
    bbox_w: float
    bbox_h: float
    confidence: float = 1.0
    keypoints: dict = field(default_factory=dict)
    # Optional Face Mesh landmarks (468 normalized 3D points) keyed by
    # canonical indices (e.g. "nose_tip", "left_eye", "right_eye").
    mesh: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Face detection (MediaPipe)
# ---------------------------------------------------------------------------

def detect_faces(image: np.ndarray) -> list[FaceInfo]:
    """Run MediaPipe Face Detection. Returns [] if unavailable."""
    fd, _, _ = _load_mediapipe()
    if fd is None:
        return []
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    out: list[FaceInfo] = []
    with fd.FaceDetection(model_selection=1, min_detection_confidence=0.5) as det:
        result = det.process(rgb)
        for d in (result.detections or []):
            box = d.location_data.relative_bounding_box
            kps = {}
            for kp in d.location_data.relative_keypoints:
                # MediaPipe keypoint indices: 0=right_eye, 1=left_eye,
                # 2=nose_tip, 3=mouth_center, 4=right_ear, 5=left_ear.
                kps[len(kps)] = (kp.x, kp.y)
            named = {
                "right_eye": kps.get(0),
                "left_eye": kps.get(1),
                "nose_tip": kps.get(2),
                "mouth_center": kps.get(3),
                "right_ear": kps.get(4),
                "left_ear": kps.get(5),
            }
            out.append(FaceInfo(
                bbox_x=max(0.0, box.xmin),
                bbox_y=max(0.0, box.ymin),
                bbox_w=box.width,
                bbox_h=box.height,
                confidence=float(d.score[0]) if d.score else 1.0,
                keypoints={k: v for k, v in named.items() if v is not None},
            ))
    return out


def detect_face_mesh(image: np.ndarray) -> dict | None:
    """Return a dict of canonical landmarks (nose_tip, left_eye, right_eye,
    chin, forehead) for the largest face, or None if no face found.
    All coordinates normalized to [0, 1]."""
    _, fm, _ = _load_mediapipe()
    if fm is None:
        return None
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    with fm.FaceMesh(static_image_mode=True, max_num_faces=1,
                     refine_landmarks=False, min_detection_confidence=0.5) as mesh:
        r = mesh.process(rgb)
        if not r.multi_face_landmarks:
            return None
        lm = r.multi_face_landmarks[0].landmark
        # Canonical MediaPipe Face Mesh indices.
        return {
            "nose_tip": (lm[1].x, lm[1].y),
            "left_eye": (lm[33].x, lm[33].y),
            "right_eye": (lm[263].x, lm[263].y),
            "chin": (lm[152].x, lm[152].y),
            "forehead": (lm[10].x, lm[10].y),
            "left_cheek": (lm[234].x, lm[234].y),
            "right_cheek": (lm[454].x, lm[454].y),
        }


def detect_pose(image: np.ndarray) -> dict | None:
    """Return a dict of canonical pose landmarks (shoulders, hips, knees,
    ankles, nose), or None if no pose found."""
    _, _, pose_mod = _load_mediapipe()
    if pose_mod is None:
        return None
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    with pose_mod.Pose(static_image_mode=True, model_complexity=1,
                       min_detection_confidence=0.5) as pose:
        r = pose.process(rgb)
        if not r.pose_landmarks:
            return None
        lm = r.pose_landmarks.landmark
        # MediaPipe Pose indices:
        # 0=nose, 11=left_shoulder, 12=right_shoulder,
        # 23=left_hip, 24=right_hip, 25=left_knee, 26=right_knee,
        # 27=left_ankle, 28=right_ankle.
        def pt(i):
            return (lm[i].x, lm[i].y, lm[i].visibility)
        return {
            "nose": pt(0),
            "left_shoulder": pt(11),
            "right_shoulder": pt(12),
            "left_hip": pt(23),
            "right_hip": pt(24),
            "left_knee": pt(25),
            "right_knee": pt(26),
            "left_ankle": pt(27),
            "right_ankle": pt(28),
        }


# ---------------------------------------------------------------------------
# Framing classification
# ---------------------------------------------------------------------------

def classify_framing(faces: list[FaceInfo], pose: dict | None,
                     image_shape: tuple[int, int]) -> str:
    """Body framing: extreme-close-up, close-up, medium-close, medium,
    medium-full, full, wide, no-person. Uses face size as the primary
    signal, refined by pose visibility for body parts."""
    if not faces and pose is None:
        return "no-person"

    if faces:
        primary = max(faces, key=lambda f: f.bbox_w * f.bbox_h)
        face_area_pct = primary.bbox_w * primary.bbox_h * 100
        # Coarse face-size mapping. These are calibrated against finished
        # wedding films at 720p where a "medium" shot puts the head at
        # ~7-9% of the frame area.
        if face_area_pct > 25:
            return "extreme-close-up"
        if face_area_pct > 12:
            return "close-up"
        if face_area_pct > 7:
            return "medium-close"
        if face_area_pct > 3:
            base = "medium"
        elif face_area_pct > 1.2:
            base = "medium-full"
        elif face_area_pct > 0.4:
            base = "full"
        else:
            base = "wide"
    else:
        base = "medium"

    # Refine using pose: if hips and knees are visible, it's at least
    # medium-full; if ankles too, it's full.
    if pose is not None:
        def vis(name):
            v = pose.get(name)
            return v is not None and v[2] > 0.5
        ankles = vis("left_ankle") or vis("right_ankle")
        knees = vis("left_knee") or vis("right_knee")
        hips = vis("left_hip") or vis("right_hip")
        shoulders = vis("left_shoulder") or vis("right_shoulder")
        if ankles and base in ("close-up", "medium-close", "medium",
                                "medium-full", "wide"):
            base = "full"
        elif knees and base in ("close-up", "medium-close", "medium", "wide"):
            base = "medium-full"
        elif hips and base in ("close-up", "medium-close", "wide"):
            base = "medium"
        elif shoulders and base == "extreme-close-up":
            base = "close-up"

    return base


def head_cut_off(faces: list[FaceInfo], face_mesh: dict | None) -> bool:
    """True if the top of the head is cropped out of frame."""
    if face_mesh:
        forehead = face_mesh.get("forehead")
        if forehead and forehead[1] < 0.03:
            return True
    if faces:
        primary = max(faces, key=lambda f: f.bbox_w * f.bbox_h)
        if primary.bbox_y < 0.01:
            return True
    return False


def primary_face_size_pct(faces: list[FaceInfo]) -> float:
    if not faces:
        return 0.0
    primary = max(faces, key=lambda f: f.bbox_w * f.bbox_h)
    return round(primary.bbox_w * primary.bbox_h * 100, 2)


def primary_face_center(faces: list[FaceInfo]) -> tuple[float, float] | None:
    if not faces:
        return None
    primary = max(faces, key=lambda f: f.bbox_w * f.bbox_h)
    return (
        primary.bbox_x + primary.bbox_w / 2,
        primary.bbox_y + primary.bbox_h / 2,
    )


def facing_camera(faces: list[FaceInfo], face_mesh: dict | None) -> bool:
    """Heuristic: subject faces camera if both eyes are detected and the
    nose lies roughly between them horizontally."""
    if face_mesh:
        le = face_mesh.get("left_eye")
        re = face_mesh.get("right_eye")
        nose = face_mesh.get("nose_tip")
        if le and re and nose:
            mid = (le[0] + re[0]) / 2
            spread = abs(le[0] - re[0])
            if spread < 1e-6:
                return False
            # Nose offset from eye-midline as fraction of eye spread:
            # near 0 = facing camera, > ~0.6 = profile.
            offset = abs(nose[0] - mid) / spread
            return offset < 0.4
    if faces:
        kps = faces[0].keypoints
        le = kps.get("left_eye")
        re = kps.get("right_eye")
        if le and re:
            return abs(le[0] - re[0]) > 0.02
    return False


# ---------------------------------------------------------------------------
# Headroom
# ---------------------------------------------------------------------------

def compute_headroom_pct(face_mesh: dict | None,
                         pose: dict | None,
                         faces: list[FaceInfo]) -> float | None:
    """Distance from top of head to top of frame, as % of frame height.
    Prefers the Face Mesh forehead landmark; falls back to the face bbox."""
    top_y = None
    if face_mesh and face_mesh.get("forehead"):
        top_y = face_mesh["forehead"][1]
    elif pose and pose.get("nose"):
        nose_y = pose["nose"][1]
        # Approximate forehead as ~5% of frame height above nose.
        top_y = max(0.0, nose_y - 0.05)
    elif faces:
        primary = max(faces, key=lambda f: f.bbox_w * f.bbox_h)
        top_y = primary.bbox_y
    if top_y is None:
        return None
    return round(max(0.0, top_y) * 100, 2)


# ---------------------------------------------------------------------------
# Lead room / looking room
# ---------------------------------------------------------------------------

def compute_lead_room(face_mesh: dict | None,
                      faces: list[FaceInfo]) -> dict:
    """Determine which direction the subject is looking and compare the
    space on the looking side vs. behind. Returns:
        {"looking_direction": "left"|"right"|None,
         "lead_room_ratio": float|None}
    A ratio > 1.0 means more space on the looking side (good lead room).
    """
    nose_x = eye_mid_x = face_x_center = None

    if face_mesh and face_mesh.get("nose_tip") and face_mesh.get("left_eye") \
            and face_mesh.get("right_eye"):
        le = face_mesh["left_eye"]
        re = face_mesh["right_eye"]
        nose_x = face_mesh["nose_tip"][0]
        eye_mid_x = (le[0] + re[0]) / 2
        face_x_center = eye_mid_x
    elif faces:
        primary = max(faces, key=lambda f: f.bbox_w * f.bbox_h)
        kps = primary.keypoints
        if kps.get("left_eye") and kps.get("right_eye") and kps.get("nose_tip"):
            nose_x = kps["nose_tip"][0]
            eye_mid_x = (kps["left_eye"][0] + kps["right_eye"][0]) / 2
            face_x_center = primary.bbox_x + primary.bbox_w / 2
        else:
            face_x_center = primary.bbox_x + primary.bbox_w / 2

    if nose_x is None or eye_mid_x is None or face_x_center is None:
        return {"looking_direction": None, "lead_room_ratio": None}

    direction = "left" if nose_x < eye_mid_x else "right"
    if direction == "left":
        lead_space = face_x_center
        back_space = 1.0 - face_x_center
    else:
        lead_space = 1.0 - face_x_center
        back_space = face_x_center

    if back_space < 1e-6:
        ratio = 99.0
    else:
        ratio = round(lead_space / back_space, 3)
    return {"looking_direction": direction, "lead_room_ratio": ratio}


# ---------------------------------------------------------------------------
# Rule of thirds
# ---------------------------------------------------------------------------

THIRDS_INTERSECTIONS = [
    (1 / 3, 1 / 3), (2 / 3, 1 / 3),
    (1 / 3, 2 / 3), (2 / 3, 2 / 3),
]


def thirds_score(face_center: tuple[float, float] | None) -> float:
    """Score 0-1 by proximity to the nearest thirds intersection.
    Maximum useful distance for a 16:9 frame is ~0.36 (corner to nearest
    intersection); we map 0->1.0 and 0.36->0.0."""
    if face_center is None:
        return 0.0
    fx, fy = face_center
    best = min(math.hypot(fx - ix, fy - iy) for ix, iy in THIRDS_INTERSECTIONS)
    score = max(0.0, 1.0 - best / 0.36)
    return round(score, 3)


# ---------------------------------------------------------------------------
# Horizon tilt (OpenCV Hough)
# ---------------------------------------------------------------------------

def detect_horizon_tilt(image: np.ndarray,
                        vote_threshold: int = 120,
                        min_line_length_frac: float = 0.25) -> dict:
    """Find the dominant near-horizontal architectural line and return
    its tilt in degrees from level. Returns:
        {"tilt_degrees": float|None,
         "lines_detected": bool,
         "line_count": int}
    Only considers lines within ±20° of horizontal so vertical posts
    don't poison the average."""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    edges = cv2.Canny(gray, 80, 200, apertureSize=3)
    min_len = int(w * min_line_length_frac)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 720,
        threshold=vote_threshold,
        minLineLength=min_len,
        maxLineGap=10,
    )
    if lines is None or len(lines) == 0:
        return {"tilt_degrees": None, "lines_detected": False, "line_count": 0}

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        # Normalize to [-90, 90]
        if angle > 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        if abs(angle) <= 20:
            angles.append(angle)

    if not angles:
        return {"tilt_degrees": None, "lines_detected": False, "line_count": 0}

    median_angle = float(np.median(angles))
    return {
        "tilt_degrees": round(median_angle, 2),
        "lines_detected": True,
        "line_count": len(angles),
    }


# ---------------------------------------------------------------------------
# Exposure (OpenCV histogram)
# ---------------------------------------------------------------------------

def analyze_exposure(image: np.ndarray) -> dict:
    """Mean brightness, shadow/midtone/highlight pcts, clipping, rating."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    mean = float(gray.mean()) / 255.0
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    total = max(1.0, hist.sum())
    shadow = float(hist[:64].sum() / total)
    midtone = float(hist[64:192].sum() / total)
    highlight = float(hist[192:].sum() / total)
    black_clip = float(hist[:3].sum() / total)
    white_clip = float(hist[253:].sum() / total)

    if mean < 0.12 or black_clip > 0.30:
        rating = "severely-underexposed"
    elif mean > 0.88 or white_clip > 0.30:
        rating = "severely-overexposed"
    elif mean < 0.25:
        rating = "underexposed"
    elif mean > 0.75:
        rating = "overexposed"
    elif 0.40 <= mean <= 0.65:
        rating = "good"
    else:
        rating = "acceptable"

    return {
        "mean_brightness": round(mean, 3),
        "shadow_pct": round(shadow * 100, 1),
        "midtone_pct": round(midtone * 100, 1),
        "highlight_pct": round(highlight * 100, 1),
        "black_clip_pct": round(black_clip * 100, 2),
        "white_clip_pct": round(white_clip * 100, 2),
        "exposure_rating": rating,
    }


# ---------------------------------------------------------------------------
# Backlit subject detection
# ---------------------------------------------------------------------------

def detect_backlit(image: np.ndarray,
                   faces: list[FaceInfo],
                   threshold: float = 0.40) -> bool:
    """True when the face region is significantly darker than the surrounding
    background. `threshold` is the fractional drop in mean brightness;
    0.40 means face is 40%+ darker than the rest of the frame."""
    if not faces:
        return False
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    primary = max(faces, key=lambda f: f.bbox_w * f.bbox_h)
    x0 = int(primary.bbox_x * w)
    y0 = int(primary.bbox_y * h)
    x1 = int(min(w, (primary.bbox_x + primary.bbox_w) * w))
    y1 = int(min(h, (primary.bbox_y + primary.bbox_h) * h))
    if x1 <= x0 or y1 <= y0:
        return False
    face_region = gray[y0:y1, x0:x1]
    if face_region.size == 0:
        return False
    face_mean = float(face_region.mean())
    # Background = whole frame minus the face box.
    mask = np.ones_like(gray, dtype=bool)
    mask[y0:y1, x0:x1] = False
    bg_pixels = gray[mask]
    if bg_pixels.size == 0:
        return False
    bg_mean = float(bg_pixels.mean())
    if bg_mean < 1.0:
        return False
    return (bg_mean - face_mean) / bg_mean > threshold


# ---------------------------------------------------------------------------
# Sharpness / focus (Laplacian variance)
# ---------------------------------------------------------------------------

# Calibrated for 720p proxies.
SHARPNESS_THRESHOLDS = {
    "very_soft": 20,
    "soft": 50,
    "acceptable": 100,
}


def laplacian_variance(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def rate_sharpness(variance: float) -> str:
    if variance < SHARPNESS_THRESHOLDS["very_soft"]:
        return "very-soft"
    if variance < SHARPNESS_THRESHOLDS["soft"]:
        return "soft"
    if variance < SHARPNESS_THRESHOLDS["acceptable"]:
        return "acceptable"
    return "sharp"


# ---------------------------------------------------------------------------
# Subject separation / depth of field
# ---------------------------------------------------------------------------

def compute_subject_separation(image: np.ndarray) -> float:
    """Ratio of center-region sharpness to edge sharpness. Higher = more
    bokeh / shallower DOF. The center is the inner 40% of the frame; edges
    are the outermost 30% on each horizontal side."""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    cx0, cx1 = int(w * 0.30), int(w * 0.70)
    cy0, cy1 = int(h * 0.30), int(h * 0.70)
    center = gray[cy0:cy1, cx0:cx1]
    left_edge = gray[:, : int(w * 0.30)]
    right_edge = gray[:, int(w * 0.70):]
    if center.size == 0:
        return 1.0
    center_var = float(cv2.Laplacian(center, cv2.CV_64F).var())
    edge_var = float(
        (cv2.Laplacian(left_edge, cv2.CV_64F).var()
         + cv2.Laplacian(right_edge, cv2.CV_64F).var()) / 2
    )
    if edge_var < 1e-3:
        return 99.0
    return round(center_var / edge_var, 2)


# ---------------------------------------------------------------------------
# Motion blur on subject
# ---------------------------------------------------------------------------

def detect_motion_blur_subject(image: np.ndarray,
                               faces: list[FaceInfo],
                               soft_factor: float = 0.5) -> bool:
    """True if the face region is much softer than the background. Indicates
    the subject moved during exposure even though the camera was steady."""
    if not faces:
        return False
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    primary = max(faces, key=lambda f: f.bbox_w * f.bbox_h)
    x0 = int(primary.bbox_x * w)
    y0 = int(primary.bbox_y * h)
    x1 = int(min(w, (primary.bbox_x + primary.bbox_w) * w))
    y1 = int(min(h, (primary.bbox_y + primary.bbox_h) * h))
    if x1 <= x0 or y1 <= y0:
        return False
    face_region = gray[y0:y1, x0:x1]
    if face_region.size == 0:
        return False
    mask = np.ones_like(gray, dtype=bool)
    mask[y0:y1, x0:x1] = False
    bg_pixels = gray[mask]
    if bg_pixels.size == 0:
        return False
    bg_for_lap = gray.copy()
    bg_for_lap[y0:y1, x0:x1] = int(bg_pixels.mean())
    face_var = float(cv2.Laplacian(face_region, cv2.CV_64F).var())
    bg_var = float(cv2.Laplacian(bg_for_lap, cv2.CV_64F).var())
    if bg_var < 5.0:
        return False
    return face_var < bg_var * soft_factor


# ---------------------------------------------------------------------------
# Camera stability (optical flow between consecutive frames)
# ---------------------------------------------------------------------------

def motion_magnitude(prev_frame: np.ndarray | None,
                     curr_frame: np.ndarray) -> float:
    """Average pixel motion between consecutive frames via Farneback
    optical flow. 0 if no previous frame given."""
    if prev_frame is None:
        return 0.0
    g_prev = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY) if prev_frame.ndim == 3 else prev_frame
    g_curr = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY) if curr_frame.ndim == 3 else curr_frame
    if g_prev.shape != g_curr.shape:
        g_prev = cv2.resize(g_prev, (g_curr.shape[1], g_curr.shape[0]))
    flow = cv2.calcOpticalFlowFarneback(
        g_prev, g_curr, None, 0.5, 3, 15, 3, 5, 1.2, 0,
    )
    mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
    return round(float(mag.mean()), 3)


# ---------------------------------------------------------------------------
# Top-level: analyze a single frame
# ---------------------------------------------------------------------------

def analyze_frame(frame: np.ndarray | Path | str) -> dict:
    """Run every composition detector on a single frame. Accepts either a
    numpy BGR image or a path to a JPEG/PNG. Returns one flat dict.

    Skips face/framing/headroom/lead-room/backlit/motion-blur detectors when
    no person is found — these are nonsense for sunset and detail shots."""
    if isinstance(frame, (str, Path)):
        image = cv2.imread(str(frame))
        if image is None:
            return {"error": f"could not read {frame}"}
    else:
        image = frame

    faces = detect_faces(image)
    pose = detect_pose(image) if faces else None
    mesh = detect_face_mesh(image) if faces else None
    has_person = bool(faces) or pose is not None

    framing = classify_framing(faces, pose, image.shape[:2])
    face_size = primary_face_size_pct(faces)
    face_center = primary_face_center(faces)
    facing = facing_camera(faces, mesh) if has_person else False
    cutoff = head_cut_off(faces, mesh) if has_person else False
    headroom = compute_headroom_pct(mesh, pose, faces) if has_person else None
    lead = compute_lead_room(mesh, faces) if has_person else \
        {"looking_direction": None, "lead_room_ratio": None}
    thirds = thirds_score(face_center) if face_center else 0.0

    horizon = detect_horizon_tilt(image)
    exposure = analyze_exposure(image)
    lap_var = laplacian_variance(image)
    focus_rating = rate_sharpness(lap_var)
    separation = compute_subject_separation(image)
    backlit = detect_backlit(image, faces) if faces else False
    motion_blur_subj = detect_motion_blur_subject(image, faces) if faces else False

    return {
        # People / framing
        "has_person": has_person,
        "faces_detected": len(faces),
        "framing": framing,
        "face_size_pct": face_size,
        "face_center_x": round(face_center[0], 3) if face_center else None,
        "face_center_y": round(face_center[1], 3) if face_center else None,
        "facing_camera": facing,
        "head_cutoff": cutoff,
        "headroom_pct": headroom,
        "looking_direction": lead["looking_direction"],
        "lead_room_ratio": lead["lead_room_ratio"],
        "thirds_score": thirds,
        # Frame-level
        "horizon_tilt_degrees": horizon["tilt_degrees"],
        "horizon_lines_detected": horizon["lines_detected"],
        **exposure,
        "backlit": backlit,
        "laplacian_variance": round(lap_var, 2),
        "focus_rating": focus_rating,
        "subject_separation_ratio": separation,
        "motion_blur_on_subject": motion_blur_subj,
    }
