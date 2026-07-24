# AGENTS.md

## Cursor Cloud specific instructions

`film-style-analyzer` is a **pure-Python CLI** (`film-style`, defined in
`pyproject.toml` `[project.scripts]`) plus a stdlib-only local dashboard. There
is no compiled build step and no separate frontend toolchain. Python 3.12 and
`ffmpeg` are already present on the VM. The startup update script installs the
package editable with dev + light extras, so you normally don't need to
reinstall.

### Services / entry points
- **CLI** — `film-style <command>` (analyze, guide, stats, list, compare,
  learn-shots, score-clips, serve, mcp-serve, …). See `README.md` "All
  commands" and any command's `--help`.
- **Dashboard** — `film-style serve` binds `http://127.0.0.1:7421` (loopback
  only). Use `--no-browser` on a headless VM. Reads the JSON the CLI writes
  under `~/.film-style-analyzer/`, so run an `analyze` first or it shows an
  empty corpus.
- **MCP server** — `film-style mcp-serve` (stdio; launched by an MCP client
  like Claude Desktop, not run interactively).

### Non-obvious gotchas
- **Console scripts install to `~/.local/bin`, which is NOT on `PATH` by
  default.** Either add it (`export PATH="$HOME/.local/bin:$PATH"`) or run tests
  via `python3 -m pytest`. `film-style` itself requires the PATH entry.
- **Pin `opencv-python<5`.** `scenedetect[opencv]` and the `>=4.8` spec resolve
  to OpenCV 5.x, which changed the `cv2.HoughLinesP` return shape and breaks
  `composition.py` (2 `test_composition.py` horizon-tilt tests fail). The update
  script installs `opencv-python<5` to keep the 4.x API. Don't "fix" it in code.
- **Heavy extras `[shots]` (mediapipe/opencv/deepface/tensorflow) and `[audio]`
  (whisperx/inaSpeechSegmenter) are intentionally NOT installed.** The unit
  suite passes without them — those modules lazy-import their deps and tests use
  synthetic frames/stubs. Only install them if you specifically need to run
  `learn-shots` / `score-clips` / audio analysis end-to-end.

### Test / lint / run
- **Test:** `python3 -m pytest -q` — full suite (~260 tests, runs in ~1s, no
  network/API needed). One test is skipped unless you pass
  `--real-media <path-to-video>`.
- **Lint:** no linter is configured (no ruff/flake8/black/mypy). `pytest` is the
  only automated check.
- **Run offline:** `film-style analyze <folder-or-file> --skip-audio` works with
  no API keys and writes analysis JSON + per-clip thumbnails. `ANTHROPIC_API_KEY`
  is only needed for `guide` / `--vision` / `--shot-sizes` / MCP;
  `GOOGLE_API_KEY` only for Gemini paths. Nothing hits the network unless you
  invoke a command that explicitly talks to Anthropic/Gemini/Vimeo/YouTube.
- Data + generated artifacts live under `~/.film-style-analyzer/<genre>/`
  (default genre `wedding`); it is safe to delete to reset state.
