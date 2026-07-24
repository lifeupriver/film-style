# film-style-analyzer

**Point this at your finished films. It learns how you cut.**

You have a body of work — a season of weddings, a year of commercials, a
documentary cut here and there — and a recognizable editing style buried
inside it. The pacing. How long you let a shot breathe. When speech enters
the mix. How often you cut on a beat. The color grade you keep coming
back to. The compositions and emotional moments you actually keep when
you assemble a finished film.

That style is hard to articulate, and it's impossible to hand to an
assistant in a useful form. This tool watches every finished film in your
archive, measures the choices you made cut by cut, and turns them into
structured data you can read, share, or hand to an AI editing assistant.

### What you get out of it

- A **plain-English style guide** that summarizes how you actually cut —
  the brief you'd hand a new assistant editor on day one.
- A **machine-readable style profile** so an AI tool — Claude Desktop, a
  rough-cut assembler, anything that can read JSON — has something
  concrete to learn from when you say *"edit this in my style."*
- A **local dashboard** to scrub the corpus, see the pacing curves, and
  correct anywhere the analyzer guessed wrong.
- A **shot-level aesthetic profile** built from every thumbnail in your
  archive — preferred framing, headroom, lead room, thirds, exposure,
  sharpness, even the emotional intensity you tend to keep — used to
  **score raw footage clip-by-clip** so the rough-cut starts from a
  shortlist of the keepers, not the whole card.

### Why bother

- **See your own patterns.** Most editors can't articulate their style.
  The pacing curve and decile breakdown make it visible.
- **Catch a rough cut drifting.** `film-style compare ~/edits/v3.fcpxml`
  scores a rough cut against your established profile and tells you
  where the pacing is off, where dissolves pile up, where the structure
  breaks from your norm.
- **Make AI assistants actually useful.** Instead of *"edit it in my
  style"* being a vibe, it becomes a measured contract — pacing
  targets, transition mix, audio rules, scene structure, shot
  preferences — that downstream tools read directly.
- **Score the card before you touch the timeline.** Raw footage gets a
  0–100 score against the framing, exposure, sharpness, and emotional
  preferences learned from your archive, so you start the edit knowing
  which clips are keepers, which are usable with trims, and which to
  skip entirely.

### How it works, in one paragraph

You point `film-style analyze` at a folder of finished films. It runs
frame-accurate scene detection, classifies every transition, builds a
per-clip color palette, transcribes speech, identifies music vs.
ambient, tracks tempo and beat alignment, and extracts a thumbnail per
clip. Then `film-style guide` aggregates that across films into a
**style profile** (typed JSON) and a **style guide** (Claude-written
markdown). `film-style learn-shots` extends it with a per-frame
composition + emotion pass over every thumbnail in the archive.
`film-style score-clips` then scores raw footage proxies against the
learned aesthetic. Everything is local; nothing leaves your machine
unless you call a tool that explicitly talks to Anthropic, Gemini,
Vimeo, or YouTube.

Works for **wedding films, commercials, brand content, social shorts,
music videos, and documentaries** — each shipped as a pluggable "genre
pack" that adapts vocabulary, prompts, and tuned numeric defaults to
the editorial conventions of that genre. One genre per workspace; switch
with `film-style genre use commercial` or the `--genre` flag on any command.

### PyPI install

```bash
pip install film-style-analyzer
film-style --help
```

See [CHANGELOG.md](CHANGELOG.md) for release notes and [PRIVACY.md](PRIVACY.md)
for what stays local vs optional cloud APIs.

A bundled web dashboard renders the corpus visually, and an MCP server
exposes the whole pipeline to Claude Desktop so you can ask Claude to
*"analyze these commercials and tell me what's distinctive about this
editor's style"* in chat — and Claude actually does it.

#### Artifacts at a glance

| File | Written by | What it's for |
|---|---|---|
| `style-guide.md` | `guide` | Human-readable brief; paste into NotebookLM as a source |
| `style-profile.json` | `guide` | Typed contract for AI tools (the *"edit in my style"* artifact) |
| `shot-profile.json` | `learn-shots` | Learned framing / headroom / thirds / exposure / emotion preferences |
| `clip-scores.json` | `score-clips` | Per-clip 0–100 score + trim points for raw footage |

---

## Genres

Each shipped genre pack tunes vocabulary, prompts, and numeric defaults
to the genre's editorial conventions. One genre per workspace —
`~/.film-style-analyzer/<genre>/` keeps each corpus separate.

