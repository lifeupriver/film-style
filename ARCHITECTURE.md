# Architecture

A walk-through of the codebase, from the directory layout to the design
decisions behind each subsystem.

## Layout

```
src/film_style_analyzer/
├── cli.py                    # click entrypoint — every `film-style` command
├── analyzer.py               # per-film orchestrator: probe → detect → audio → color → music
├── aggregator.py             # cross-film statistics
├── profile_writer.py         # builds style-profile.json (the AI contract)
├── guide_writer.py           # calls Claude to write style-guide.md
├── notebooklm_export.py      # produces a NotebookLM-ingestible brief
├── schemas.py                # Pydantic models for every data structure
├── config.py                 # user config (~/.film-style-analyzer/config.json)
├── server.py                 # stdlib HTTP server for the dashboard
├── mcp_server.py             # MCP server (Claude Desktop integration)
│
├── scene_detect.py           # PySceneDetect ContentDetector + boundary classification
├── dissolve_measure.py       # frame-gradient analysis: hard_cut / dissolve / still_hold
├── fade_detect.py            # opening/closing fade-to-black detection
├── chapters.py               # group clips into chapters at dissolve boundaries
├── thumbnails.py             # ffmpeg thumbnail extraction
├── color_analysis.py         # k-means palette + warmth + exposure + contrast
├── shot_size.py              # Claude vision per-clip composition labels
├── vision_classify.py        # Claude vision chapter scene types + few-shot loop
├── composition.py            # MediaPipe + OpenCV per-frame detectors
│                             #   (faces, framing, headroom, lead room, thirds,
│                             #   horizon tilt, exposure, sharpness, subject
│                             #   separation, motion blur, optical flow)
├── emotion.py                # DeepFace wrapper, wedding-weighted scoring,
│                             #   per-clip peak aggregation, scene weights
├── shot_profile.py           # Aggregator for shot-profile.json (`learn-shots`)
├── clip_scoring.py           # Hard rejections, soft penalties, composite
│                             #   scoring, trim detection (`score-clips`)
├── genre_pack.py             # GenrePack dataclass + TOML loader
├── genre_packs/              # shipped TOML packs (wedding, commercial, ...)
│
├── media_probe.py            # ffprobe wrapper
├── audio_extract.py          # ffmpeg WAV extraction
├── audio_classify.py         # inaSpeechSegmenter speech/music/noise + overlap merge
├── audio_transcribe.py       # WhisperX transcription
├── music_analyze.py          # librosa tempo / beats / energy / cut-on-beat
│
├── matchmaker.py             # film vector embedding + cosine similarity
├── metadata.py               # per-wedding tagging (curated keys)
├── predict_cuts.py           # decile-pacing-walk + beat-snap → FCPXML markers
├── fcpxml_parser.py          # FCPXML parsing for `compare` command
├── vimeo_import.py           # yt-dlp wrapper for Vimeo / YouTube downloads
├── gemini_analyzer.py        # Gemini narrative + YouTube URL analysis
│
└── static/                   # dashboard frontend (HTML / CSS / vanilla JS)
    ├── index.html
    ├── css/main.css
    └── js/{app,views,charts,markdown,timeline}.js

tests/                        # 250+ unit tests
```

## Genre packs

The pipeline math (scene detection, color analysis, audio classification,
beat tracking, dissolve measurement) is genre-agnostic. The vocabulary,
prompts, and tuned numeric defaults are not — they live in **genre
packs** (TOML files in `src/film_style_analyzer/genre_packs/`).

A `GenrePack` is loaded via `genre_pack.load(name)` and threaded as an
explicit argument through `analyzer.analyze_film`, `vision_classify`,
`shot_size`, `metadata.curated_keys`, `guide_writer.write_guide`,
`gemini_analyzer.analyze`, `notebooklm_export.export_brief`, and the
MCP server. The pack supplies:

- **Scene labels** and **shot labels** for vision classification
- **`insert_definition`** — what counts as an "insert" in this genre
- **Curated metadata keys** for the dashboard's per-film tagging dropdowns
- **`scene_detect_threshold`** and **`min_scene_length_sec`** — defaults
  tuned to the genre's average cut density
- **`audio_emphasis`** — one of `music_first`, `voiceover_first`,
  `interview`, `beat_locked`, `hook_driven`. Branches the audio rules
  in `profile_writer`
- **`still_hold_relevant`** — gates the still-hold transition rule
- **`prompts`** — a dict of prompt templates (guide writer system,
  vision classifier system, Gemini film/YouTube prompts, MCP edit-in-style,
  NotebookLM brief intro). Missing keys fall back to the wedding pack.

Workspaces partition by genre: `~/.film-style-analyzer/<genre>/{analyses,
thumbs, audio, style-profile.json, ...}`. Users author custom packs at
`~/.film-style-analyzer/genre_packs/<name>.toml`; user packs override
shipped packs of the same name. The active genre comes from
`config.default_genre`.

