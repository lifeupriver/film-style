"""ffmpeg audio extraction to 16kHz mono WAV (format required by WhisperX + inaSpeechSegmenter)."""

from __future__ import annotations

import subprocess
from pathlib import Path


class AudioExtractError(RuntimeError):
    pass


def extract_wav(film_path: Path, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(film_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, stderr=subprocess.PIPE)
    except FileNotFoundError as e:
        raise AudioExtractError("ffmpeg not found — install ffmpeg (brew install ffmpeg)") from e
    except subprocess.CalledProcessError as e:
        raise AudioExtractError(f"ffmpeg failed: {e.stderr.decode(errors='ignore')}") from e
    return out_path