| Pack | Threshold | Audio emphasis | Duration hint | Distinctive labels |
|---|---|---|---|---|
| `wedding` | 8.0 | music_first | 3–10 min | ceremony, first_dance, speeches, getting_ready |
| `commercial` | 14.0 | voiceover_first | 6–120 s | hook, product_reveal, demo, cta, kicker |
| `brand_content` | 10.0 | interview | 1–5 min | interview, b_roll, title_card, archival |
| `social_short` | 16.0 | hook_driven | 7–90 s | hook, payoff, jump_cut, text_overlay, cta |
| `music_video` | 12.0 | beat_locked | 2–6 min | performance, narrative, abstract, lipsync |
| `documentary` | 7.0 | interview | 3–30 min | interview, b_roll, archival, vérité, recreation |

```bash
film-style genre list                # what packs are available
film-style genre show commercial     # inspect a pack's contents
film-style genre current             # which one is active
film-style genre init my_custom      # scaffold a custom pack
```

Set the active genre by editing `~/.film-style-analyzer/config.json`'s
`default_genre` field. User packs at `~/.film-style-analyzer/genre_packs/<name>.toml`
override shipped packs of the same name. Existing wedding installs run
`film-style migrate --to wedding` once to relocate legacy flat data.

---

## What it captures

| Dimension | How |
|---|---|
| **Pacing** | Frame-accurate scene detection (PySceneDetect ContentDetector tuned for soft-cut content). Per-clip durations, decile pacing curve, distribution histogram. |
| **Transitions** | Per-boundary classification: `hard_cut`, `dissolve`, `still_hold`, `fade_in`, `fade_out`. Detected by frame-gradient signature, not threshold heuristics. |
| **Color & grade** | Per-clip k-means palette, mean luminance, contrast σ, warm/cool index, saturation. Aggregated to a corpus-wide tone label. |
| **Shot mix** | Optional Claude-vision pass labels every clip as `wide` / `medium` / `close_up` / `insert` / `over_shoulder` / etc. |
| **Shot composition** | MediaPipe + OpenCV pass over thumbnails: face count + size, body framing, head-cutoff, headroom %, lead room ratio, rule-of-thirds proximity, horizon tilt (Hough), exposure histogram, backlit detection, Laplacian sharpness, center-vs-edge subject separation, motion blur on subject. Aggregated into `shot-profile.json` by `learn-shots`. |
| **Emotion** | DeepFace per-face emotion classification, weighted for wedding moments (happy ×1.0, surprise ×0.6, sad ×0.4 for happy tears; angry/fear/disgust penalized), with a multi-face crowd-reaction bonus and scene-aware weighting. |
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
| `[shots]` | MediaPipe + OpenCV + DeepFace for `learn-shots` and `score-clips` | `pip install -e '.[shots]'` |
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

# 8. Learn the editor's compositional + emotional preferences from the
#    thumbnails of every analyzed film.
film-style learn-shots                    # ~2-3 min for ~1500 thumbnails

