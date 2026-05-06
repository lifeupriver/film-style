# film-style-analyzer

> Analyze a folder of finished wedding films (or any films you admire) and
> produce a typed style profile that AI tools can consume to assemble new
> edits in your style.

A Python toolkit that watches your finished work, measures every dimension
that defines an editor's style — pacing, cut rhythm, audio layering, color
grade, shot composition, music tempo — and emits two artifacts:

1. **`style-guide.md`** — a markdown briefing for humans (and for pasting
   into NotebookLM as a source).
2. **`style-profile.json`** — a typed, addressable contract for downstream
   AI tools (e.g., assistants assembling rough cuts in your style via
   Claude Desktop / MCP).

A bundled web dashboard renders the corpus visually, and an MCP server
exposes the whole pipeline to Claude Desktop so you can ask Claude to
*"analyze these wedding films and tell me what's distinctive about this
editor's style"* in chat — and Claude actually does it.

---

## What it captures

| Dimension | How |
|---|---|
| **Pacing** | Frame-accurate scene detection (PySceneDetect ContentDetector tuned for soft-cut content). Per-clip durations, decile pacing curve, distribution histogram. |
| **Transitions** | Per-boundary classification: `hard_cut`, `dissolve`, `still_hold`, `fade_in`, `fade_out`. Detected by frame-gradient signature, not threshold heuristics. |
| **Color & grade** | Per-clip k-means palette, mean luminance, contrast σ, warm/cool index, saturation. Aggregated to a corpus-wide tone label. |
| **Shot mix** | Optional Claude-vision pass labels every clip as `wide` / `medium` / `close_up` / `insert` / `over_shoulder` / etc. |
| **Audio design** | Music vs. speech-over-music vs. ambient classification (inaSpeechSegmenter). When does the first speech enter? How long do excerpts run? |
| **Music** | Tempo (BPM), key, beat times, RMS energy curve, spectral centroid (librosa). Plus per-film cut-on-beat alignment scoring. |
| **Scene structure** | Chapter detection from dissolve boundaries. Optional Claude-vision labelling (`ceremony`, `dancing`, `getting_ready`, …) with a feedback loop for corrections. |
| **Speech content** | Word-level transcription via WhisperX. Speaker diarization optional. |

---

## Install

### Prerequisites

```bash
brew install ffmpeg
```

### Core install

```bash
git clone https://github.com/lifeupriver/film-style.git
cd film-style
pip install -e . --break-system-packages
```

### Optional extras

| Extra | Adds | Install |
|---|---|---|
| `[music]` | librosa-based tempo / beat / energy analysis | `pip install -e '.[music]'` |
| `[vimeo]` | yt-dlp video download (Vimeo + YouTube) | `pip install -e '.[vimeo]'` |
| `[gemini]` | Gemini-direct YouTube analysis (no download) | `pip install -e '.[gemini]'` |
| `[mcp]` | Claude Desktop integration over MCP | `pip install -e '.[mcp]'` |
| `[audio]` | WhisperX transcription + inaSpeechSegmenter classification (heavy; needs Python 3.11–3.12) | `pip install -e '.[audio]'` |

### Environment variables

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # required for `guide`, `--vision`, `--shot-sizes`, MCP
export GOOGLE_API_KEY="..."             # required for `--gemini` and analyze_youtube_via_gemini
export HF_TOKEN="..."                   # optional — for WhisperX speaker diarization
```

---

## Quickstart

```bash
# 1. Analyze a folder of finished wedding films.
film-style analyze ~/films/finished/

# 2. Generate the style guide + the AI-consumable profile.
film-style guide --vision

# 3. Open the dashboard to inspect the corpus visually.
film-style serve   # → http://127.0.0.1:7421

# 4. Compare a rough-cut FCPXML against the established profile.
film-style compare ~/edits/rough-cut-v1.fcpxml

# 5. Predict cut points for a new song using your established pacing.
film-style predict-cuts ~/music/new-song.mp3 --output cuts.fcpxml

# 6. Find which prior film is most stylistically similar.
film-style match sarah-and-mike

