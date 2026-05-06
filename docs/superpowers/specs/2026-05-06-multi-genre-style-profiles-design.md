# Multi-Genre Style Profiles — Design

**Status:** Approved (in brainstorm)
**Date:** 2026-05-06
**Author:** Joshua + Claude

## Problem

`film-style-analyzer` currently encodes wedding-film assumptions in many
places: scene-label vocabularies, prompt strings, scene-detect thresholds,
metadata keys, audio rules, dashboard copy, and MCP prompts. An editor
who cuts commercials, brand content, social shorts, music videos, or
documentaries can run the pipeline and get back a profile that's
mathematically correct but semantically wedding-shaped (asking how soon
"ceremony audio" enters a 30-second product spot, etc.).

The mathematics of the pipeline (scene detection, dissolve measurement,
color k-means, librosa beat tracking, transcription) is genre-agnostic.
What's wedding-specific is the **labels, prompts, defaults, and report
framings** layered on top.

## Goal

Replace hardcoded wedding assumptions with a pluggable **genre pack**
abstraction. Ship six starter packs covering the genres the user works
in. Let users add custom packs without touching the package source.

## Scope decisions (from brainstorm)

- **One genre per workspace.** A user analyzes weddings into a wedding
  corpus and commercials into a separate commercial corpus. No mixed
  corpora. (Rejected: per-film genre tag.)
- **Six starter packs.** wedding, commercial, brand_content,
  social_short, music_video, documentary.
- **L2 prescription level.** Each pack carries vocabulary (labels,
  prompts) AND tuned numeric defaults (thresholds, min scene length,
  curated metadata keys, audio emphasis). Profile schema stays stable
  across genres so downstream AI tools keep working.
- **Pack format: TOML data files.** Not Python modules, not classes.
  Treats packs as data, lets users author custom genres by dropping a
  `.toml` file in their config directory.

## Architecture

### `genre_pack.py` (new module)

Defines the `GenrePack` dataclass and the loader:

```python
@dataclass(frozen=True)
class GenrePack:
    name: str
    display_name: str
    scene_detect_threshold: float
    min_scene_length_sec: float
    scene_labels: tuple[str, ...]
    shot_labels: tuple[str, ...]
    insert_definition: str
    metadata_keys: dict[str, list[str]]
    audio_emphasis: str           # music_first | voiceover_first | beat_locked | interview | hook_driven
    still_hold_relevant: bool
    duration_range_hint_sec: tuple[float, float]
    prompts: dict[str, str]       # named templates
```

`load(name: str) -> GenrePack` searches:

1. `~/.film-style-analyzer/genre_packs/<name>.toml` (user — overrides)
2. `<package>/genre_packs/<name>.toml` (shipped)

`list_available() -> list[str]` returns the union of names from both
search paths.

`PromptKey` enum (or string constants) names the templates each pack
must supply:

- `guide_writer_system`
- `chapter_classify_system`
- `shot_classify_system`
- `gemini_film_prompt`
- `gemini_youtube_prompt`
- `mcp_edit_in_style`
- `notebooklm_brief_intro`

A pack that's missing a key falls back to the equivalent key in the
shipped `wedding.toml` (so user packs only need to override what
differs).

### Module changes

| Module | Wedding hardcoding now lives in pack as |
|---|---|
| `vision_classify.py` | `pack.scene_labels`, `pack.prompts["chapter_classify_system"]` |
| `shot_size.py` | `pack.shot_labels`, `pack.prompts["shot_classify_system"]`, `pack.insert_definition` |
| `metadata.py` | `pack.metadata_keys` (CURATED_KEYS becomes a function `curated_keys(pack)`) |
| `guide_writer.py` | `pack.prompts["guide_writer_system"]`; user-message uses `pack.display_name + "s"` |
| `gemini_analyzer.py` | `pack.prompts["gemini_film_prompt"]`, `pack.prompts["gemini_youtube_prompt"]` |
| `mcp_server.py` | `pack.prompts["mcp_edit_in_style"]`; tool docstrings stay generic |
| `notebooklm_export.py` | `pack.prompts["notebooklm_brief_intro"]`, `pack.display_name` |
| `scene_detect.py` | default threshold and min-scene from `pack.scene_detect_threshold` / `pack.min_scene_length_sec` (CLI flag still wins) |
| `profile_writer.py` | audio rules branch on `pack.audio_emphasis`; `still_hold_pct` rules suppressed if `not pack.still_hold_relevant`. Records `genre: pack.name` at the top level |
| `analyzer.py` | accepts a `pack` argument; passes through to scene_detect / audio classifiers |
| `cli.py` | group docstring becomes generic; every command takes `--genre <name>` |
| `matchmaker.py` | vector dims unchanged; restricts archive to films from the same genre's analyses dir |
| `config.py` | adds `default_genre: str = "wedding"` |
| `mcp_server.py` resources | path-style: `film-style://wedding/profile`, `film-style://commercial/profile`, `film-style://wedding/films/{stem}` |

