"""Extract thumbnails at clip start times via ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .schemas import Clip


def extract(film_path: Path, clips: list[Clip], out_dir: Path, quality: int = 2) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for clip in clips:
        out = out_dir / f"clip_{clip.index:03d}.jpg"
        # Seek slightly into the clip to avoid pre-cut frames.
        ts = clip.start_sec + min(0.1, clip.duration_sec / 2)
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{ts:.3f}",
            "-i", str(film_path),
            "-vframes", "1",
            "-q:v", str(quality),
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
            # Stored relative to data root (one level above thumbs_root) so
            # the path includes the "thumbs/" prefix and resolves cleanly via
            # `DATA_ROOT / clip.thumbnail`.
            clip.thumbnail = str(out.relative_to(out_dir.parent.parent))
        except subprocess.CalledProcessError:
            clip.thumbnail = None
        except ValueError:
            # Falls through if out is not under a 2-level ancestor; store as-is.
            clip.thumbnail = str(out)