# 9. Score raw-footage proxies against the learned shot profile.
film-style score-clips ~/footage/proxies/ --detect-trims
```

### Use your Claude Pro/Max subscription instead of API tokens

Two paths route LLM work through your subscription quota instead of an
`ANTHROPIC_API_KEY`:

**Text-only work (the markdown style guide):** set `claude_backend = "cli"`
in `~/.film-style-analyzer/config.json` and the guide writer shells out to
the local `claude` Code CLI:

```json
{ "claude_backend": "cli" }
```

Requires `claude` on `$PATH` and `claude auth login` once.

**Vision work (chapter labels, shot sizes):** the local CLI is text-only,
so vision passes happen via Claude Desktop + the MCP server. Run
`film-style mcp-serve` (or wire the server into Claude Desktop's
`claude_desktop_config.json`), then in chat ask:

> "Label all unlabeled chapters in my Amanda_and_Kenton film."

Claude calls `get_chapter_thumbnails_to_label`, looks at each thumbnail,
and writes labels back via `set_chapter_labels_bulk`. Same flow for
`get_clip_thumbnails_to_label_shots` + `set_shot_sizes_bulk` and
`set_film_metadata`. No API tokens consumed.

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
| `learn-shots` | Build `shot-profile.json` from corpus thumbnails (composition + emotion) |
| `score-clips <path>` | Score raw footage against `shot-profile.json`; optional trim detection |
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

## Shot composition + emotion

The corpus already produces frame-accurate thumbnails during `analyze`.
`learn-shots` and `score-clips` reuse them to capture the *shot-level*
choices an editor makes — what's in frame, where it sits, and the
emotion on the subjects' faces — and to score raw footage against
those preferences.

### `learn-shots`

Walks `~/.film-style-analyzer/<genre>/thumbs/<film>/` and runs every
per-frame detector on every thumbnail:

- **Faces & framing** — MediaPipe Face Detection. Body framing
  (`extreme-close-up` … `wide`) inferred from face area refined by Pose
  visibility (shoulders → hips → knees → ankles).
- **Headroom** — distance from the top of the head (Face Mesh forehead
  landmark) to the top of frame, as % of frame height. Ideal range
  ~8–15%.
- **Lead room** — direction of gaze from nose vs. eye-midline, ratio of
  space on the looking side to space behind the head.
- **Rule of thirds** — proximity of the primary face center to the
  nearest thirds intersection, scored 0–1.
- **Horizon tilt** — Hough line detection of strong architectural lines.
  Only fires when straight lines are actually present, so meadow shots
  aren't falsely flagged.
- **Exposure** — mean brightness, shadow/midtone/highlight pcts, black
  & white clipping, severity rating.
- **Backlit** — face region brightness vs. background; flagged when
  the face is 40 %+ darker than the surrounding frame.
- **Sharpness** — Laplacian variance, rated `very-soft` / `soft` /
  `acceptable` / `sharp` (calibrated for 720p).
- **Subject separation** — center-region sharpness vs. edge sharpness;
  higher ratio = more bokeh / shallower depth of field.
- **Motion blur on subject** — face-region sharpness vs. background
  sharpness; flags moving subjects in front of a steady camera.
- **Emotion** — DeepFace per-face classifier with wedding weights:
  happy ×1.0, surprise ×0.6, sad ×0.4 (happy-tears positive),
  neutral 0, angry ×−0.5, fear ×−0.3, disgust ×−0.5. Multi-face
  crowd-reaction bonus capped at +15.

Aggregated to `~/.film-style-analyzer/shot-profile.json`. Computed
fields include preferred framing, face-presence %, average headroom
and headroom 10–90 percentile range, average thirds score, exposure
range, dominant emotion distribution, and percent of frames at each
emotion-intensity tier.

```bash
film-style learn-shots
film-style learn-shots --films "sarah-and-mike,chen-williams"
film-style learn-shots --force          # rebuild
```

### `score-clips`

Scores raw 720p proxies against the learned profile. Per clip:

1. Sample N evenly-spaced frames (default 5).
2. Run every detector on each, plus optical-flow stability between
   consecutive frames.
3. Aggregate — **median** for composition (resilient to outliers),
   **peak** for emotion (one genuine moment makes the clip worth
   keeping).
4. Apply hard rejections (severe over/under-exposure, fully out of
   focus, head cut off the top of frame with a face present) → score 0.
5. Apply stacked soft penalties (shake, soft focus, too tight or wide
   crop, backlit, tilted horizon, poor headroom or lead room, low
   subject separation, "shooting from behind").
6. Compute the composite (50 baseline + composition + emotion +
   penalties), clamped to 0–100.
7. With `--detect-trims`, find the first stable+sharp frame from
   start and last stable+sharp frame from end; or for clips with
   transcript data, trim to 0.5 s before the first word and 1.0 s
   after the last word.

Scene-aware emotion weighting can be enabled by passing
`--scene-context scene-map.json` — `ceremony`, `first_look`, and
`speeches` get 1.5×, dancing gets 1.0×, B-roll and reception details
get 0× so emotion doesn't influence whether a sunset is keeper-worthy.

```bash
film-style score-clips /path/to/proxies/ --detect-trims
film-style score-clips /path/to/proxies/ --samples-per-clip 10
film-style score-clips /path/to/single-clip.mp4
film-style score-clips /path/to/proxies/ --scene-context scenes.json \
                                          --transcripts transcripts.json
