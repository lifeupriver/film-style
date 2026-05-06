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

tests/                        # 100+ unit tests
```

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
