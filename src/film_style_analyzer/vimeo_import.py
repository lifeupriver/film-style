"""Download videos via yt-dlp.

Despite the legacy module name, this works for any URL yt-dlp supports —
Vimeo, YouTube, Vimeo Showcase, YouTube playlists, channel URLs, etc.

We shell out to yt-dlp instead of using its Python API — keeps the dep
optional, lets users install the CLI tool however they like (pipx / brew),
and gives us cookie support out of the box (`--cookies-from-browser`).

Examples:
  - Vimeo single:     https://vimeo.com/123456789
  - Vimeo showcase:   https://vimeo.com/showcase/12345
  - Vimeo account:    https://vimeo.com/your-handle
  - YouTube single:   https://www.youtube.com/watch?v=...
  - YouTube playlist: https://www.youtube.com/playlist?list=PL...
  - YouTube channel:  https://www.youtube.com/@channelhandle
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Iterator


class VimeoImportError(RuntimeError):
    """Legacy name. Catch as VideoImportError everywhere new."""

    pass


# Forward-friendly alias.
VideoImportError = VimeoImportError


def _ensure_yt_dlp() -> str:
    exe = shutil.which("yt-dlp")
    if not exe:
        raise VimeoImportError(
            "yt-dlp not found. Install it: brew install yt-dlp  "
            "(or: pip install 'film-style-analyzer[vimeo]')"
        )
    return exe


def _build_command(
    yt_dlp: str,
    url: str,
    output_dir: Path,
    cookies_browser: str | None,
    quality: str,
    archive_path: Path | None,
) -> list[str]:
    template = str(output_dir / "%(title).200B [%(id)s].%(ext)s")
    cmd = [
        yt_dlp,
        "--no-playlist-reverse",
        "--ignore-errors",
        "--output",
        template,
        "--format",
        quality,
        "--write-info-json",
        "--no-overwrites",
    ]
    if cookies_browser:
        cmd += ["--cookies-from-browser", cookies_browser]
    if archive_path is not None:
        cmd += ["--download-archive", str(archive_path)]
    cmd.append(url)
    return cmd


def download(
    url: str,
    output_dir: Path,
    *,
    cookies_browser: str | None = None,
    quality: str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    archive: bool = True,
) -> Iterator[str]:
    """Download videos from a Vimeo URL. Yields stdout lines for live display.

    Args:
      url: Single video, showcase, or user URL.
      output_dir: Where MP4s land.
      cookies_browser: e.g. "safari" / "chrome" / "firefox" — needed for
                       private videos in your account.
      quality: yt-dlp -f format string.
      archive: maintain a download-archive file so re-runs are idempotent.
    """
    exe = _ensure_yt_dlp()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / ".yt-dlp-archive.txt" if archive else None

    cmd = _build_command(exe, url, output_dir, cookies_browser, quality, archive_path)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            yield line.rstrip()
    finally:
        proc.wait()
    if proc.returncode not in (0, 101):  # 101 = some failed but others ok
        raise VimeoImportError(
            f"yt-dlp exited with code {proc.returncode}. "
            "If the video is private, pass --cookies-browser=safari (or your browser)."
        )
