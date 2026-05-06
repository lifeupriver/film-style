# Contributing

Thanks for your interest. This project is small, opinionated, and aims to
stay that way — but PRs that fix bugs, expand test coverage, or add support
for new platforms are welcome.

## Setup

```bash
git clone https://github.com/lifeupriver/film-style.git
cd film-style
pip install -e '.[dev]' --break-system-packages
brew install ffmpeg
pytest
```

Optional extras for testing the heavier code paths:

```bash
pip install -e '.[music,vimeo,gemini,mcp]' --break-system-packages
```

`[audio]` (WhisperX + inaSpeechSegmenter) needs Python 3.11 or 3.12.

## Conventions

- **Tests required for behavior changes.** All new modules ship with at
  least one test file in `tests/`. Pure-function tests (no API calls, no
  ffmpeg) preferred. Real-media tests gated behind the `--real-media` opt-in.
- **No new top-level dependencies in core.** Heavy deps (torch, librosa,
  yt-dlp, mcp) live behind `[extras]` in `pyproject.toml`.
- **Schemas are versioned.** If you change `schemas.py` in a way that
  breaks the on-disk JSON format, bump `schema_version` in
  `profile_writer.py` and document the migration.
- **No PII in tests or docs.** Use generic placeholders (`a.mp4`,
  `demo-wedding`, `your-handle`).
- **Public-facing UI strings should be configurable.** Use `Config.brand_name`
  / `Config.editor_name` rather than hardcoding identities.

## Running tests

```bash
pytest -q                         # full suite
pytest tests/test_color_analysis.py -q   # one file
pytest -k matchmaker -q          # by name
pytest --real-media tests/fixtures/sample.mp4   # with real media
```

## Adding a new analyzer module

1. Implement the pure function in `src/film_style_analyzer/<name>.py`.
2. Add Pydantic schema fields in `schemas.py` if needed.
3. Wire into `analyzer.py` behind a `skip_<name>` flag (default True for
   anything heavy; default False for fast).
4. Surface in `aggregator.py` and `profile_writer.py` so the data reaches
   downstream consumers.
5. Tests in `tests/test_<name>.py`.
6. Document in README + ARCHITECTURE.

## Adding a new MCP tool

1. Implement `tool_<name>(...)` in `mcp_server.py` as a pure function.
2. Add a thin wrapper in `build_server()` decorated with `@mcp.tool()`.
3. Update the `EDIT_IN_STYLE_PROMPT` if the tool fits an existing workflow.
4. Test with `tests/test_mcp_*.py`.

## Code style

- Prefer dataclasses over dicts where the shape is stable.
- Type hints throughout. Pydantic models for anything serialized to JSON.
- Errors that the user might see should be domain-specific subclasses of
  `RuntimeError` (`MCPServerError`, `MusicAnalyzeError`, etc).
- No `print()` for user output — use `rich.console.Console` so colors
  degrade gracefully.

## Commit messages

Conventional-ish:

```
fix(scene_detect): swap AdaptiveDetector for ContentDetector for soft-cut content
feat(profile): add still_hold transition class
docs: clarify NotebookLM bridge in README
```

No need to follow a strict spec. Just: terse, present tense, scope-prefixed.

## Reporting bugs

Open an issue with:
1. The film's duration / resolution / codec (`ffprobe -show_streams ...`).
2. The exact CLI command that triggered the bug.
3. The error output if any.
4. What you expected to happen.

A 5-second clip that reproduces the bug — uploaded to a Gist or attached —
is worth a thousand words.
