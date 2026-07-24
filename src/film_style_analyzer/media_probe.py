"""ffprobe wrapper for media metadata."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .schemas import FilmMeta


class ProbeError(RuntimeError):
    pass


def probe(path: Path) -> FilmMeta:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.PIPE)
    except FileNotFoundError as e:
        raise ProbeError("ffprobe not found — install ffmpeg (brew install ffmpeg)") from e
    except subprocess.CalledProcessError as e:
        raise ProbeError(f"ffprobe failed for {path}: {e.stderr.decode(errors='ignore')}") from e

    data = json.loads(out)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ProbeError(f"no video stream in {path}")

    fr_num, fr_den = (video.get("r_frame_rate") or "0/1").split("/")
    frame_rate = float(fr_num) / float(fr_den) if float(fr_den) else 0.0

    duration = float(data["format"].get("duration", 0.0))
    width = video.get("width", 0)
    height = video.get("height", 0)

    return FilmMeta(
        filename=path.name,
        path=str(path),
        duration_sec=duration,
        resolution=f"{width}x{height}",
        frame_rate=frame_rate,
        codec=video.get("codec_name", "unknown"),
    )