```

**Performance.** All analysis runs on CPU. `learn-shots` over a
1,500-thumbnail corpus is ~2–3 minutes; `score-clips` on 247 clips at
5 samples each is ~15–20 minutes (DeepFace dominates at ~200–400 ms
per frame).

**B-roll handling.** Clips where no person is detected skip the
face/framing/headroom/lead-room/emotion detectors entirely. Sunsets,
tablescapes, and other detail shots are scored only on exposure,
sharpness, stability, and horizon tilt.

**Camera-original mapping.** The default proxy → original mapping
swaps `/02-proxies/` → `/01-camera-originals/` and replaces
`_proxy.mp4` with `.MXF`. The `original` field of every clip record
holds the resulting path so a downstream rough-cut tool can pull from
the camera originals.

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
├── shot-profile.json              # ⭐ shared across genres — learned shot aesthetic
├── <genre>/                       # per-genre workspace
│   ├── analyses/<name>.json       # per-film analysis
│   ├── thumbs/<name>/clip_NNN.jpg # per-clip thumbnails
│   ├── audio/<name>.wav           # extracted audio (auto-cleaned)
│   ├── inspirations.json          # YouTube references (analyze_youtube_via_gemini)
│   ├── aggregate-stats.json       # written during `guide`
│   ├── style-profile.json         # ⭐ the typed AI contract
│   ├── style-guide.md             # the human-readable guide
│   └── notebooklm-brief.md        # the NotebookLM source
```

`clip-scores.json` is written next to the proxy footage being scored
(or wherever `--output` points), not into the data root — that file
belongs with the project, not the corpus.

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

## What `shot-profile.json` looks like

```jsonc
{
  "version": "1.0",
  "films_analyzed": 15,
  "total_frames_analyzed": 1472,
  "framing_distribution": { "medium": 0.42, "close-up": 0.22, ... },
  "preferred_framing": "medium",
  "face_presence": { "frames_with_faces_pct": 72,
                     "primary_face_avg_size_pct": 8.2,
                     "facing_camera_pct": 89 },
  "composition": { "avg_thirds_score": 0.68,
                   "preferred_face_center_y": 0.35,
                   "avg_headroom_pct": 11.2,
                   "headroom_range": [6, 18] },
  "exposure":  { "avg_brightness": 0.48, "brightness_range": [0.25, 0.72] },
  "sharpness": { "avg_laplacian": 142.3, "min_laplacian_used": 45.0 },
  "subject_separation": { "avg_center_to_edge_ratio": 2.4, "min_ratio_used": 1.1 },
  "emotion_preferences": {
    "avg_peak_emotion_in_finished_films": 45.2,
    "pct_frames_with_emotion_above_20": 58,
    "pct_frames_with_emotion_above_40": 31,
    "dominant_emotions_distribution": { "happy": 0.48, "neutral": 0.32, ... }
  },
  "rejection_rules_learned": { "head_cutoff_pct": 0.3, ... }
}
```

## What `clip-scores.json` looks like

```jsonc
{
  "version": "1.0",
  "total_clips": 247,
  "clips_rejected": 18,
  "score_distribution": { "90-100": 12, "80-89": 34, ..., "rejected": 18 },
  "clips": [
    {
      "file": "card-A/CLIP0001_proxy.mp4",
      "original": "01-camera-originals/card-A/CLIP0001.MXF",
      "duration_sec": 12.4,
      "score": 87,
      "rejection": null,
      "scene": "ceremony",
      "analysis": { "framing": "medium", "faces_detected": 2,
                    "thirds_score": 0.74, "exposure_rating": "good",
                    "focus_rating": "sharp", "stability": "stable", ... },
      "emotion":  { "peak_wedding_emotion": 62.5, "peak_emotion_type": "happy",
                    "avg_wedding_emotion": 34.2, "emotional_frames_pct": 40.0 },
      "penalties_applied": [],
      "trim": { "trim_in_sec": 0.5, "trim_out_sec": 11.8,
                "usable_duration_sec": 11.3, "reason": "shaky_start" }
    }
  ]
}
```

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

270+ unit tests covering schema validity, aggregation, transition
classification, profile generation, MCP tool dispatch, dashboard HTTP API,
matchmaker similarity, predict-cuts, NotebookLM brief, metadata tagging,
FCPXML parsing, genre workspaces, migration, and the shot-composition /
emotion / scoring stack.

For real-media smoke tests, drop a 30-second video in `tests/fixtures/` and
run `pytest --real-media tests/fixtures/sample.mp4`.

---

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and conventions.

## License

MIT — see [LICENSE](LICENSE).

## Privacy

See [PRIVACY.md](PRIVACY.md).