## Data flow

```
                 ┌──────────────────┐
   video files ─►│  analyzer.py     │──► ~/.film-style-analyzer/analyses/*.json
                 │   ├ probe          │
                 │   ├ scene_detect   │
                 │   ├ thumbnails     │
                 │   ├ color_analysis │
                 │   ├ audio (opt)    │
                 │   └ music (opt)    │
                 └──────────────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  aggregator.py   │   cross-film statistics
                 └──────────────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  profile_writer  │──► style-profile.json   (AI contract)
                 └──────────────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  guide_writer    │──► style-guide.md       (human briefing)
                 └──────────────────┘

                 Then either:

  film-style serve  ──►  server.py  ──►  static/             (dashboard)
  film-style mcp-serve  ──►  mcp_server.py                   (Claude Desktop)
  film-style export-notebooklm  ──►  notebooklm_export.py    (paste-bridge)
```

### Shot-learning + scoring (parallel pipeline)

`learn-shots` consumes the same thumbnails the analyzer wrote;
`score-clips` consumes raw 720p proxies plus the learned profile.

```
  ~/.film-style-analyzer/<genre>/thumbs/<film>/clip_NNN.jpg
            │
            ▼
   ┌──────────────────┐
   │  composition.py  │   per-frame: faces, framing, headroom, lead room,
   │  emotion.py      │   thirds, horizon, exposure, sharpness, separation,
   └──────────────────┘   motion blur, DeepFace emotion
            │
            ▼
   ┌──────────────────┐
   │  shot_profile.py │──► ~/.film-style-analyzer/shot-profile.json
   └──────────────────┘
            │
            ▼
   ┌──────────────────┐
   │  clip_scoring.py │   sample N frames per clip → median composition,
   │                  │   peak emotion → hard rejections + soft penalties
   │                  │   → composite 0–100, optional trim window
   └──────────────────┘
            │
            ▼
       <project>/clip-scores.json   (consumed by rough-cut assemblers)
```

## Key design decisions

**Why `style-profile.json` AND `style-guide.md`?** They serve different
consumers. The markdown is for humans to read and for pasting into NotebookLM
as a source. The JSON is for downstream AI tools (Claude assembling rough
cuts, etc.) — every key is typed, addressable, and traceable. The same data,
two formats.

**Why ContentDetector instead of PySceneDetect's AdaptiveDetector?** Adaptive
plateaus at 5–10 scenes regardless of threshold on soft-cut wedding content.
Threshold sweeps showed ContentDetector at threshold 8.0 produces realistic
clip counts (~2–3 sec average). See `scene_detect.py` docstring.

**Why a `still_hold` transition class?** Wedding-film editing heavily mixes
held photographs with motion video. Frame-gradient analysis at every detected
boundary distinguishes three signatures: a single-frame spike (hard cut), a
multi-frame plateau (dissolve), and one side near-zero MAD (still hold).
Lumping still-holds into the "dissolve" bucket would miss a defining
stylistic feature. See `dissolve_measure.classify_boundaries`.

**Why k-means over a fixed-palette histogram for color?** k-means adapts to
the actual content. A wedding-film palette is different from a corporate-doc
palette, and k-means finds the dominant clusters without assumed bins. The
trade-off is that k-means is more expensive — we sample one frame per clip
to keep total cost reasonable. See `color_analysis.py`.

**Why no full-fledged ML model for shot-size?** We use Claude vision in
batches of 16 thumbnails per request. Calibrated, accurate, no training data
needed, and the editor can correct labels in the dashboard — those
corrections become few-shot examples for the next vision pass. See
`shot_size.py` and `vision_classify.gather_existing_examples`.

**Why hand-rolled SVG charts in the dashboard?** Recharts / Chart.js produce
generic-looking output that conflicts with the editorial dark-mode aesthetic.
Hand-rolling a cardinal-spline line chart and donut takes ~150 lines and
gives full control over visual style (warm amber accents, hairline grids,
hover loupe with monospace timecode). See `static/js/charts.js`.

**Why MCP for the Claude Desktop integration?** MCP is the standard wire
protocol for Claude Desktop to call out to external tools. FastMCP + the
official Python SDK gives us automatic JSON schema generation from type hints,
stdio transport, resource templating. See `mcp_server.py`.

**Why a paste-bridge for NotebookLM rather than direct integration?**
NotebookLM has no public API. The next-best integration is to produce a
single dense source document the user uploads — and to leverage the same
underlying engine (Gemini) for direct YouTube URL analysis when you don't
want to download. See `notebooklm_export.py` and
`gemini_analyzer.analyze_youtube_url`.

