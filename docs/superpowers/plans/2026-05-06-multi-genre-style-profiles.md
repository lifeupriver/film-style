# Multi-Genre Style Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded wedding-film assumptions in `film-style-analyzer` with a pluggable Genre Pack abstraction. Ship six starter packs (wedding, commercial, brand_content, social_short, music_video, documentary) so editors of any genre get semantically correct labels, prompts, and tuned numeric defaults.

**Architecture:** A `GenrePack` frozen dataclass loaded from TOML files (shipped + user-overridable), threaded as an explicit argument through every site that today uses module-level constants. Profile schema gains `genre`/`genre_display_name`/`genre_extensions` fields but stays backwards-stable. Workspace data partitions into per-genre subfolders under `~/.film-style-analyzer/<genre>/`. Migration is interactive on first run after upgrade.

**Tech Stack:** Python 3.11+, `tomllib` (stdlib), Click, Pydantic, pytest. No new runtime dependencies.

---

## Task 1: Add `genre_pack.py` module + shipped `wedding.toml`

**Files:**
- Create: `src/film_style_analyzer/genre_pack.py`
- Create: `src/film_style_analyzer/genre_packs/__init__.py` (empty marker — kept as package data)
- Create: `src/film_style_analyzer/genre_packs/wedding.toml`
- Create: `tests/test_genre_pack.py`
- Modify: `pyproject.toml` (add `genre_packs/*.toml` to package-data)

- [ ] **Step 1.1: Write failing test for `GenrePack.load("wedding")`**

```python
# tests/test_genre_pack.py
"""Tests for the genre_pack module."""

from __future__ import annotations

import pytest

from film_style_analyzer import genre_pack
from film_style_analyzer.genre_pack import GenrePack


def test_load_wedding_pack():
    pack = genre_pack.load("wedding")
    assert isinstance(pack, GenrePack)
    assert pack.name == "wedding"
    assert pack.display_name == "wedding film"
    assert pack.scene_detect_threshold == 8.0
    assert pack.min_scene_length_sec == 0.5
    assert pack.audio_emphasis == "music_first"
    assert pack.still_hold_relevant is True
    assert "ceremony" in pack.scene_labels
    assert "first_dance" in pack.scene_labels
    assert "insert" in pack.shot_labels
    assert "rings" in pack.insert_definition.lower()


def test_pack_required_prompts_present():
    pack = genre_pack.load("wedding")
    required = {
        "guide_writer_system",
        "chapter_classify_system",
        "shot_classify_system",
        "gemini_film_prompt",
        "gemini_youtube_prompt",
        "mcp_edit_in_style",
        "notebooklm_brief_intro",
    }
    assert required.issubset(pack.prompts.keys())


def test_pack_metadata_keys_structure():
    pack = genre_pack.load("wedding")
    assert "venue" in pack.metadata_keys
    assert isinstance(pack.metadata_keys["venue"], list)
    assert "indoor" in pack.metadata_keys["venue"]


def test_load_unknown_pack_raises():
    with pytest.raises(genre_pack.GenrePackError):
        genre_pack.load("nonexistent_genre_xyz")


def test_list_available_includes_wedding():
    names = genre_pack.list_available()
    assert "wedding" in names


def test_pack_is_frozen():
    pack = genre_pack.load("wedding")
    with pytest.raises((AttributeError, Exception)):
        pack.name = "changed"  # frozen dataclass should reject this


def test_scene_labels_no_duplicates():
    pack = genre_pack.load("wedding")
    assert len(pack.scene_labels) == len(set(pack.scene_labels))


def test_scene_and_shot_labels_dont_overlap():
    pack = genre_pack.load("wedding")
    overlap = set(pack.scene_labels) & set(pack.shot_labels)
    assert overlap == set(), f"scene and shot labels overlap: {overlap}"
```

- [ ] **Step 1.2: Run the test — confirm it fails**

Run: `pytest tests/test_genre_pack.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'film_style_analyzer.genre_pack'`

- [ ] **Step 1.3: Create the `GenrePack` module**

```python
# src/film_style_analyzer/genre_pack.py
"""Genre Pack abstraction.

A GenrePack bundles the vocabulary (scene labels, shot labels), prompts, and
tuned numeric defaults that adapt the analyzer to a specific genre of
filmmaking. Packs are TOML files — shipped in this package and optionally
overridden in `~/.film-style-analyzer/genre_packs/`.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

USER_PACK_DIR = Path.home() / ".film-style-analyzer" / "genre_packs"
SHIPPED_PACK_DIR = Path(__file__).parent / "genre_packs"

REQUIRED_PROMPT_KEYS = (
    "guide_writer_system",
    "chapter_classify_system",
    "shot_classify_system",
    "gemini_film_prompt",
    "gemini_youtube_prompt",
    "mcp_edit_in_style",
    "notebooklm_brief_intro",
)


class GenrePackError(RuntimeError):
    pass


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
    audio_emphasis: str
    still_hold_relevant: bool
    duration_range_hint_sec: tuple[float, float]
    prompts: dict[str, str]


def _resolve_path(name: str) -> Path:
    user = USER_PACK_DIR / f"{name}.toml"
    if user.is_file():
        return user
    shipped = SHIPPED_PACK_DIR / f"{name}.toml"
    if shipped.is_file():
        return shipped
    raise GenrePackError(
        f"genre pack {name!r} not found "
        f"(searched {USER_PACK_DIR} and {SHIPPED_PACK_DIR})"
    )


def _load_wedding_fallback_prompts() -> dict[str, str]:
    """Wedding's prompts are the fallback for any pack that omits a prompt key."""
    path = SHIPPED_PACK_DIR / "wedding.toml"
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text()).get("prompts", {})


def load(name: str) -> GenrePack:
    path = _resolve_path(name)
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise GenrePackError(f"failed to parse {path}: {e}") from e

    prompts = dict(raw.get("prompts", {}))
    if name != "wedding":
        for key, val in _load_wedding_fallback_prompts().items():
            prompts.setdefault(key, val)

    missing = [k for k in REQUIRED_PROMPT_KEYS if k not in prompts]
    if missing:
        raise GenrePackError(
            f"pack {name!r} missing required prompts: {missing}"
        )

    duration = raw.get("duration_range_hint_sec") or [0.0, 0.0]
    return GenrePack(
        name=raw["name"],
        display_name=raw["display_name"],
        scene_detect_threshold=float(raw["scene_detect_threshold"]),
        min_scene_length_sec=float(raw["min_scene_length_sec"]),
        scene_labels=tuple(raw["scene_labels"]),
        shot_labels=tuple(raw["shot_labels"]),
        insert_definition=raw["insert_definition"],
        metadata_keys={k: list(v) for k, v in raw.get("metadata_keys", {}).items()},
        audio_emphasis=raw["audio_emphasis"],
        still_hold_relevant=bool(raw["still_hold_relevant"]),
        duration_range_hint_sec=(float(duration[0]), float(duration[1])),
        prompts=prompts,
    )


def list_available() -> list[str]:
    names: set[str] = set()
    for d in (SHIPPED_PACK_DIR, USER_PACK_DIR):
        if d.is_dir():
            for p in d.glob("*.toml"):
                names.add(p.stem)
    return sorted(names)
```

- [ ] **Step 1.4: Create `wedding.toml` reproducing today's behavior**

