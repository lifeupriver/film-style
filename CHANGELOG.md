# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once it leaves 0.x.

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-07-08

Initial public release.

`film-style` analyzes finished films across genres (wedding, commercial,
brand content, social shorts, music videos, documentary) and generates
per-genre editing style guides from a scene-detected, dissolve-classified,
optionally audio- and shot-aware pipeline, plus a static local dashboard
for browsing results.

### Fixed (pre-release hardening)

- **Security**: the dashboard's local HTTP server now defends against
  cross-origin mutating requests (Origin/Referer checks), requires a JSON
  `Content-Type` on JSON POST bodies, refuses to bind to non-loopback
  addresses without an explicit opt-in, and validates genre-pack names so
  they can't be used for path traversal.
- **Security**: Vimeo/yt-dlp imports reject URLs that don't start with
  `http://`/`https://` and always pass the URL after a `--` separator,
  closing an argument-injection path from MCP tool input into the
  underlying `yt-dlp` command.
- **FCPXML parsing**: nested clip containers (e.g. `sync-clip`/`clip`
  wrapping `asset-clip`s) no longer double-count duration, and clips are no
  longer misclassified as audio just because FCP stamped an ordinary
  A/V clip with `audioRole="dialogue"`.
- **Tempo detection**: beat-tracking no longer crashes converting the
  tempo estimate to `float` under numpy 2.x, where `librosa` returns it as
  a shape-`(1,)` array instead of a scalar.
- **Thumbnails/clip paths**: dashboard clip and thumbnail path resolution
  handles real-world film filenames correctly instead of assuming a
  narrow naming convention.
- **Dashboard**: the transition-mix chart and legend now include
  `still_hold` alongside hard cut / dissolve / fade, so the dominant
  transition class in the default wedding genre pack is no longer silently
  omitted.

### Changed (packaging)

- Replaced the `scenedetect[opencv]` extra (no longer published as of
  scenedetect 0.7) with `scenedetect>=0.7` plus an explicit
  `opencv-python>=4.8` dependency.
- Switched `license` metadata to the modern SPDX string form (`license =
  "MIT"`) and dropped the now-redundant classifier.
- Added a `[project.urls]` table pointing at the project's GitHub repo.
- Added a GitHub Actions CI workflow that installs `.[dev]` and runs the
  base test suite (no optional heavy extras) on Python 3.11 and 3.12.

### Docs

- Replaced `pip install --break-system-packages` guidance in the README
  and CONTRIBUTING with standard virtual-environment install instructions.
- Scrubbed personal/client references from the docs in favor of neutral
  placeholders.

[Unreleased]: https://github.com/lifeupriver/film-style/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lifeupriver/film-style/releases/tag/v0.1.0