**Why MediaPipe + OpenCV + DeepFace for shot composition?** The Claude
vision pass already produces shot-size labels (`shot_size.py`) — that
answers "what kind of shot is this?". `composition.py` answers a
different question: "*how* well-composed is this exact frame?" — and it
needs to do that across thousands of thumbnails per corpus and tens of
thousands of sampled raw-footage frames per project. A vision API call
per frame would be prohibitive on cost and latency; CPU-only MediaPipe +
OpenCV runs in ~50–100 ms per frame and gives frame-precise numerical
metrics (headroom %, thirds score, Laplacian variance, horizon angle).
DeepFace provides the same coverage for emotion. See `composition.py`
and `emotion.py`.

**Why median for composition, peak for emotion?** A clip's composition
should be judged by what most of it looks like — a single soft sample
shouldn't tank an otherwise-sharp clip. Emotion is the opposite: in a
10-second cutaway, one half-second of genuine reaction is the entire
reason the clip is useful. Aggregating with median for composition and
max for emotion encodes that asymmetry directly. See
`clip_scoring.aggregate_clip_frames` and `emotion.aggregate_clip_emotions`.

**Why hard rejections + stacking soft penalties instead of a single
score?** Hard rejections (severe over/under-exposure, head cut off the
top of frame, fully out of focus) are deal-breakers — no amount of
emotional content makes those clips usable. Soft penalties (mild shake,
slight tilt, off-preferred framing) reduce desirability but shouldn't
eliminate. Two-tier scoring keeps that distinction explicit and lets the
penalty ledger appear in the JSON for downstream tools that want to
explain *why* a clip ranked where it did. See
`clip_scoring.HARD_REJECTIONS` and `clip_scoring.collect_penalties`.

**Why is `shot-profile.json` outside the per-genre subfolders?**
Composition and emotion are properties of the editor's eye, not the
genre. A wedding editor's preferred headroom and thirds proximity carry
over to commercial work. Keeping the shot profile at the data-root level
lets one corpus inform clip scoring across multiple genres if the editor
chooses. (The genre-specific style profile in `<genre>/style-profile.json`
remains the authoritative pacing/transition/audio contract.)

## Schemas

Top-level types in `schemas.py`:

- `FilmAnalysis` — one per analyzed film
- `Clip` — one per detected scene; carries thumbnail, color, shot_size
- `ChapterRecord` — runs of clips between dissolve/fade boundaries
- `Pacing`, `Transitions`, `Cuts`, `FilmMeta`, `Structure` — sub-objects
- `TransitionType` — `hard_cut` | `dissolve` | `still_hold` | `fade_in` | `fade_out`

Aggregated/derived structures (not Pydantic, just dict-shaped):

- `aggregate-stats.json` — cross-film summary, used internally by `guide`
- `style-profile.json` — typed contract for AI consumption
- `style-guide.md` — Claude-written prose
- `inspirations.json` — saved YouTube reference analyses
- `notebooklm-brief.md` — paste-ready NotebookLM source
- `shot-profile.json` — learned compositional + emotional preferences
  (`shot_profile.aggregate_frames`)
- `clip-scores.json` — per-clip composite scores, penalties, and trim
  points for raw footage (`clip_scoring.score_directory`)

## Known limits

- **Audio classification + transcription** require Python 3.11–3.12 because
  inaSpeechSegmenter pulls keras/tensorflow, and the latter has limited 3.13+
  support. The full pipeline (color + scene + music + cut-on-beat) works on
  Python 3.13/3.14.

- **Beat tracking** via librosa identifies a "stable tempo region" — if a
  song has 10 seconds of silence/intro, beats won't be detected there, and
  cuts in that range can't score as on-beat. The `cut_on_beat_pct` metric
  reflects this honestly.

- **Color analysis** samples one frame per clip (the middle frame). For
  long single-shot openers this misses intra-shot color drift. Acceptable
  trade-off since wedding films average ~3-second clips.

- **Vision passes** require `ANTHROPIC_API_KEY` and consume API tokens. A
  100-clip film at the standard model is ~$0.05–0.15 in API cost depending
  on model.

- **Gemini YouTube URL analysis** requires `GOOGLE_API_KEY` and consumes
  Gemini API tokens. ~30 seconds and $0.05–0.15 per video.

- **Shot composition + emotion** require the `[shots]` extras
  (`mediapipe`, `opencv-python`, `numpy`, `deepface`). All run on CPU.
  DeepFace dominates `score-clips` runtime at ~200–400 ms per frame —
  budget ~15–20 minutes for 247 clips at 5 samples each. The MediaPipe
  detectors are lazy-imported, so the unit suite (which uses synthetic
  frames + stubbed detection results) runs without these extras
  installed. The shot-profile / clip-score files are written outside
  the per-genre subfolders because composition and emotion are
  properties of the editor's eye, not of any one genre.