```toml
# src/film_style_analyzer/genre_packs/wedding.toml
name = "wedding"
display_name = "wedding film"
scene_detect_threshold = 8.0
min_scene_length_sec = 0.5
audio_emphasis = "music_first"
still_hold_relevant = true
duration_range_hint_sec = [180.0, 600.0]

scene_labels = [
    "getting_ready", "details", "first_look", "portraits", "ceremony",
    "ceremony_processional", "ceremony_vows", "ceremony_recessional",
    "cocktail_hour", "reception_entrance", "first_dance",
    "speeches", "toasts", "cake_cutting", "dancing", "send_off",
    "establishing", "transition", "other",
]

shot_labels = [
    "extreme_wide", "wide", "medium_wide", "medium", "medium_close",
    "close_up", "extreme_close", "insert", "over_shoulder", "aerial", "other",
]

insert_definition = "a detail of an object, no subject in frame (rings on a book, place card, paper details, glassware)"

[metadata_keys]
venue = ["indoor", "outdoor", "destination", "church", "barn", "estate", "beach", "garden", "ballroom"]
season = ["spring", "summer", "autumn", "winter"]
time_of_day = ["morning", "afternoon", "golden_hour", "evening", "night"]
ceremony = ["religious", "civil", "spiritual", "elopement", "vow_renewal"]
guest_count = ["intimate", "small", "medium", "large", "huge"]
music_genre = ["acoustic", "indie", "folk", "pop", "classical", "instrumental", "jazz", "electronic", "soul"]
weather = ["sunny", "overcast", "rainy", "snowy", "stormy"]
duration_target = ["short", "standard", "long"]

[prompts]
guide_writer_system = """You are helping a wedding filmmaker document their editing style.
You will receive detailed statistical analysis of their finished wedding films.
Write a comprehensive editing style guide in markdown that a junior editor (or an
AI rough cut assembler) could follow to produce edits that match this filmmaker's
style.

Be extremely specific. Use exact numbers from the data. Do not generalize when
you can be precise. Write rules, not descriptions. For example: "Ceremony clips:
4.8 seconds average, never exceed 7 seconds" is better than "ceremony clips tend
to be a bit longer."

The guide should be structured as actionable rules for assembling a rough cut,
not as a description of the filmmaker's work.

If the data includes a `scene_breakdown` array (per-scene-type statistics from
vision classification), produce a per-scene rules table. If it includes
`audio` and `transcript`, produce explicit audio-design rules. If it includes
`gemini_analyses`, treat them as qualitative observations and weave specific
distinctive choices into the guide.

Do not use the words: stunning, magical, seamless, breathtaking, cinematic,
captivating, mesmerizing, or any similar filler."""

chapter_classify_system = """You are labeling shots from a finished wedding film. Each image is the middle frame of one chapter of the film. Label each chapter with exactly one of these scene types:
{scene_labels}

Return JSON: {{"labels": ["label1", "label2", ...]}} with one label per image in the order presented. Be precise. Use 'other' only if nothing else fits."""

shot_classify_system = """You are labeling shots from a wedding film by composition. Each image is the middle frame of one shot. For each image, output exactly one of:
{shot_labels}

Definitions:
- extreme_wide: landscape / venue exterior with subjects tiny or absent.
- wide: full body of subject(s), context dominates.
- medium_wide: waist-up framing, two-shot, conversational distance.
- medium: mid-thigh up.
- medium_close: chest up.
- close_up: head and shoulders.
- extreme_close: face only / eyes / hands / ring.
- insert: {insert_definition}.
- over_shoulder: shot framed past the back of someone's head/shoulder.
- aerial: from above (drone, overhead).
- other: cannot tell.

Return JSON: {{"labels": ["label1", "label2", ...]}} in image order."""

gemini_film_prompt = """You are analyzing a finished wedding film to extract the editor's style.
This film is {duration} long with {cuts} cuts.

Analyze the film and answer these questions precisely:

1. OPENING: Describe the first 30 seconds. What is the first shot? How many establishing shots before the first "story" shot? When does the music start? When does the first cut happen?

2. SCENE FLOW: List every scene transition you observe. What visual or audio cue marks each transition? Are scenes strictly chronological or does the editor intercut between parallel timelines?

3. AUDIO DESIGN: When does ceremony/speech audio first appear? Over what visuals is it placed? How long do speech excerpts run? Does the music ever fully cut out or always play underneath?

4. PACING FEEL: Where does the edit feel slow and lingering vs. fast and energetic? Is there a build? Where is the emotional peak?

5. SHOT SELECTION: Does the editor favor wide shots, close-ups, or a specific mix? Do you see a pattern in how shot sizes alternate?

6. CLOSING: Describe the final 30 seconds. How does the film end? What is the last shot? Is there a fade? How long does the final shot hold?

7. DISTINCTIVE CHOICES: What 3 things make this editor's style recognizable? What would you notice if you watched 10 of their films?

Respond in structured JSON with one top-level key per question:
{{"opening": ..., "scene_flow": ..., "audio_design": ..., "pacing_feel": ..., "shot_selection": ..., "closing": ..., "distinctive_choices": [...]}}"""

gemini_youtube_prompt = """You are analyzing a wedding film (or a film whose editing style might inspire wedding-film editing) on YouTube.

Answer these questions precisely:

1. PACING: How does the editor handle pacing? Is it fast or slow? Does it build, plateau, or release? Where does it accelerate?

2. SHOT SELECTION: What kinds of shots dominate (wide/medium/close-up, handheld/locked, drone)? Is there a pattern in how shot sizes alternate?

3. AUDIO DESIGN: When does music play? When does speech enter? Does music continue under speech or drop out? Are ambient sounds featured?

4. COLOR / GRADE: What's the dominant tonal approach (warm/cool, low-key/high-key, saturated/desaturated)? Any signature looks (e.g., milky shadows, crushed blacks, lifted contrast)?

5. STRUCTURE: How does the film open and close? What's the narrative arc?

6. DISTINCTIVE CHOICES: Three things that make this editor's style recognizable. What would you notice if you watched 10 of their films?

7. RELEVANCE: How might this style translate to wedding-film editing? What would be a clear and specific takeaway for the user's edits?

Respond in structured JSON with one top-level key per question: opening, pacing, shot_selection, audio_design, color_grade, structure, distinctive_choices (array), relevance."""

mcp_edit_in_style = """You are assembling a rough cut in {brand_name}'s wedding-film style. Use the loaded style profile and guide as your reference; cite specific rules when you make a cut decision."""

notebooklm_brief_intro = """This brief summarizes the editing style of {brand_name}, derived from {n} analyzed wedding films. Use it as a reference when discussing edit choices, planning new films, or training assistants on this style."""
```

- [ ] **Step 1.5: Update `pyproject.toml` to ship the TOML files**

Modify `pyproject.toml` lines 62-67:

```toml
[tool.setuptools.package-data]
film_style_analyzer = [
    "static/*.html",
    "static/css/*.css",
    "static/js/*.js",
    "genre_packs/*.toml",
]
```

- [ ] **Step 1.6: Run the test — confirm it passes**

Run: `pytest tests/test_genre_pack.py -v`
Expected: PASS for all 8 tests.

- [ ] **Step 1.7: Commit**

```bash
git add src/film_style_analyzer/genre_pack.py src/film_style_analyzer/genre_packs/wedding.toml tests/test_genre_pack.py pyproject.toml
git commit -m "feat: add GenrePack abstraction + shipped wedding pack"
```

---

## Task 2: Thread `pack` through `vision_classify.py` and `shot_size.py`

**Files:**
- Modify: `src/film_style_analyzer/vision_classify.py`
- Modify: `src/film_style_analyzer/shot_size.py`
- Create/Modify: `tests/test_vision_classify_pack.py`

- [ ] **Step 2.1: Write failing test for vision_classify accepting a pack**

```python
# tests/test_vision_classify_pack.py
"""Test that vision_classify and shot_size honor a GenrePack."""

from __future__ import annotations

from film_style_analyzer import genre_pack
from film_style_analyzer.vision_classify import build_chapter_system_prompt
from film_style_analyzer.shot_size import build_shot_system_prompt


def test_chapter_prompt_uses_pack_labels():
    pack = genre_pack.load("wedding")
    prompt = build_chapter_system_prompt(pack)
    assert "ceremony" in prompt
    assert "first_dance" in prompt
    assert "wedding film" in prompt.lower()


def test_shot_prompt_uses_pack_labels_and_insert_def():
    pack = genre_pack.load("wedding")
    prompt = build_shot_system_prompt(pack)
    assert "extreme_wide" in prompt
    assert "rings" in prompt.lower()  # from wedding's insert_definition
```

- [ ] **Step 2.2: Run the test — confirm it fails**

Run: `pytest tests/test_vision_classify_pack.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_chapter_system_prompt'`

- [ ] **Step 2.3: Refactor `vision_classify.py` to accept a pack**

Replace lines 14-30 of `src/film_style_analyzer/vision_classify.py`:

```python
from .genre_pack import GenrePack


def build_chapter_system_prompt(pack: GenrePack) -> str:
    """Render the chapter-classification system prompt for the given pack."""
    template = pack.prompts["chapter_classify_system"]
    return template.format(scene_labels=", ".join(pack.scene_labels))
```

Modify `classify_chapters` signature to add `pack: GenrePack` as a required keyword argument and use the rendered prompt instead of the module-level `SYSTEM`:

```python
def classify_chapters(
    thumbnail_paths: list[Path],
    pack: GenrePack,
    model: str = "claude-sonnet-4-20250514",
    examples: list[tuple[Path, str]] | None = None,
    max_examples: int = 6,
) -> list[str]:
    if not thumbnail_paths:
        return []
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise VisionError("ANTHROPIC_API_KEY not set")

    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise VisionError("anthropic SDK not installed") from e

    client = Anthropic(api_key=api_key)
    system_prompt = build_chapter_system_prompt(pack)
    valid_labels = set(pack.scene_labels)
    # ... existing batch loop, but use system=system_prompt and the final
    # return uses `valid_labels` instead of the global SCENE_LABELS:
    # return [l if l in valid_labels else "other" for l in labels]
```

Remove the module-level `SCENE_LABELS` and `SYSTEM` constants. Update the final line of `classify_chapters` to use `valid_labels` instead of `SCENE_LABELS`.

- [ ] **Step 2.4: Refactor `shot_size.py` to accept a pack**

Replace lines 15-47 of `src/film_style_analyzer/shot_size.py`:

```python
from .genre_pack import GenrePack


def build_shot_system_prompt(pack: GenrePack) -> str:
    """Render the shot-classification system prompt for the given pack."""
    template = pack.prompts["shot_classify_system"]
    return template.format(
        shot_labels=", ".join(pack.shot_labels),
        insert_definition=pack.insert_definition,
    )
```

Modify `classify_shots` signature to require `pack: GenrePack` as a positional arg after `thumbnail_paths`. Replace `system=SYSTEM` with `system=build_shot_system_prompt(pack)`. Replace the final `out.extend(...)` validation against `SHOT_LABELS` with `set(pack.shot_labels)`.

Remove the module-level `SHOT_LABELS` and `SYSTEM`.

- [ ] **Step 2.5: Run the test — confirm it passes**

Run: `pytest tests/test_vision_classify_pack.py -v`
Expected: PASS.

- [ ] **Step 2.6: Find and fix existing callers**

Run: `grep -rn "classify_chapters\|classify_shots\|SCENE_LABELS\|SHOT_LABELS" src/film_style_analyzer/ tests/`

For each caller (likely `cli.py` and possibly `analyzer.py`), add the pack argument. The CLI loads `pack = genre_pack.load(genre)` (genre comes from `--genre` flag or `cfg.default_genre` — wired up in Task 5) and passes it through.

For now, just propagate a literal `genre_pack.load("wedding")` so the existing tests pass; Task 5 wires it to a CLI flag.

- [ ] **Step 2.7: Run full test suite**

Run: `pytest -x`
Expected: PASS. If any test fails because it called the old signatures, update the test to pass `pack=genre_pack.load("wedding")`.

- [ ] **Step 2.8: Commit**

```bash
git add src/film_style_analyzer/vision_classify.py src/film_style_analyzer/shot_size.py tests/test_vision_classify_pack.py src/film_style_analyzer/cli.py
git commit -m "refactor: thread genre pack through vision_classify and shot_size"
```

---

## Task 3: Thread `pack` through `metadata.py`, `scene_detect.py`, and `analyzer.py`

**Files:**
- Modify: `src/film_style_analyzer/metadata.py`
- Modify: `src/film_style_analyzer/scene_detect.py`
- Modify: `src/film_style_analyzer/analyzer.py`
- Create/Modify: `tests/test_metadata.py`

- [ ] **Step 3.1: Write failing test for `curated_keys(pack)`**

```python
# tests/test_metadata.py — new test, append to existing file or create
from film_style_analyzer import genre_pack
from film_style_analyzer.metadata import curated_keys


def test_curated_keys_returns_pack_metadata():
    pack = genre_pack.load("wedding")
    keys = curated_keys(pack)
    assert keys == pack.metadata_keys
    assert "venue" in keys
    assert "indoor" in keys["venue"]
```

- [ ] **Step 3.2: Run test — confirm it fails**

Run: `pytest tests/test_metadata.py::test_curated_keys_returns_pack_metadata -v`
Expected: FAIL — `cannot import name 'curated_keys'`.

- [ ] **Step 3.3: Replace `CURATED_KEYS` with `curated_keys(pack)`**

In `src/film_style_analyzer/metadata.py`, remove lines 11-22 (the `CURATED_KEYS` dict) and add:

```python
from .genre_pack import GenrePack


def curated_keys(pack: GenrePack) -> dict[str, list[str]]:
    """The metadata keys/values surfaced as dropdowns for this genre."""
    return pack.metadata_keys
```

Update the module docstring lines 1-7 to remove "wedding" framing — generic version: "Per-film metadata. Free-form key/value, with a curated set the dashboard surfaces as dropdowns. The curated keys come from the active genre pack."

- [ ] **Step 3.4: Find and fix callers of `CURATED_KEYS`**

Run: `grep -rn "CURATED_KEYS" src/film_style_analyzer/ tests/`

For each caller (likely `cli.py`, `server.py`, dashboard helpers), replace with `curated_keys(pack)` where pack is the active pack for the request.

- [ ] **Step 3.5: Update `scene_detect.py` to default from pack**

Modify `src/film_style_analyzer/scene_detect.py`. Keep `DEFAULT_CONTENT_THRESHOLD = 8.0` as a fallback constant (so the module is still importable without a pack), but document that `analyzer.py` resolves the genre default before calling `detect_clips`. No signature change needed — `detect_clips` already takes `threshold` and `min_scene_length_sec` as arguments.

Update the module docstring (lines 1-13) to remove the wedding-specific tone — generic version explaining that ContentDetector is used and thresholds come from the active genre.

- [ ] **Step 3.6: Update `analyzer.py` to accept a pack**

Modify `src/film_style_analyzer/analyzer.py`:

Replace the `analyze_film` signature (lines 57-73) so `pack` is required:

```python
from .genre_pack import GenrePack


def analyze_film(
    path: Path,
    thumbs_root: Path,
    pack: GenrePack,
    audio_root: Path | None = None,
    min_scene_length_sec: float | None = None,
    threshold: float | None = None,
    skip_audio: bool = False,
    skip_color: bool = False,
    color_every_n_clips: int = 1,
    skip_music: bool = True,
    whisper_model: str = "large-v3",
    language: str = "en",
    diarize: bool = True,
    run_gemini: bool = False,
    gemini_model: str = "gemini-2.5-pro",
    cleanup_audio: bool = True,
) -> FilmAnalysis:
    if min_scene_length_sec is None:
        min_scene_length_sec = pack.min_scene_length_sec
    if threshold is None:
        threshold = pack.scene_detect_threshold
    # ... rest unchanged through detect_clips call
```

In the same file, where `analyze_film` calls `gemini_analyzer.analyze`, pass `pack=pack` (Task 4 will update gemini_analyzer to use it).

- [ ] **Step 3.7: Update CLI's `analyze` command to pass pack**

In `src/film_style_analyzer/cli.py`, find every call to `analyze_film(...)` and add `pack=genre_pack.load(...)` (Task 5 will wire this to the actual `--genre` flag; for now hardcode `"wedding"`).

- [ ] **Step 3.8: Run the test suite**

Run: `pytest -x`
Expected: PASS. If callers in tests broke, update them to pass `pack=genre_pack.load("wedding")`.

- [ ] **Step 3.9: Commit**

```bash
git add src/film_style_analyzer/metadata.py src/film_style_analyzer/scene_detect.py src/film_style_analyzer/analyzer.py src/film_style_analyzer/cli.py tests/test_metadata.py
git commit -m "refactor: thread genre pack through analyzer, scene_detect, metadata"
```

---

## Task 4: Move prompts in `guide_writer.py`, `gemini_analyzer.py`, `notebooklm_export.py` to the pack

**Files:**
- Modify: `src/film_style_analyzer/guide_writer.py`
- Modify: `src/film_style_analyzer/gemini_analyzer.py`
- Modify: `src/film_style_analyzer/notebooklm_export.py`
- Modify: `src/film_style_analyzer/mcp_server.py`
- Create: `tests/test_prompts_from_pack.py`

- [ ] **Step 4.1: Write failing test that prompts come from the pack**