# 7. Export a NotebookLM-ingestion brief.
film-style export-notebooklm
```

---

## All commands

| Command | Purpose |
|---|---|
| `analyze <path>` | Run the analyzer on a file or folder. Slow with audio enabled; use `--skip-audio` for ~10× speedup |
| `import <url>` | Download from any Vimeo / YouTube / yt-dlp-supported URL |
| `guide` | Aggregate analyses, optionally run vision passes, write `style-guide.md` + `style-profile.json` |
| `stats` | Quick stats summary of the analyzed corpus |
| `list` | Table of every analyzed film with feature flags |
| `compare <fcpxml>` | Score a rough cut against the profile and suggest fixes |
| `match <stem>` | Find stylistically similar films in the archive |
| `tag <stem> --set k=v` | Add per-wedding metadata (venue, season, music_genre, …) |
| `predict-cuts <song>` | Predict cut points for a song; emit FCPXML marker track |
| `export-notebooklm` | Write a NotebookLM-ingestible markdown brief |
| `serve` | Boot the dashboard at http://127.0.0.1:7421 |
| `mcp-serve` | Run the MCP server (for Claude Desktop) |
| `config` | Show or `--init` the user config |

Every command supports `--help` for full flag detail.

---

## The dashboard

A local-only single-page app that renders the corpus as an editorial archive.

- Pacing curves drawn as hand-traced SVG, hover-loupe tooltips
- Filmstrip of every clip thumbnail with timecode
- Audio ribbon showing music / speech-over-music / ambient bands
- Synced timeline cursor across pacing-bars and audio-ribbon
- Inline chapter-label correction (feeds back into the next vision pass)
- Per-film metadata tagging (venue, season, music genre)
- Stylistically-nearest-films panel (matchmaker)
- Density toggle (compact / default / spacious), persisted in localStorage
- Print stylesheet for the Style Guide page (A4, page-breaks before each H2,
  link URLs printed inline)

Run `film-style serve`. Stays on `127.0.0.1` — never opens to the network.

Customize the masthead in `~/.film-style-analyzer/config.json`:

```json
{ "brand_name": "Your Studio", "editor_name": "your name" }
```

---

## Claude Desktop integration (MCP)

The MCP server makes the whole pipeline callable from a Claude Desktop chat.

### Setup

```bash
pip install -e '.[mcp]' --break-system-packages
```

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```jsonc
{
  "mcpServers": {
    "film-style-analyzer": {
      "command": "film-style",
      "args": ["mcp-serve"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

Restart Claude Desktop. The toolset shows up under the connections menu.

### What Claude can do

**Read** — `list_films`, `corpus_report`, `get_film`, `get_style_profile`, `get_style_guide`, `get_aggregate_stats`, `find_similar_films`, `list_inspirations`

**Pull / Analyze** — `import_videos` (any URL), `analyze_url` (download + analyze in one), `analyze_films` (local pipeline), `analyze_youtube_via_gemini` (no download), `generate_guide`

**Edit / Correct** — `set_film_metadata`, `set_chapter_label`

**Generate** — `compare_fcpxml`, `predict_cuts`, `export_for_notebooklm`

**Resources** auto-loadable as conversation context:
- `film-style://profile` — typed style-profile.json
- `film-style://guide` — markdown style guide
- `film-style://films` — film index
- `film-style://films/{stem}` — single film analysis

**Prompt** `edit_in_style` — primes Claude with the workflows.

### Sample Claude Desktop conversations

> *"Analyze the wedding films in `~/films/finished/` and give me a report."*
>
> Claude calls `analyze_films(paths=[...], skip_audio=True)` → `generate_guide(vision=True)` → `corpus_report()`, then writes the report.

> *"Pull `vimeo.com/showcase/12345` and analyze them. Cookies via Safari for the private ones."*
>
> Claude calls `analyze_url(url=..., cookies_browser="safari")` per URL.

> *"Watch this YouTube reference video and tell me what's distinctive about the edit."*
>
> Claude calls `analyze_youtube_via_gemini(url=...)`. No download; Gemini watches the video natively. Result is saved to `inspirations.json` for future guide passes.

> *"Build me a NotebookLM source."*
>
> Claude calls `export_for_notebooklm()`. You paste the markdown into NotebookLM as a source alongside any YouTube reference videos.

> *"Using my profile, propose where to cut a 3-minute teaser to `~/music/new-song.mp3`."*
>
> Claude reads `get_style_profile()`, calls `predict_cuts(song_path=..., target_duration_sec=180)`, gets back snapped-to-beat timestamps + an FCPXML marker track.

---

## NotebookLM tie-in

NotebookLM has no public API, but we've built two complementary ways to use
its underlying capabilities:

1. **Direct Gemini analysis of YouTube URLs** (`analyze_youtube_via_gemini`).
   Same engine that powers NotebookLM. ~30-second qualitative analysis of any
   YouTube reference video without downloading.

2. **NotebookLM-ingestion bridge** (`export_for_notebooklm`). Generates a
   single dense markdown document — pacing curve as a table, transition mix,
   audio rules, color grade, shot mix, music characterization, per-scene
   rules, transcript excerpts — that you upload to NotebookLM as a source.
   Add YouTube reference videos as additional sources in the same notebook.
   NotebookLM can then chat about your style grounded in *both* the measured
   quantitative profile *and* qualitative video references.

---

## Data layout

```
~/.film-style-analyzer/
├── config.json                    # user config
├── analyses/<name>.json           # per-film analysis
├── thumbs/<name>/clip_NNN.jpg     # per-clip thumbnails
├── audio/<name>.wav               # extracted audio (auto-cleaned)
├── inspirations.json              # YouTube references (analyze_youtube_via_gemini)
├── aggregate-stats.json           # written during `guide`
├── style-profile.json             # ⭐ the typed AI contract
├── style-guide.md                 # the human-readable guide
└── notebooklm-brief.md            # the NotebookLM source
```

Everything is local. Nothing leaves your machine unless you explicitly call
a tool that talks to Anthropic / Gemini / Vimeo / YouTube.

---

## What `style-profile.json` looks like

```jsonc
{
  "schema_version": "1.0",
  "film_count": 15,
  "duration":   { "target_min_sec": 312, "target_max_sec": 408, "target_median_sec": 352 },
  "pacing":     { "target_avg_clip_sec": 3.4, "decile_curve": [...], "min_clip_sec": 0.8, "max_clip_sec": 16.3 },
  "transitions":{ "hard_cut_pct": 2, "dissolve_pct": 16, "still_hold_pct": 82, "fade_pct": 0 },
  "audio":      { "first_speech_at_pct_target": 16.6, "speech_over_music_pct_target": 25.6 },
  "color":      { "mean_warm_cool": 0.23, "dominant_palette": [...], "tone_labels_seen": {...} },
  "shot_mix":   { "dominant": "medium_close", "distribution": {"wide": 22.0, ...} },
  "music":      { "target_tempo_range_bpm": [82, 124], "cut_on_beat_pct_target": 27.0 },
  "scenes":     { "ceremony": {...}, "dancing": {...} },
  "structure":  { "opening": {...}, "closing": {...} },
  "rules":      [ "Target average clip duration 3.4s …", "Land 27% of cuts on a music beat …", "…" ],
  "source_films":[ {...}, … ]
}
```

That's the artifact you point downstream Claude tools at when you say
*"edit this video in my style"* — every key is typed, addressable, and
traceable to source films.

---

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full picture: module
responsibilities, data flow, schemas, design decisions, known limits.

---

## Tests

```bash
pip install -e '.[dev]' --break-system-packages
pytest
```

100+ unit tests covering schema validity, aggregation, transition
classification, profile generation, MCP tool dispatch, dashboard endpoints,
matchmaker similarity, predict-cuts, NotebookLM brief, metadata tagging,
and FCPXML parsing.

For real-media smoke tests, drop a 30-second video in `tests/fixtures/` and
run `pytest --real-media tests/fixtures/sample.mp4`.

---

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and conventions.

## License

MIT — see [LICENSE](LICENSE).