### CLI surface

**New flags on existing commands:**

- `analyze --genre <name>`
- `guide --genre <name>`
- `compare --genre <name>`
- `predict-cuts --genre <name>`
- `match --genre <name>`
- `tag --genre <name>` (operates within that genre's analyses dir)
- `stats --genre <name>`
- `list --genre <name>`
- `serve --genre <name>` (dashboard scoped to one genre at boot)
- `export-notebooklm --genre <name>`

When `--genre` is omitted, the CLI uses `config.default_genre`.

**New `genre` command group:**

- `film-style genre list` — table of all available packs (shipped + user)
- `film-style genre show <name>` — print the pack's contents
- `film-style genre init <name>` — scaffold a new user pack at
  `~/.film-style-analyzer/genre_packs/<name>.toml`, pre-filled with
  comments for each field and the wedding values as defaults
- `film-style genre current` — print the active genre (from config)

**New `migrate` command:**

- `film-style migrate --to <genre>` — moves legacy data
  (`~/.film-style-analyzer/{analyses,thumbs,audio,inspirations.json,
  aggregate-stats.json,style-profile.json,style-guide.md,
  notebooklm-brief.md}`) into `~/.film-style-analyzer/<genre>/`.

### Data layout

```
~/.film-style-analyzer/
├── config.json                    # { "default_genre": "wedding", ... }
├── genre_packs/                   # user-defined packs (optional)
│   └── my_custom.toml
├── wedding/
│   ├── analyses/<name>.json
│   ├── thumbs/<name>/clip_NNN.jpg
│   ├── audio/<name>.wav
│   ├── inspirations.json
│   ├── aggregate-stats.json
│   ├── style-profile.json
│   ├── style-guide.md
│   └── notebooklm-brief.md
├── commercial/...
├── brand_content/...
├── social_short/...
├── music_video/...
└── documentary/...
```

### Migration

On first run of the new version, if `~/.film-style-analyzer/analyses/`
exists at the legacy path, the CLI prints:

```
Detected legacy data layout (analyses/, thumbs/, etc. live at the root).
The new layout partitions by genre. Move existing data under wedding/?
[Y/n]
```

`Y` → moves files. `n` → exits with a hint to run `film-style migrate
--to <genre>` explicitly. We never auto-migrate silently.

The MCP server checks at startup and refuses to run if legacy paths
exist (printing the same instructions to stderr).

### Profile schema additions

`style-profile.json` gains:

- `genre: str` (required, top-level) — e.g. `"wedding"`, `"commercial"`
- `genre_display_name: str` (top-level)
- `genre_extensions: dict` (optional, top-level) — for any per-genre
  keys that don't fit the universal schema (e.g. `commercial.hook_at_sec_target`)

Existing top-level keys are unchanged. Downstream consumers can ignore
the new fields and keep working.

## Starter pack specs (L2)

| Pack | Threshold | Min scene | Audio emphasis | Still-hold | Duration hint | Distinctive labels |
|---|---|---|---|---|---|---|
| **wedding** | 8.0 | 0.5s | music_first | yes | 180–600s | ceremony, first_dance, speeches, getting_ready, portraits, reception_entrance, ... |
| **commercial** | 14.0 | 0.3s | voiceover_first | no | 6–120s | hook, product_reveal, lifestyle, demo, talking_head, cta, logo, kicker |
| **brand_content** | 10.0 | 0.4s | interview | no | 60–300s | interview, b_roll, title_card, product_inset, location, archival |
| **social_short** | 16.0 | 0.2s | hook_driven | no | 7–90s | hook, payoff, transition, text_overlay, jump_cut, reveal, cta |
| **music_video** | 12.0 | 0.25s | beat_locked | no | 120–360s | performance, narrative, abstract, transition, lipsync, vfx |
| **documentary** | 7.0 | 0.6s | interview | no | 180–1800s | interview, b_roll, archival, establishing, title_card, vérité, recreation |

Each pack supplies:

- `insert_definition` — what counts as an "insert" shot in this genre
  (wedding: "rings, glassware, place cards, paper details"; commercial:
  "product detail, typography, screen content, brand mark")
- A full set of prompts authored for the genre's editorial conventions
- Curated metadata keys appropriate to the genre (commercials: `client`,
  `product_category`, `placement`, `length_class`; documentaries:
  `subject_type`, `interview_count`, `archival_use`, `release_format`)

## Testing

### New tests

- `tests/test_genre_pack.py` — load every shipped pack, assert required
  fields are populated, TOML parses, prompt keys are present, scene_labels
  has no duplicates and no overlap with shot_labels.
- `tests/test_genre_cli.py` — `genre list`, `genre show`, `genre init`,
  `genre current`.
- `tests/test_migration.py` — legacy → genre-subfolder move with
  fixtures.
- `tests/fixtures/test_pack.toml` — minimal valid pack used by other
  tests where a synthetic pack is preferable to the real wedding pack.

### Updated tests

- `test_metadata.py` — `CURATED_KEYS` replaced by `curated_keys(pack)`.
  Test against wedding pack for back-compat parity.
- `test_aggregator.py`, `test_profile_writer.py` — pass `pack=wedding`
  to keep existing assertions valid.
- `test_mcp_tools.py`, `test_mcp_execute_tools.py` — MCP server tests
  exercise the genre parameter on read tools (defaults to wedding).

### Regression guarantee

Existing tests pass unchanged when the active pack is `wedding`. We
explicitly assert that `style-profile.json` for an existing wedding
corpus is byte-identical (modulo the new `genre` field) before/after
the refactor.

## Build sequence

1. **Add `genre_pack.py`** with the dataclass, loader, and `wedding.toml`
   that exactly reproduces today's behavior. Ship `wedding.toml`.
2. **Thread `pack` through `analyzer.py`, `vision_classify.py`,
   `shot_size.py`, `metadata.py`** — sites that today use module-level
   constants now accept a pack. Wedding behavior unchanged.
3. **Update `guide_writer.py`, `gemini_analyzer.py`, `notebooklm_export.py`,
   `mcp_server.py`** to read prompts from the pack.
4. **Update `profile_writer.py`** to branch on `audio_emphasis` and
   `still_hold_relevant`; add `genre`, `genre_display_name`, and
   `genre_extensions` to output.
5. **Add `--genre` flag** to every CLI command. Add `genre` command
   group. Add `migrate` command.
6. **Implement data layout migration** — startup check + interactive
   prompt + `migrate` command.
7. **Author the five new packs** — commercial, brand_content,
   social_short, music_video, documentary. Each gets prompt strings
   tested against a real sample.
8. **Update README and ARCHITECTURE.md** — generic-first, mention
   wedding as one of several packs.
9. **Update dashboard** — add a genre dropdown in the masthead; the
   server picks up the active genre via query param or config.

## Out of scope (YAGNI)

- Cross-genre matching ("find a wedding that paces like a commercial")
- Automatic genre detection from a video file
- Per-film genre override within a corpus
- Profile merging across genres
- A web UI for editing genre packs
- Genre inheritance / mixins (one pack extending another)

## Risks

- **Prompt quality variation across packs.** A wedding prompt has been
  iterated; new genre prompts haven't. Mitigation: ship the five new
  packs with prompts authored from real footage references, and
  document that prompts are user-overridable.
- **Schema drift via `genre_extensions`.** Downstream tools that *do*
  read genre_extensions need per-genre branching. Mitigation: the
  universal top-level schema stays stable; extensions are clearly
  scoped under one key.
- **Migration friction for existing wedding users.** They have to
  approve a one-time move. Mitigation: explicit prompt, never silent;
  `migrate` command for scripted use.