```python
# tests/test_prompts_from_pack.py
"""Smoke tests: prompts in network-calling modules are sourced from the pack."""

from __future__ import annotations

from film_style_analyzer import genre_pack
from film_style_analyzer.guide_writer import build_system_prompt
from film_style_analyzer.gemini_analyzer import build_film_prompt, build_youtube_prompt
from film_style_analyzer.notebooklm_export import build_brief_intro


def test_guide_system_prompt_from_pack():
    pack = genre_pack.load("wedding")
    s = build_system_prompt(pack)
    assert "wedding filmmaker" in s.lower()


def test_gemini_film_prompt_uses_pack_and_substitutes_runtime_vars():
    pack = genre_pack.load("wedding")
    p = build_film_prompt(pack, duration="5:00", cuts=120)
    assert "5:00" in p
    assert "120" in p
    assert "wedding film" in p.lower()


def test_gemini_youtube_prompt_from_pack():
    pack = genre_pack.load("wedding")
    p = build_youtube_prompt(pack)
    assert "wedding" in p.lower()


def test_notebooklm_intro_substitutes_brand_and_count():
    pack = genre_pack.load("wedding")
    text = build_brief_intro(pack, brand_name="Test Studio", n=42)
    assert "Test Studio" in text
    assert "42" in text
    assert "wedding" in text.lower()
```

- [ ] **Step 4.2: Run test — confirm it fails**

Run: `pytest tests/test_prompts_from_pack.py -v`
Expected: FAIL — those builder functions don't exist yet.

- [ ] **Step 4.3: Refactor `guide_writer.py`**

Replace `src/film_style_analyzer/guide_writer.py`:

```python
"""Call Claude to turn aggregated stats into a markdown style guide."""

from __future__ import annotations

import json
import os

from .genre_pack import GenrePack


def build_system_prompt(pack: GenrePack) -> str:
    return pack.prompts["guide_writer_system"]


def write_guide(stats: dict, pack: GenrePack, model: str = "claude-sonnet-4-20250514") -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Run: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    n = stats.get("film_count", 0)
    user = (
        f"Here is the aggregated analysis of {n} {pack.display_name}s:\n\n"
        f"{json.dumps(stats, indent=2)}\n\n"
        f"Write the complete editing style guide."
    )

    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=build_system_prompt(pack),
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in msg.content if hasattr(block, "text"))
```

- [ ] **Step 4.4: Refactor `gemini_analyzer.py`**

In `src/film_style_analyzer/gemini_analyzer.py`:

1. Remove module-level `PROMPT` (lines 11-42) and `YOUTUBE_PROMPT` (lines 66-95).
2. Add at the top of the module:

```python
from .genre_pack import GenrePack


def build_film_prompt(pack: GenrePack, duration: str, cuts: int) -> str:
    return pack.prompts["gemini_film_prompt"].format(duration=duration, cuts=cuts)


def build_youtube_prompt(pack: GenrePack) -> str:
    return pack.prompts["gemini_youtube_prompt"]
```

3. Update `analyze(...)` signature to require `pack: GenrePack` and use `build_film_prompt(pack, _format_duration(duration_sec), cut_count)` in place of `PROMPT.format(...)`.

4. Update `analyze_youtube_url(...)` signature to require `pack: GenrePack` and use `custom_prompt or build_youtube_prompt(pack)`.

- [ ] **Step 4.5: Refactor `notebooklm_export.py`**

Read the current file first (lines 1-60+). Replace the hardcoded `"{N} analyzed wedding films"` string with `build_brief_intro(pack, brand_name=..., n=...)`:

```python
from .genre_pack import GenrePack


def build_brief_intro(pack: GenrePack, brand_name: str, n: int) -> str:
    return pack.prompts["notebooklm_brief_intro"].format(
        brand_name=brand_name, n=n
    )
```

Update the existing export function(s) to accept and use `pack: GenrePack`.

- [ ] **Step 4.6: Update MCP server's `edit_in_style` prompt**

In `src/film_style_analyzer/mcp_server.py`, find any reference to a hardcoded "wedding" in the `edit_in_style` MCP tool/prompt body and replace with `pack.prompts["mcp_edit_in_style"].format(brand_name=cfg.brand_name)`.

(Full mcp_server URI changes happen in Task 6; this step only swaps the prompt body.)

- [ ] **Step 4.7: Run test suite**

Run: `pytest tests/test_prompts_from_pack.py tests/ -x`
Expected: PASS. Update any callers in cli.py / mcp_server.py that broke due to new required arguments.

- [ ] **Step 4.8: Commit**

```bash
git add src/film_style_analyzer/guide_writer.py src/film_style_analyzer/gemini_analyzer.py src/film_style_analyzer/notebooklm_export.py src/film_style_analyzer/mcp_server.py src/film_style_analyzer/cli.py tests/test_prompts_from_pack.py
git commit -m "refactor: source LLM prompts from genre pack"
```

---

## Task 5: Update `profile_writer.py` to branch on `audio_emphasis` and `still_hold_relevant`

**Files:**
- Modify: `src/film_style_analyzer/profile_writer.py`
- Modify: `tests/test_profile_writer.py` (or create if missing)

- [ ] **Step 5.1: Write failing test for genre-aware profile output**

```python
# tests/test_profile_writer_genre.py
"""Profile_writer should record genre + branch on audio_emphasis."""

from __future__ import annotations

from film_style_analyzer import genre_pack
from film_style_analyzer.profile_writer import build_profile


def test_profile_records_genre_top_level():
    pack = genre_pack.load("wedding")
    profile = build_profile([], {}, pack=pack)
    assert profile["genre"] == "wedding"
    assert profile["genre_display_name"] == "wedding film"


def test_profile_includes_genre_extensions_key():
    pack = genre_pack.load("wedding")
    profile = build_profile([], {}, pack=pack)
    assert "genre_extensions" in profile
    assert isinstance(profile["genre_extensions"], dict)


def test_still_hold_rule_suppressed_when_pack_disables_it():
    """When pack.still_hold_relevant=False, no still-hold rules should appear."""
    # Build a synthetic non-wedding context: we don't load a real non-wedding
    # pack yet (Task 7), but we can verify the wedding pack DOES emit the rule
    # so the branch exists. The negative case will be added in Task 7.
    pack = genre_pack.load("wedding")
    aggregated = {
        "transitions": {
            "hard_cut_pct": 80,
            "dissolve_pct": 15,
            "still_hold_pct": 5,
            "avg_dissolves_per_film": 8,
            "avg_still_holds_per_film": 3,
        },
    }
    profile = build_profile([], aggregated, pack=pack)
    rules_text = " ".join(profile.get("rules", []))
    assert "still-hold" in rules_text  # wedding pack: rule present
```

- [ ] **Step 5.2: Run test — confirm it fails**

Run: `pytest tests/test_profile_writer_genre.py -v`
Expected: FAIL — `build_profile` doesn't accept `pack` yet.

- [ ] **Step 5.3: Update `build_profile` to accept and honor pack**

In `src/film_style_analyzer/profile_writer.py`:

Update the signature:

```python
from .genre_pack import GenrePack


def build_profile(
    films: list[FilmAnalysis],
    aggregated: dict,
    pack: GenrePack,
) -> dict[str, Any]:
```

After the empty-films early return, immediately establish the genre fields. At the bottom of the function (the final `return {...}`), add:

```python
"genre": pack.name,
"genre_display_name": pack.display_name,
"genre_extensions": {},
```

Also update the empty-films early return to include them:

```python
if not films:
    return {
        "schema_version": "1.0",
        "generator_version": __version__,
        "film_count": 0,
        "rules": [],
        "genre": pack.name,
        "genre_display_name": pack.display_name,
        "genre_extensions": {},
    }
```

Inside the transitions block (around line 84-96), wrap the still-hold rule in a `pack.still_hold_relevant` check:

```python
if transitions.get("hard_cut_pct") is not None:
    parts = [
        f"{transitions['hard_cut_pct']:.0f}% hard cuts",
        f"{transitions.get('dissolve_pct', 0):.0f}% dissolves "
        f"(~{transitions.get('avg_dissolves_per_film', 0):.0f} per film)",
    ]
    if pack.still_hold_relevant and transitions.get("still_hold_pct"):
        parts.append(
            f"{transitions['still_hold_pct']:.0f}% still-holds "
            f"(boundaries between motion video and held photographs, "
            f"~{transitions.get('avg_still_holds_per_film', 0):.0f} per film)"
        )
    rules.append(". ".join(parts) + ".")
```

Inside the audio block (around line 99-122), branch on `pack.audio_emphasis`:

```python
if audio:
    audio_block.update({...})  # existing assignments unchanged
    if pack.audio_emphasis == "music_first" and audio.get("first_speech_at_pct_avg") is not None:
        rules.append(
            f"Hold music alone before any speech for the first "
            f"{audio['first_speech_at_pct_avg']:.0f}% of the film "
            f"(~{(audio.get('first_speech_at_sec_avg') or 0):.0f}s)."
        )
    elif pack.audio_emphasis == "voiceover_first" and audio.get("first_speech_at_pct_avg") is not None:
        rules.append(
            f"Voiceover/dialogue starts within the first "
            f"{audio['first_speech_at_pct_avg']:.0f}% of runtime "
            f"(~{(audio.get('first_speech_at_sec_avg') or 0):.0f}s) — lead with the message."
        )
    elif pack.audio_emphasis == "interview" and audio.get("speech_over_music_pct_avg"):
        rules.append(
            f"Interview/dialogue covers ~{audio['speech_over_music_pct_avg']:.0f}% "
            f"of runtime; cut to b-roll under speech, not over silence."
        )
    elif pack.audio_emphasis == "beat_locked":
        rules.append("Lock cuts to the music beat — see music block for tempo target.")
    elif pack.audio_emphasis == "hook_driven" and audio.get("first_speech_at_sec_avg") is not None:
        rules.append(
            f"Open with a hook in the first 3 seconds; "
            f"first speech lands at ~{audio['first_speech_at_sec_avg']:.1f}s."
        )

    if pack.audio_emphasis == "music_first" and audio.get("speech_over_music_pct_avg"):
        rules.append(
            f"Layer speech over music for ~{audio['speech_over_music_pct_avg']:.0f}% "
            f"of total runtime; speech rarely plays without music underneath."
        )
```

- [ ] **Step 5.4: Update existing callers**

Run: `grep -rn "build_profile(" src/film_style_analyzer/ tests/`

Update each call site to pass `pack=pack`. In `cli.py`, the active pack comes from the genre flag (Task 6). For now, hardcode `genre_pack.load("wedding")` at the call site.

In any pre-existing test that calls `build_profile(films, aggregated)`, add `pack=genre_pack.load("wedding")` to keep behavior identical.

- [ ] **Step 5.5: Run the test suite**

Run: `pytest -x`
Expected: PASS for everything including the new genre test.

- [ ] **Step 5.6: Commit**

```bash
git add src/film_style_analyzer/profile_writer.py src/film_style_analyzer/cli.py tests/test_profile_writer_genre.py tests/
git commit -m "refactor: profile_writer branches on audio_emphasis and records genre"
```

---

## Task 6: Add `--genre` flag, `genre` command group, per-genre data layout, and `migrate` command

**Files:**
- Modify: `src/film_style_analyzer/config.py` (add `default_genre`)
- Modify: `src/film_style_analyzer/cli.py` (per-command flag + genre group + migrate)
- Modify: `src/film_style_analyzer/mcp_server.py` (paths derived from genre)
- Modify: `src/film_style_analyzer/server.py` (paths derived from genre)
- Create: `tests/test_genre_cli.py`
- Create: `tests/test_migration.py`

- [ ] **Step 6.1: Write failing test for `default_genre` config field**

```python
# Append to tests/test_config.py if it exists, or create:
from film_style_analyzer.config import Config


def test_config_has_default_genre():
    c = Config()
    assert c.default_genre == "wedding"
```

- [ ] **Step 6.2: Add `default_genre` to `Config`**

In `src/film_style_analyzer/config.py` line 26 (after `cleanup_audio_after_analysis`), add:

```python
    default_genre: str = "wedding"
```

- [ ] **Step 6.3: Write failing test for `genre list` and `genre show`**

```python
# tests/test_genre_cli.py
"""Tests for the `film-style genre` command group."""

from __future__ import annotations

from click.testing import CliRunner

from film_style_analyzer.cli import cli


def test_genre_list_includes_wedding():
    runner = CliRunner()
    result = runner.invoke(cli, ["genre", "list"])
    assert result.exit_code == 0
    assert "wedding" in result.output


def test_genre_show_wedding():
    runner = CliRunner()
    result = runner.invoke(cli, ["genre", "show", "wedding"])
    assert result.exit_code == 0
    assert "ceremony" in result.output
    assert "music_first" in result.output


def test_genre_current_prints_default():
    runner = CliRunner()
    result = runner.invoke(cli, ["genre", "current"])
    assert result.exit_code == 0
    assert "wedding" in result.output
```

- [ ] **Step 6.4: Run test — confirm it fails**

Run: `pytest tests/test_genre_cli.py -v`
Expected: FAIL — no `genre` command group registered.

- [ ] **Step 6.5: Add path resolution helper that uses genre**

At the top of `src/film_style_analyzer/cli.py`, after the imports, add:

```python
from .genre_pack import GenrePack, load as load_genre_pack, list_available as list_genre_packs

DATA_ROOT = Path.home() / ".film-style-analyzer"


def _genre_paths(genre: str) -> dict[str, Path]:
    """Return the standard file paths for a given genre's workspace."""
    root = DATA_ROOT / genre
    return {
        "root": root,
        "analyses": root / "analyses",
        "thumbs": root / "thumbs",
        "audio": root / "audio",
        "guide": root / "style-guide.md",
        "profile": root / "style-profile.json",
        "stats": root / "aggregate-stats.json",
        "inspirations": root / "inspirations.json",
        "notebooklm_brief": root / "notebooklm-brief.md",
    }


def _resolve_genre(passed: str | None) -> str:
    """Use the flag if given, else the configured default."""
    if passed:
        return passed
    return load_config().default_genre
```

Remove the legacy `ANALYSES_DIR`, `THUMBS_DIR`, `AUDIO_DIR`, `DEFAULT_GUIDE`, `DEFAULT_STATS`, `DEFAULT_PROFILE` module-level constants. Replace every reference to them inside CLI command bodies with `_genre_paths(genre)["analyses"]` etc.

- [ ] **Step 6.6: Add `--genre` flag to every command**

For each command in `cli.py` (`analyze`, `guide`, `compare`, `predict-cuts`, `match`, `tag`, `stats`, `list`, `serve`, `export-notebooklm`), add:

```python
@click.option("--genre", default=None, help="Genre pack to use (default: from config).")
def analyze(..., genre: str | None):
    genre = _resolve_genre(genre)
    pack = load_genre_pack(genre)
    paths = _genre_paths(genre)
    paths["analyses"].mkdir(parents=True, exist_ok=True)
    paths["thumbs"].mkdir(parents=True, exist_ok=True)
    # ... use `pack` and `paths[...]` throughout
```

The earlier-hardcoded `genre_pack.load("wedding")` calls from Tasks 2-5 get replaced with `pack` here.

- [ ] **Step 6.7: Add the `genre` command group**

Append to `cli.py`:

```python
@cli.group()
def genre() -> None:
    """Inspect and manage genre packs."""


@genre.command("list")
def genre_list() -> None:
    """List available genre packs (shipped + user)."""
    from .genre_pack import SHIPPED_PACK_DIR, USER_PACK_DIR
    table = Table(title="Available genre packs")
    table.add_column("Name")
    table.add_column("Source")
    for name in list_genre_packs():
        if (USER_PACK_DIR / f"{name}.toml").exists():
            source = "user override" if (SHIPPED_PACK_DIR / f"{name}.toml").exists() else "user"
        else:
            source = "shipped"
        table.add_row(name, source)
    console.print(table)


@genre.command("show")
@click.argument("name")
def genre_show(name: str) -> None:
    """Print a pack's contents."""
    try:
        pack = load_genre_pack(name)
    except Exception as e:
        raise click.ClickException(str(e))
    console.print(f"[bold]{pack.name}[/bold] — {pack.display_name}")
    console.print(f"scene_detect_threshold: {pack.scene_detect_threshold}")
    console.print(f"min_scene_length_sec: {pack.min_scene_length_sec}")
    console.print(f"audio_emphasis: {pack.audio_emphasis}")
    console.print(f"still_hold_relevant: {pack.still_hold_relevant}")
    console.print(f"duration_range_hint_sec: {pack.duration_range_hint_sec}")
    console.print(f"scene_labels: {', '.join(pack.scene_labels)}")
    console.print(f"shot_labels: {', '.join(pack.shot_labels)}")
    console.print(f"insert_definition: {pack.insert_definition}")
    console.print(f"metadata_keys: {list(pack.metadata_keys.keys())}")


@genre.command("current")
def genre_current() -> None:
    """Print the active genre from config."""
    cfg = load_config()
    console.print(cfg.default_genre)


@genre.command("init")
@click.argument("name")
def genre_init(name: str) -> None:
    """Scaffold a new user pack at ~/.film-style-analyzer/genre_packs/<name>.toml."""
    from .genre_pack import USER_PACK_DIR, SHIPPED_PACK_DIR
    USER_PACK_DIR.mkdir(parents=True, exist_ok=True)
    target = USER_PACK_DIR / f"{name}.toml"
    if target.exists():
        raise click.ClickException(f"already exists: {target}")
    template = (SHIPPED_PACK_DIR / "wedding.toml").read_text()
    header = (
        f"# {name}.toml — user-defined genre pack.\n"
        f"# Edit this file then call: film-style genre show {name}\n"
        f"# Note: name and display_name should reflect your genre.\n\n"
    )
    target.write_text(header + template.replace('name = "wedding"', f'name = "{name}"'))
    console.print(f"[green]wrote {target}[/green]")
```

- [ ] **Step 6.8: Update CLI group docstring**

Replace line 56 of `cli.py`:
```python
    """Analyze finished wedding films and generate an editing style guide."""
```
with:
```python
    """Analyze finished films and generate an editing style guide for any genre (wedding, commercial, brand content, social shorts, music videos, documentary)."""
```

- [ ] **Step 6.9: Add `migrate` command**

Append to `cli.py`:

```python
LEGACY_LAYOUT_FILES = (
    "analyses", "thumbs", "audio",
    "inspirations.json", "aggregate-stats.json",
    "style-profile.json", "style-guide.md", "notebooklm-brief.md",
)


def _legacy_layout_present() -> bool:
    return (DATA_ROOT / "analyses").is_dir()


@cli.command()
@click.option("--to", "to_genre", default=None, help="Genre to migrate legacy data into.")
def migrate(to_genre: str | None) -> None:
    """Move legacy data (~/.film-style-analyzer/{analyses,thumbs,...}) into a per-genre subfolder."""
    import shutil
    if not _legacy_layout_present():
        raise click.ClickException("no legacy layout detected; nothing to migrate.")
    target = to_genre or load_config().default_genre
    paths = _genre_paths(target)
    paths["root"].mkdir(parents=True, exist_ok=True)
    moved = []
    for name in LEGACY_LAYOUT_FILES:
        src = DATA_ROOT / name
        if not src.exists():
            continue
        dst = paths["root"] / name
        if dst.exists():
            console.print(f"[yellow]skip {name} — already exists at {dst}[/yellow]")
            continue
        shutil.move(str(src), str(dst))
        moved.append(name)
    console.print(f"[green]moved {len(moved)} items into {paths['root']}[/green]")
    for m in moved:
        console.print(f"  • {m}")
```

- [ ] **Step 6.10: Add startup migration prompt**

Wrap `cli()` with a precheck. Before any subcommand runs, if `_legacy_layout_present()` AND the subcommand isn't `migrate` itself, print the prompt and either auto-move on `Y` or exit with `n`.

Use a Click callback on the group:

```python
@cli.result_callback()
@click.pass_context
def _post(ctx, result, **kwargs):
    pass  # placeholder; real check goes in a before-invoke hook
```

Better: use a top-level invocation guard inside each command, OR use `cli.invoke` interception. Cleanest: a small helper `_check_migration_or_exit()` called at the top of every non-`migrate`/`genre` command:

```python
def _check_migration_or_exit() -> None:
    if not _legacy_layout_present():
        return
    console.print("[yellow]Detected legacy data layout (analyses/, thumbs/, etc. live at the root).[/yellow]")
    console.print("The new layout partitions by genre.")
    if click.confirm("Move existing data under wedding/?", default=True):
        cli.main(args=["migrate", "--to", "wedding"], standalone_mode=False)
    else:
        raise click.ClickException(
            "Cannot proceed with legacy layout. Run: film-style migrate --to <genre>"
        )
```

Call this at the start of every command except `migrate`, `genre <subcommand>`, and `--version`.

- [ ] **Step 6.11: Update MCP server and dashboard server paths**

In `src/film_style_analyzer/mcp_server.py` lines 26-32, replace the module-level path constants with a function:

```python
def _genre_paths(genre: str) -> dict[str, Path]:
    root = Path.home() / ".film-style-analyzer" / genre
    return {
        "analyses": root / "analyses",
        "thumbs": root / "thumbs",
        "audio": root / "audio",
        "profile": root / "style-profile.json",
        "guide": root / "style-guide.md",
        "stats": root / "aggregate-stats.json",
    }
```

Add a module-level `ACTIVE_GENRE` set at server startup (from env var `FILM_STYLE_GENRE` or config). Update `_safe_stem`, `_load_film`, `_load_all_films`, and the resource URI registrations to use `_genre_paths(ACTIVE_GENRE)`.

Update resource URIs from `film-style://profile`, `film-style://guide`, `film-style://films/{stem}` to:
- `film-style://{genre}/profile`
- `film-style://{genre}/guide`
- `film-style://{genre}/films/{stem}`

Apply equivalent changes to `src/film_style_analyzer/server.py` (dashboard) — accept `--genre` on `serve` and scope all reads to that genre's paths.

- [ ] **Step 6.12: Write migration test**

```python
# tests/test_migration.py
"""Test the legacy → genre-subfolder migration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from film_style_analyzer import cli as cli_mod


def test_migrate_moves_legacy_files(tmp_path, monkeypatch):
    fake_root = tmp_path / ".film-style-analyzer"
    fake_root.mkdir()
    # Lay down legacy files.
    (fake_root / "analyses").mkdir()
    (fake_root / "analyses" / "fake.json").write_text("{}")
    (fake_root / "thumbs").mkdir()
    (fake_root / "style-profile.json").write_text("{}")

    monkeypatch.setattr(cli_mod, "DATA_ROOT", fake_root)

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["migrate", "--to", "wedding"])
    assert result.exit_code == 0, result.output
    assert (fake_root / "wedding" / "analyses" / "fake.json").exists()
    assert (fake_root / "wedding" / "style-profile.json").exists()
    assert not (fake_root / "analyses").exists()
```

- [ ] **Step 6.13: Run all tests**

Run: `pytest -x`
Expected: PASS.

- [ ] **Step 6.14: Commit**

```bash
git add src/film_style_analyzer/cli.py src/film_style_analyzer/config.py src/film_style_analyzer/mcp_server.py src/film_style_analyzer/server.py tests/test_genre_cli.py tests/test_migration.py tests/
git commit -m "feat: --genre flag, genre command group, per-genre data layout, migrate"
```

---

## Task 7: Author the five new genre packs

**Files:**
- Create: `src/film_style_analyzer/genre_packs/commercial.toml`
- Create: `src/film_style_analyzer/genre_packs/brand_content.toml`
- Create: `src/film_style_analyzer/genre_packs/social_short.toml`
- Create: `src/film_style_analyzer/genre_packs/music_video.toml`
- Create: `src/film_style_analyzer/genre_packs/documentary.toml`
- Modify: `tests/test_genre_pack.py` (parametrized validation)

- [ ] **Step 7.1: Write parametrized test that loads all shipped packs**

Append to `tests/test_genre_pack.py`:

```python
import pytest


@pytest.mark.parametrize("name", [
    "wedding", "commercial", "brand_content",
    "social_short", "music_video", "documentary",
])
def test_all_shipped_packs_load(name):
    pack = genre_pack.load(name)
    assert pack.name == name
    assert pack.display_name
    assert pack.scene_labels
    assert pack.shot_labels
    assert pack.audio_emphasis in {
        "music_first", "voiceover_first", "beat_locked",
        "interview", "hook_driven",
    }
    # No duplicate labels.
    assert len(pack.scene_labels) == len(set(pack.scene_labels))
    assert len(pack.shot_labels) == len(set(pack.shot_labels))
    # Required prompts.
    for key in ("guide_writer_system", "chapter_classify_system",
                "shot_classify_system", "gemini_film_prompt",
                "gemini_youtube_prompt", "mcp_edit_in_style",
                "notebooklm_brief_intro"):
        assert key in pack.prompts
```

- [ ] **Step 7.2: Run test — confirm it fails for the five new packs**

Run: `pytest tests/test_genre_pack.py::test_all_shipped_packs_load -v`
Expected: FAIL for commercial, brand_content, social_short, music_video, documentary (file not found).

- [ ] **Step 7.3: Author `commercial.toml`**

```toml
# src/film_style_analyzer/genre_packs/commercial.toml
name = "commercial"
display_name = "commercial"
scene_detect_threshold = 14.0
min_scene_length_sec = 0.3
audio_emphasis = "voiceover_first"
still_hold_relevant = false
duration_range_hint_sec = [6.0, 120.0]

scene_labels = [
    "hook", "product_reveal", "lifestyle", "demo", "talking_head",
    "cta", "logo", "kicker", "establishing", "transition", "other",
]

shot_labels = [
    "extreme_wide", "wide", "medium_wide", "medium", "medium_close",
    "close_up", "extreme_close", "insert", "over_shoulder", "aerial", "other",
]

insert_definition = "a detail of an object or screen content (product detail, typography, screen UI, brand mark, packaging close-up)"

[metadata_keys]
client = []
product_category = ["consumer_electronics", "auto", "fashion", "fmcg", "beauty", "finance", "tech_b2b", "food_drink", "service"]
placement = ["broadcast_30", "broadcast_15", "youtube_pre_roll", "social_in_feed", "out_of_home", "long_form", "other"]
length_class = ["6s", "15s", "30s", "60s", "90s_plus"]
campaign_tone = ["aspirational", "humor", "informational", "emotional", "performance", "brand"]

[prompts]
chapter_classify_system = """You are labeling shots from a finished commercial. Each image is the middle frame of one chapter. Label each chapter with exactly one of:
{scene_labels}

A 'hook' is the opening grab. 'product_reveal' is the moment the product is first clearly shown. 'cta' is a direct call-to-action (URL, offer, action verb). 'kicker' is the brand-level closing beat after the cta.

Return JSON: {{"labels": ["label1", ...]}} in image order. Use 'other' only if nothing fits."""

shot_classify_system = """You are labeling shots from a commercial by composition. Each image is the middle frame of one shot. For each image, output exactly one of:
{shot_labels}

Definitions:
- extreme_wide: landscape / location with subjects tiny.
- wide: full body, full set/environment.
- medium_wide: waist-up, two-shot.
- medium: mid-thigh up.
- medium_close: chest up.
- close_up: head and shoulders.
- extreme_close: face only / eyes / hands / single product detail.
- insert: {insert_definition}.
- over_shoulder: framed past someone's shoulder.
- aerial: drone / overhead.
- other: cannot tell.

Return JSON: {{"labels": ["label1", ...]}} in image order."""

guide_writer_system = """You are helping a commercial editor document their cutting style.
You will receive detailed statistical analysis of finished commercials they've edited.
Write a comprehensive editing style guide in markdown that a junior editor (or an AI rough cut assembler) could follow to produce edits that match this editor's style.

Be extremely specific. Use exact numbers from the data. Write rules, not descriptions. For example: "Hook lands within 0.8 seconds, never longer than 1.2 seconds" beats vague language.

Structure the guide around the commercial spine: hook → product reveal → demo/lifestyle → CTA → kicker. Quantify how long each beat runs, what shot sizes dominate where, and how voiceover lines up with picture.

If the data includes a `scene_breakdown`, produce a per-beat rules table. If it includes `audio` and `transcript`, produce explicit voiceover/music timing rules. If it includes `gemini_analyses`, weave specific distinctive choices into the guide.

Do not use the words: stunning, magical, seamless, breathtaking, cinematic, captivating, mesmerizing, or any similar filler."""

gemini_film_prompt = """You are analyzing a finished commercial to extract the editor's style.
This piece is {duration} long with {cuts} cuts.

Answer these questions precisely:

1. HOOK: What happens in the first 3 seconds? Identify the exact moment intended to stop a viewer scrolling. How is it shot?

2. PRODUCT REVEAL: When does the product first appear cleanly on screen? How is it framed?

3. PACING ARC: Map cut frequency across the runtime. Where does it accelerate, where does it breathe?

4. VOICEOVER vs PICTURE: How does VO line up with cuts — does picture lead VO, or VO lead picture? When does the VO start?

5. SHOT SELECTION: Mix of wides/mediums/inserts. How often do inserts cut to product/screen content?

6. CTA: When does the CTA enter? How long does it hold? On-screen text vs voiceover vs both?

7. CLOSING / KICKER: How does the spot end — logo lockup duration, music tail, fade behavior?

8. DISTINCTIVE CHOICES: Three things that make this editor's commercial work recognizable.

Respond in structured JSON with one key per question:
{{"hook": ..., "product_reveal": ..., "pacing_arc": ..., "voiceover_vs_picture": ..., "shot_selection": ..., "cta": ..., "closing_kicker": ..., "distinctive_choices": [...]}}"""

gemini_youtube_prompt = """You are analyzing a commercial on YouTube to extract its editorial style.

Answer:

1. HOOK: First 3 seconds — what stops the scroll?
2. PACING: Cut frequency arc. Where does it accelerate?
3. SHOT SELECTION: Wide/medium/close mix. Insert frequency.
4. AUDIO DESIGN: Voiceover entry, music role, sound design accents.
5. COLOR / GRADE: Tonal approach.
6. STRUCTURE: Hook → reveal → demo → CTA mapping.
7. DISTINCTIVE CHOICES: Three signature moves.
8. RELEVANCE: How might this style translate to the user's commercial work?

Respond in structured JSON: hook, pacing, shot_selection, audio_design, color_grade, structure, distinctive_choices (array), relevance."""

mcp_edit_in_style = """You are assembling a rough cut in {brand_name}'s commercial-editing style. Use the loaded style profile and guide as your reference; cite specific rules when you make a cut decision."""

notebooklm_brief_intro = """This brief summarizes the commercial-editing style of {brand_name}, derived from {n} analyzed commercials. Use it as a reference when discussing edit choices, planning new spots, or training assistants on this style."""
```

- [ ] **Step 7.4: Author `brand_content.toml`**

Same structure as commercial.toml but with these distinct values:
- `name = "brand_content"`, `display_name = "brand content piece"`
- `scene_detect_threshold = 10.0`, `min_scene_length_sec = 0.4`
- `audio_emphasis = "interview"`, `still_hold_relevant = false`
- `duration_range_hint_sec = [60.0, 300.0]`
- `scene_labels = ["interview", "b_roll", "title_card", "product_inset", "location", "archival", "establishing", "transition", "other"]`
- Shot labels same as commercial.
- `insert_definition = "a detail of an object or environment used as a cutaway during interview audio (product detail, hand-held object, location signage, archival paper)"`
- `metadata_keys`: `subject_type` (`["founder","employee","customer","expert","partner"]`), `format` (`["short_doc","case_study","employer_brand","product_story","mini_doc"]`), `length_class` (`["60s","2m","3_5m","5m_plus"]`), `interview_count` (`["one","two","three_plus"]`).
- Prompts: scene labels emphasize interview/b-roll structure. Audio emphasis "interview". Guide writer prompt frames around interview-driven brand stories.

- [ ] **Step 7.5: Author `social_short.toml`**

Distinct values:
- `name = "social_short"`, `display_name = "social short"`
- `scene_detect_threshold = 16.0`, `min_scene_length_sec = 0.2`
- `audio_emphasis = "hook_driven"`, `still_hold_relevant = false`
- `duration_range_hint_sec = [7.0, 90.0]`
- `scene_labels = ["hook", "payoff", "transition", "text_overlay", "jump_cut", "reveal", "cta", "establishing", "other"]`
- Shot labels same as commercial.
- `insert_definition = "a fast cutaway detail or text-on-screen card (typography, on-screen caption, product detail, screen recording inset)"`
- `metadata_keys`: `platform` (`["tiktok","instagram_reels","youtube_shorts","x","linkedin"]`), `format` (`["talking_head","trend","tutorial","ugc","skit","listicle"]`), `aspect_ratio` (`["9_16","1_1","16_9"]`), `length_class` (`["7_15s","16_30s","31_60s","61_90s"]`).
- Prompts emphasize hook-in-3-frames, jump cuts, on-screen text density.

- [ ] **Step 7.6: Author `music_video.toml`**

Distinct values:
- `name = "music_video"`, `display_name = "music video"`
- `scene_detect_threshold = 12.0`, `min_scene_length_sec = 0.25`
- `audio_emphasis = "beat_locked"`, `still_hold_relevant = false`
- `duration_range_hint_sec = [120.0, 360.0]`
- `scene_labels = ["performance", "narrative", "abstract", "transition", "lipsync", "vfx", "establishing", "other"]`
- Shot labels same.
- `insert_definition = "a styling, prop, or texture detail used as visual punctuation between performance shots (instrument detail, fabric, lighting effect, environment texture)"`
- `metadata_keys`: `genre_music` (`["pop","hip_hop","rnb","rock","indie","electronic","country","latin","jazz","classical"]`), `format` (`["performance","narrative","hybrid","lyric","visualizer"]`), `length_class` (`["under_3m","3_4m","4_5m","5m_plus"]`).
- Prompts emphasize beat-locked cutting, lipsync vs narrative intercut, performance staging.

- [ ] **Step 7.7: Author `documentary.toml`**

Distinct values:
- `name = "documentary"`, `display_name = "documentary"`
- `scene_detect_threshold = 7.0`, `min_scene_length_sec = 0.6`
- `audio_emphasis = "interview"`, `still_hold_relevant = false`
- `duration_range_hint_sec = [180.0, 1800.0]`
- `scene_labels = ["interview", "b_roll", "archival", "establishing", "title_card", "verite", "recreation", "transition", "other"]`
- Shot labels same.
- `insert_definition = "a detail used as a cutaway under interview/narration (archival document, environmental detail, hand-held object, location signage)"`
- `metadata_keys`: `subject_type` (`["personal","historical","investigative","nature","sports","cultural","crime"]`), `interview_count` (`["one","few","many","none"]`), `archival_use` (`["heavy","moderate","minimal","none"]`), `release_format` (`["short_doc","feature","series_episode","theatrical"]`).
- Prompts emphasize interview pacing, b-roll cadence, archival integration.

- [ ] **Step 7.8: Run pack-loading tests**

Run: `pytest tests/test_genre_pack.py -v`
Expected: PASS for all six packs.

- [ ] **Step 7.9: Sanity-check audio_emphasis branches in profile_writer**

Add a test:

```python
# tests/test_profile_writer_genre.py — append
import pytest

@pytest.mark.parametrize("genre,emphasis", [
    ("commercial", "voiceover_first"),
    ("brand_content", "interview"),
    ("social_short", "hook_driven"),
    ("music_video", "beat_locked"),
    ("documentary", "interview"),
])
def test_each_genre_emits_appropriate_audio_rule(genre, emphasis):
    pack = genre_pack.load(genre)
    assert pack.audio_emphasis == emphasis
    aggregated = {
        "transitions": {"hard_cut_pct": 90, "dissolve_pct": 10},
        "audio": {
            "first_speech_at_pct_avg": 5,
            "first_speech_at_sec_avg": 1.2,
            "speech_over_music_pct_avg": 60,
        },
    }
    profile = build_profile([], aggregated, pack=pack)
    rules = " ".join(profile.get("rules", []))
    # Each genre should NOT emit the "music_first" rule.
    assert "Hold music alone" not in rules
```

Run: `pytest tests/test_profile_writer_genre.py -v`
Expected: PASS.

- [ ] **Step 7.10: Commit**

```bash
git add src/film_style_analyzer/genre_packs/ tests/test_genre_pack.py tests/test_profile_writer_genre.py
git commit -m "feat: add commercial, brand_content, social_short, music_video, documentary packs"
```

---

## Task 8: Update README, ARCHITECTURE.md, dashboard, and pyproject metadata

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `pyproject.toml` (description, keywords)
- Modify: `src/film_style_analyzer/static/index.html` and JS (genre dropdown)
- Modify: `src/film_style_analyzer/notebooklm_export.py` (lines 1-60: docstring + intro generation)

- [ ] **Step 8.1: Update `pyproject.toml` metadata**

Replace lines 8 and 12 of `pyproject.toml`:

```toml
description = "Analyze finished films across genres (wedding, commercial, brand content, social shorts, music videos, documentary) and generate per-genre editing style guides"
...
keywords = ["video", "editing", "style-transfer", "mcp", "claude", "gemini", "wedding-film", "commercial", "music-video", "documentary"]
```

- [ ] **Step 8.2: Update `README.md` opening**

Read current README. Replace the opening section (top heading + first paragraph) so the project leads with multi-genre framing, then mentions wedding as one of the shipped packs. Add a "Genres" section listing all six packs and their differing thresholds/emphasis. Add a `--genre` example for `analyze`. Add `film-style genre list` example.

Keep the existing wedding-specific examples but mark them as illustrative for one genre.

- [ ] **Step 8.3: Update `ARCHITECTURE.md`**

Read current file. Add a new section between the existing module overview and the data flow:

```markdown
## Genre Packs

The pipeline math (scene detection, color analysis, audio classification,
beat tracking) is genre-agnostic. The vocabulary, prompts, and tuned
defaults are not — they live in **genre packs** (TOML files in
`src/film_style_analyzer/genre_packs/`).

Each pack is loaded via `genre_pack.load(name)` and threaded as an
explicit argument through `analyzer.analyze_film`, `vision_classify`,
`shot_size`, `metadata.curated_keys`, `guide_writer.write_guide`,
`gemini_analyzer.analyze`, `notebooklm_export`, and the MCP server.

Workspaces partition by genre: `~/.film-style-analyzer/<genre>/{analyses,
thumbs,audio,style-profile.json,...}`. Users author custom packs at
`~/.film-style-analyzer/genre_packs/<name>.toml`; user packs override
shipped packs of the same name.
```

- [ ] **Step 8.4: Update dashboard masthead**

Read `src/film_style_analyzer/static/index.html` (or main JS). Add a header element showing the active genre — e.g. `<span class="genre-badge">{{ genre }}</span>`. The server (`server.py`, modified in Task 6) injects the active genre into the page's data. No genre-switcher dropdown for now (out of scope per spec — single-genre per workspace, toggled via CLI).

If the dashboard reads `/api/...` JSON endpoints, update them to include `genre` and `genre_display_name` in their responses (sourced from the loaded profile).

- [ ] **Step 8.5: Run full test suite**

Run: `pytest`
Expected: PASS.

- [ ] **Step 8.6: Smoke-test the CLI end-to-end (no-real-media)**

Run: `python -m film_style_analyzer.cli genre list`
Expected: table listing all six packs with source = "shipped".

Run: `python -m film_style_analyzer.cli genre show commercial`
Expected: prints commercial pack's threshold (14.0), audio emphasis (voiceover_first), labels, etc.

Run: `python -m film_style_analyzer.cli genre current`
Expected: prints `wedding` (the configured default).

- [ ] **Step 8.7: Commit**

```bash
git add README.md ARCHITECTURE.md pyproject.toml src/film_style_analyzer/static/ src/film_style_analyzer/server.py src/film_style_analyzer/notebooklm_export.py
git commit -m "docs: README/ARCHITECTURE for multi-genre; dashboard genre badge"
```

---

## Self-review notes

- **Spec coverage:** Tasks 1-8 map to spec build-sequence steps 1-9. Step 9 (dashboard genre dropdown) is reduced to a genre badge in Task 8 — the spec calls for a "dropdown" but per the one-genre-per-workspace decision, the active genre is selected at boot via CLI flag, not at runtime in the browser. A badge accurately reflects the chosen architecture; if the user wants in-browser switching, that's a follow-up.
- **Type/name consistency:** `pack` is the consistent argument name everywhere; `GenrePack` is the type. `_genre_paths(genre)` is the consistent helper name in both `cli.py` and `mcp_server.py`. `load_genre_pack` is the import alias for `genre_pack.load` in `cli.py` to avoid shadowing.
- **Placeholder scan:** Task 7 steps 7.4-7.7 describe deltas instead of full files (the toml structure is identical to commercial.toml save for the listed fields). This is a deliberate compression — the engineer can copy commercial.toml and apply the delta. If you want every pack inlined verbatim, expand those steps before execution.
- **Migration safety:** The startup migration prompt is interactive (Y/n). `migrate` command is idempotent (skips files that already exist at destination).
- **Schema stability:** `genre`, `genre_display_name`, `genre_extensions` are additive. Existing top-level keys in `style-profile.json` are unchanged. Downstream consumers ignore unknown fields and keep working.
