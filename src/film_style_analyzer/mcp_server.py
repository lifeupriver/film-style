"""MCP server — exposes the analyzer's data and operations to Claude Desktop
(and any other MCP client) over stdio.

Tools and resources are organized so that a Claude conversation can:

  1. Read the editor's style profile + markdown guide as context
     (via resources film-style://profile and film-style://guide).
  2. List and inspect individual films in the archive.
  3. Find stylistically similar films (matchmaker).
  4. Tag films with metadata; correct chapter labels (the dashboard's
     correction loop, available from chat).
  5. Compare a rough-cut FCPXML against the profile.
  6. Predict cut points for a song given the profile (heaviest tool —
     requires librosa).

Run via:  film-style mcp-serve
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_ROOT = Path.home() / ".film-style-analyzer"


def _active_genre() -> str:
    """Read the active genre from config. Falls back to 'wedding'.

    Resolved per-call (not frozen at import) so a genre switch mid-session is
    honored — writes and pack-based validation must target the SAME genre.
    """
    try:
        from .config import load as _load
        return getattr(_load(), "default_genre", "wedding")
    except Exception:
        return "wedding"


# Per-call path resolvers. The genre root is re-resolved on every call so a
# config genre switch immediately repoints reads/writes; the module-level
# constants below are only an import-time snapshot kept for back-compat and
# tests (which reload the module after pointing HOME at a temp dir).
def _genre_root() -> Path:
    return DATA_ROOT / _active_genre()


def _analyses_dir() -> Path:
    return _genre_root() / "analyses"


def _thumbs_dir() -> Path:
    return _genre_root() / "thumbs"


def _audio_dir() -> Path:
    return _genre_root() / "audio"


def _profile_path() -> Path:
    return _genre_root() / "style-profile.json"


def _guide_path() -> Path:
    return _genre_root() / "style-guide.md"


def _stats_path() -> Path:
    return _genre_root() / "aggregate-stats.json"


_GENRE_ROOT = _genre_root()
ANALYSES_DIR = _GENRE_ROOT / "analyses"
THUMBS_DIR = _GENRE_ROOT / "thumbs"
AUDIO_DIR = _GENRE_ROOT / "audio"
PROFILE_PATH = _GENRE_ROOT / "style-profile.json"
GUIDE_PATH = _GENRE_ROOT / "style-guide.md"
STATS_PATH = _GENRE_ROOT / "aggregate-stats.json"

SUPPORTED_VIDEO = {".mp4", ".mov", ".m4v", ".mkv"}


class MCPServerError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Pure helpers — testable without an MCP runtime.
# ---------------------------------------------------------------------------

def _safe_stem(stem: str) -> str:
    """Reject anything that could traverse out of the analyses dir, while
    still accepting the real filenames the import pipeline produces — spaces,
    brackets, ampersands, unicode word chars, etc.

    The old allow-list (`^[A-Za-z0-9._\\-]+$`) rejected those exact filenames,
    locking imported films out of every stem-based tool. We instead deny the
    handful of things that actually enable traversal:
      - path separators (`/`, `\\`)
      - parent-dir refs (`..`)
      - empty / whitespace-only / dot-only names
      - control characters (incl. NUL)
    """
    if not isinstance(stem, str) or not stem.strip():
        raise MCPServerError(f"invalid film stem: {stem!r}")
    if "/" in stem or "\\" in stem:
        raise MCPServerError(f"invalid film stem: {stem!r}")
    if ".." in stem:
        raise MCPServerError(f"invalid film stem: {stem!r}")
    if stem.strip(". ") == "":  # ".", "..", "…" etc — dot/space-only
        raise MCPServerError(f"invalid film stem: {stem!r}")
    if any(ord(c) < 32 for c in stem):
        raise MCPServerError(f"invalid film stem: {stem!r}")
    return stem


def _load_film(stem: str) -> "FilmAnalysis":
    from .schemas import FilmAnalysis
    path = _analyses_dir() / f"{_safe_stem(stem)}.json"
    if not path.is_file():
        raise MCPServerError(f"no analysis at {path}")
    return FilmAnalysis.model_validate_json(path.read_text())


def _load_all_films() -> list["FilmAnalysis"]:
    from .schemas import FilmAnalysis
    analyses_dir = _analyses_dir()
    if not analyses_dir.exists():
        return []
    out: list[FilmAnalysis] = []
    for p in sorted(analyses_dir.glob("*.json")):
        try:
            out.append(FilmAnalysis.model_validate_json(p.read_text()))
        except Exception as e:
            # A silently dropped analysis shrinks the corpus without any
            # signal — surface it so the operator can spot a bad/stale file.
            logger.warning("skipping unreadable analysis %s: %s", p, e)
            continue
    return out


def _film_summary(a) -> dict[str, Any]:
    from pathlib import Path as _Path
    return {
        "stem": _Path(a.film.filename).stem,
        "filename": a.film.filename,
        "duration_sec": a.film.duration_sec,
        "clip_count": a.cuts.total,
        "avg_clip_sec": a.pacing.avg_clip_duration_sec,
        "metadata": a.metadata or {},
        "has_color": a.color is not None,
        "has_audio": a.audio is not None,
        "has_music": a.music is not None,
        "has_vision": any(c.label for c in a.chapters),
    }


# ---------------------------------------------------------------------------
# Tool implementations — pure functions returning dicts/strings.
# ---------------------------------------------------------------------------

def tool_list_films() -> dict[str, Any]:
    """Return summaries of every analyzed film in the archive."""
    films = _load_all_films()
    return {
        "film_count": len(films),
        "films": [_film_summary(a) for a in films],
    }


def tool_get_film(stem: str) -> dict[str, Any]:
    """Return the full analysis JSON for one film. STEM is the filename
    without extension (e.g. 'sarah-and-mike-gather-greene')."""
    a = _load_film(stem)
    return json.loads(a.model_dump_json())


def tool_get_style_profile() -> dict[str, Any]:
    """Return the typed style-profile.json — the canonical artifact for
    editing in this filmmaker's style. Contains pacing, transitions, audio,
    color, shot mix, music, scene rules, plus a human-readable rules array."""
    profile_path = _profile_path()
    if not profile_path.is_file():
        raise MCPServerError(
            f"{profile_path} does not exist. Run `film-style guide` first."
        )
    return json.loads(profile_path.read_text())


def tool_get_style_guide() -> str:
    """Return the markdown style guide. Pair with get_style_profile() for
    full coverage — the guide is for reading, the profile is for parsing."""
    guide_path = _guide_path()
    if not guide_path.is_file():
        raise MCPServerError(
            f"{guide_path} does not exist. Run `film-style guide` first."
        )
    return guide_path.read_text()


def tool_get_aggregate_stats() -> dict[str, Any]:
    """Return aggregate statistics across all analyzed films."""
    from .aggregator import aggregate
    return aggregate(_load_all_films())


def tool_find_similar_films(stem: str, top: int = 3) -> dict[str, Any]:
    """Find films in the archive most stylistically similar to STEM.
    Useful when assembling a new wedding edit — load the most similar prior
    work as a tighter reference than the corpus average."""
    from .matchmaker import biggest_differences, find_similar
    target = _load_film(stem)
    archive = _load_all_films()
    matches = find_similar(target, archive, top_n=max(1, min(20, top)))
    # Augment each match with biggest-difference dimensions.
    for m in matches:
        other = next((f for f in archive if f.film.filename == m["filename"]), None)
        if other:
            m["biggest_differences"] = biggest_differences(target, other, top_n=4)
    return {"target": stem, "matches": matches}


def tool_set_film_metadata(stem: str, metadata: dict[str, str | None]) -> dict[str, Any]:
    """Merge metadata onto a film. Use null/None values to delete keys.

    Supported curated keys (free-form values also allowed):
      venue, season, time_of_day, ceremony, guest_count, music_genre,
      weather, duration_target.
    """
    from .metadata import merge as merge_md
    a = _load_film(stem)
    a.metadata = merge_md(a.metadata, metadata)
    target_path = _analyses_dir() / f"{_safe_stem(stem)}.json"
    target_path.write_text(a.model_dump_json(indent=2))
    return {"stem": stem, "metadata": a.metadata}


def _active_pack():
    """Resolve the active genre pack for label validation. Reads the same
    active genre as `_genre_root()` so validation and writes stay in lockstep
    after a genre switch."""
    from .genre_pack import load as _load_pack
    return _load_pack(_active_genre())


def tool_get_unlabeled_chapter_thumbnails(stem: str, max_chapters: int = 12) -> dict[str, Any]:
    """Return file-path metadata for up to `max_chapters` unlabeled chapter
    thumbnails. The MCP wrapper turns this into a list of image content
    blocks Claude can see; callers without MCP image support still get the
    paths and can read them with their own tools."""
    a = _load_film(stem)
    genre_root = _genre_root()
    pending = [c for c in a.chapters if not c.label and c.representative_thumbnail]
    batch = pending[:max_chapters]
    return {
        "stem": stem,
        "chapters": [
            {
                "chapter_index": c.index,
                "start_sec": c.start_sec,
                "end_sec": c.end_sec,
                "duration_sec": c.duration_sec,
                # Thumbnails are stored relative to the GENRE root, not
                # DATA_ROOT — joining against DATA_ROOT drops the genre
                # segment and yields a nonexistent path.
                "thumbnail_path": str((genre_root / c.representative_thumbnail).resolve()),
            }
            for c in batch
        ],
        "remaining_after_batch": max(0, len(pending) - len(batch)),
        "valid_labels": list(_active_pack().scene_labels),
    }


def tool_set_chapter_labels_bulk(stem: str, labels: dict) -> dict[str, Any]:
    """Apply chapter labels in bulk. `labels` maps chapter_index → label
    (or None to clear). Invalid labels are recorded in `skipped` and don't
    abort the rest of the batch."""
    # NOTE: this (and the other set_*_bulk / set_*_label / metadata tools) is
    # an unsynchronized read-modify-write on the analysis JSON — two concurrent
    # writers to the same film can clobber each other's changes. Acceptable for
    # the single-client MCP usage today; revisit with file locking if the
    # server ever fans out to concurrent callers.
    a = _load_film(stem)
    valid = set(_active_pack().scene_labels)
    written = 0
    skipped: list[dict] = []
    for idx_key, label in labels.items():
        try:
            idx = int(idx_key)
        except (TypeError, ValueError):
            skipped.append({"index": idx_key, "reason": "non-integer key"})
            continue
        if idx < 0 or idx >= len(a.chapters):
            skipped.append({"index": idx, "reason": f"out of range (have {len(a.chapters)})"})
            continue
        if label is not None:
            label = str(label).strip().lower().replace(" ", "_")
            if label not in valid:
                skipped.append({"index": idx, "reason": f"invalid label {label!r}"})
                continue
        a.chapters[idx].label = label
        written += 1
    target = _analyses_dir() / f"{_safe_stem(stem)}.json"
    target.write_text(a.model_dump_json(indent=2))
    return {
        "stem": stem,
        "labels_applied": written,
        "skipped": skipped,
        "remaining_unlabeled": sum(1 for c in a.chapters if not c.label),
    }


def tool_get_unlabeled_clip_thumbnails(stem: str, start_index: int = 0,
                                        batch_size: int = 12) -> dict[str, Any]:
    """Return paths for up to `batch_size` unlabeled clip thumbnails starting
    from `start_index` (clip index, not list position). Used for shot-size
    labeling."""
    a = _load_film(stem)
    genre_root = _genre_root()
    pending = [c for c in a.cuts.clips
               if not c.shot_size and c.thumbnail and c.index >= start_index]
    batch = pending[:batch_size]
    return {
        "stem": stem,
        "clips": [
            {
                "clip_index": c.index,
                "start_sec": c.start_sec,
                "end_sec": c.end_sec,
                "duration_sec": c.duration_sec,
                # Relative to the genre root (see chapter-thumbnail note).
                "thumbnail_path": str((genre_root / c.thumbnail).resolve()),
            }
            for c in batch
        ],
        "remaining_after_batch": max(
            0,
            sum(1 for c in a.cuts.clips if not c.shot_size and c.thumbnail) - len(batch),
        ),
        "valid_shot_labels": list(_active_pack().shot_labels),
    }


def tool_set_shot_sizes_bulk(stem: str, sizes: dict) -> dict[str, Any]:
    """Apply per-clip shot sizes in bulk. `sizes` maps clip_index → shot
    label (or None to clear)."""
    a = _load_film(stem)
    valid = set(_active_pack().shot_labels)
    written = 0
    skipped: list[dict] = []
    for idx_key, sz in sizes.items():
        try:
            idx = int(idx_key)
        except (TypeError, ValueError):
            skipped.append({"index": idx_key, "reason": "non-integer key"})
            continue
        if idx < 0 or idx >= len(a.cuts.clips):
            skipped.append({"index": idx, "reason": f"out of range (have {len(a.cuts.clips)})"})
            continue
        if sz is not None:
            sz = str(sz).strip().lower().replace(" ", "_")
            if sz not in valid:
                skipped.append({"index": idx, "reason": f"invalid shot label {sz!r}"})
                continue
        a.cuts.clips[idx].shot_size = sz
        written += 1
    target = _analyses_dir() / f"{_safe_stem(stem)}.json"
    target.write_text(a.model_dump_json(indent=2))
    return {
        "stem": stem,
        "sizes_applied": written,
        "skipped": skipped,
        "remaining_unlabeled": sum(1 for c in a.cuts.clips if not c.shot_size),
    }


def tool_get_undescribed_clip_thumbnails(stem: str, start_index: int = 0,
                                           batch_size: int = 8) -> dict[str, Any]:
    """Return paths for up to `batch_size` clips that DO NOT yet have a
    shot_description, starting at clip index `start_index`. Used by Claude
    Desktop's describe-clips workflow."""
    a = _load_film(stem)
    genre_root = _genre_root()
    pending = [c for c in a.cuts.clips
               if c.shot_description is None and c.thumbnail and c.index >= start_index]
    batch = pending[:batch_size]
    return {
        "stem": stem,
        "clips": [
            {
                "clip_index": c.index,
                "start_sec": c.start_sec,
                "end_sec": c.end_sec,
                "duration_sec": c.duration_sec,
                "shot_size": c.shot_size,
                # Relative to the genre root (see chapter-thumbnail note).
                "thumbnail_path": str((genre_root / c.thumbnail).resolve()),
            }
            for c in batch
        ],
        "remaining_after_batch": max(
            0,
            sum(1 for c in a.cuts.clips
                if c.shot_description is None and c.thumbnail) - len(batch),
        ),
        # NOTE: these controlled vocabularies are wedding-specific. Unlike
        # scene_labels / shot_labels (sourced from the active pack), the genre
        # packs ship no shot-description vocabulary field, so there is nothing
        # pack-backed to wire this to yet; it stays wedding-default until such
        # a field is added to GenrePack.
        "schema_hint": {
            "subjects": ["bride", "groom", "couple", "wedding_party",
                         "officiant", "parents", "family", "kids", "guests",
                         "details_only"],
            "setting": ["altar", "aisle", "lawn", "garden", "dance_floor",
                        "tent", "ballroom", "ceremony_seating",
                        "getting_ready_room", "reception_table", "hallway",
                        "exterior_landscape", "interior_other", "vehicle"],
            "lighting": ["golden_hour", "natural_daylight", "overcast",
                         "candle", "warm_indoor", "mixed_indoor",
                         "dim_indoor", "uplighting_warm", "uplighting_cool",
                         "dance_floor", "night_exterior"],
            "camera": ["locked", "slight_handheld", "handheld", "push_in",
                       "pull_back", "pan", "tilt", "gimbal_walk", "drone",
                       "rack_focus", "slow_motion"],
            "mood": ["tender", "joyful", "ceremonial", "intimate", "candid",
                     "kinetic", "still", "anticipatory", "celebratory"],
            "action": "short imperative phrase, e.g. 'embracing', "
                      "'walking down aisle', 'looking down at flowers'",
            "description": "one short free-form sentence",
        },
    }


def tool_set_clip_descriptions_bulk(stem: str, descriptions: dict) -> dict[str, Any]:
    """Apply many clip shot_descriptions at once. `descriptions` maps
    clip_index (int) → ShotDescription dict (or None to clear). Each value
    is validated as a ShotDescription pydantic model."""
    from .schemas import ShotDescription
    a = _load_film(stem)
    written = 0
    skipped: list[dict] = []
    for idx_key, payload in descriptions.items():
        try:
            idx = int(idx_key)
        except (TypeError, ValueError):
            skipped.append({"index": idx_key, "reason": "non-integer key"})
            continue
        if idx < 0 or idx >= len(a.cuts.clips):
            skipped.append({"index": idx, "reason": f"out of range (have {len(a.cuts.clips)})"})
            continue
        if payload is None:
            a.cuts.clips[idx].shot_description = None
            written += 1
            continue
        try:
            sd = ShotDescription.model_validate(payload)
        except Exception as e:
            skipped.append({"index": idx, "reason": f"invalid payload: {e}"})
            continue
        a.cuts.clips[idx].shot_description = sd
        written += 1
    target = _analyses_dir() / f"{_safe_stem(stem)}.json"
    target.write_text(a.model_dump_json(indent=2))
    return {
        "stem": stem,
        "descriptions_applied": written,
        "skipped": skipped,
        "remaining_undescribed": sum(
            1 for c in a.cuts.clips
            if c.shot_description is None and c.thumbnail
        ),
    }


def tool_set_chapter_label(stem: str, chapter_index: int,
                           label: str | None) -> dict[str, Any]:
    """Correct a chapter's scene label. The vision pass uses these
    corrections as few-shot examples on subsequent runs.

    Pass label=None to clear an existing label.
    """
    a = _load_film(stem)
    if chapter_index < 0 or chapter_index >= len(a.chapters):
        raise MCPServerError(
            f"chapter_index {chapter_index} out of range "
            f"(film has {len(a.chapters)} chapters)"
        )
    if label is not None:
        label = str(label).strip().lower().replace(" ", "_") or None
    # Enforce the same genre-pack validation the bulk tool applies — a single
    # write must not be able to slip an invalid label into the corpus.
    if label is not None:
        valid = set(_active_pack().scene_labels)
        if label not in valid:
            raise MCPServerError(
                f"invalid label {label!r} for the active genre; "
                f"valid labels: {sorted(valid)}"
            )
    a.chapters[chapter_index].label = label
    target_path = _analyses_dir() / f"{_safe_stem(stem)}.json"
    target_path.write_text(a.model_dump_json(indent=2))
    return {
        "stem": stem,
        "chapter_index": chapter_index,
        "label": a.chapters[chapter_index].label,
    }


def tool_compare_fcpxml(fcpxml_content: str | None = None,
                        fcpxml_path: str | None = None) -> dict[str, Any]:
    """Compare a rough-cut FCPXML against the established style profile.

    Pass either fcpxml_content (the XML as a string) OR fcpxml_path (a
    filesystem path). Returns a deviation report with per-decile pacing
    drift and concrete suggestions.
    """
    import tempfile
    from .fcpxml_parser import parse as parse_fcpxml
    from .server import _build_compare_report

    if not fcpxml_content and not fcpxml_path:
        raise MCPServerError("provide either fcpxml_content or fcpxml_path")
    if fcpxml_content:
        with tempfile.NamedTemporaryFile(suffix=".fcpxml", delete=False, mode="w") as tmp:
            tmp.write(fcpxml_content)
            tmp_path = Path(tmp.name)
        try:
            cut = parse_fcpxml(tmp_path)
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass
    else:
        p = Path(fcpxml_path).expanduser()
        if not p.is_file():
            raise MCPServerError(f"file not found: {p}")
        cut = parse_fcpxml(p)

    profile = tool_get_aggregate_stats()
    return _build_compare_report(cut, profile)


# ---------------------------------------------------------------------------
# Execute-tools — these *do* things (analyze, import, generate). Long-running
# by nature, so we keep the API surface minimal and return a structured result.
# ---------------------------------------------------------------------------

def _contained_write_path(raw: str | Path, *, what: str) -> Path:
    """Resolve `raw` and ensure it lands under an allowed write root
    (DATA_ROOT or the user's home directory).

    The MCP write tools (import downloads, NotebookLM brief) otherwise accept
    an arbitrary absolute path, letting a caller write anywhere on the
    filesystem (e.g. /etc). This constrains them to sane roots.
    """
    target = Path(raw).expanduser().resolve()
    allowed = [DATA_ROOT.resolve(), Path.home().resolve()]
    if not any(target == root or root in target.parents for root in allowed):
        raise MCPServerError(
            f"{what} must be under {DATA_ROOT} or your home directory; "
            f"refused {target}"
        )
    return target


def _expand_video_paths(paths: list[str]) -> list[Path]:
    """Resolve a mix of file paths and folder paths to a flat list of video files."""
    out: list[Path] = []
    for raw in paths:
        p = Path(raw).expanduser().resolve()
        if not p.exists():
            raise MCPServerError(f"path not found: {p}")
        if p.is_dir():
            out.extend(sorted(
                f for f in p.iterdir()
                if f.is_file() and f.suffix.lower() in SUPPORTED_VIDEO
            ))
        elif p.suffix.lower() in SUPPORTED_VIDEO:
            out.append(p)
        else:
            raise MCPServerError(f"unsupported file type: {p}")
    if not out:
        raise MCPServerError("no supported video files found in given paths")
    return out


def tool_analyze_films(
    paths: list[str],
    *,
    skip_audio: bool = False,
    skip_color: bool = False,
    color_every_n: int = 1,
    music: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Run the analyzer on one or more video files (or folders).

    SLOW: each 6-minute film takes ~5-6 minutes on CPU with audio enabled,
    or ~30 seconds with --skip-audio. Pass `skip_audio=True` for a fast first
    pass, then re-run with `force=True` later for the full pipeline.

    Returns: per-file outcome (succeeded / skipped / failed) + summary stats.
    """
    from .analyzer import analyze_film
    from .config import load as load_config
    from .genre_pack import load as load_genre_pack

    cfg = load_config()
    genre = getattr(cfg, "default_genre", "wedding")
    pack = load_genre_pack(genre)
    # Resolve the genre dirs from the SAME cfg read used to pick the pack, so
    # analyses/thumbs land in the genre whose pack we validated against.
    genre_root = DATA_ROOT / genre
    analyses_dir = genre_root / "analyses"
    thumbs_dir = genre_root / "thumbs"
    audio_dir = genre_root / "audio"
    files = _expand_video_paths(paths)
    analyses_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    # NOTE: this loop is long-running and fully synchronous — each film can
    # take minutes. Callers should expect a blocking call; there is no
    # progress streaming here by design (keeps the MCP surface simple).
    results: list[dict] = []
    for f in files:
        out_path = analyses_dir / f"{f.stem}.json"
        if out_path.exists() and not force:
            results.append({
                "file": str(f), "stem": f.stem,
                "status": "skipped", "reason": "already analyzed; pass force=true to redo",
            })
            continue
        try:
            result = analyze_film(
                f, thumbs_dir, pack,
                audio_root=audio_dir,
                min_scene_length_sec=cfg.min_scene_length_sec,
                threshold=cfg.scene_detect_threshold,
                skip_audio=skip_audio,
                skip_color=skip_color,
                color_every_n_clips=max(1, color_every_n),
                skip_music=not music,
                whisper_model=cfg.whisper_model,
                language=cfg.language,
                gemini_model=cfg.gemini_model,
                cleanup_audio=cfg.cleanup_audio_after_analysis,
            )
            out_path.write_text(result.model_dump_json(indent=2))
            results.append({
                "file": str(f), "stem": f.stem, "status": "ok",
                "clip_count": result.cuts.total,
                "avg_clip_sec": result.pacing.avg_clip_duration_sec,
                "duration_sec": result.film.duration_sec,
                "has_audio": result.audio is not None,
                "has_color": result.color is not None,
            })
        except Exception as e:
            results.append({
                "file": str(f), "stem": f.stem,
                "status": "failed", "error": str(e),
            })

    ok = [r for r in results if r["status"] == "ok"]
    return {
        "requested": len(files),
        "succeeded": len(ok),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "results": results,
        "next_step": (
            "Call generate_guide() to write style-guide.md and style-profile.json"
            if ok else None
        ),
    }


def tool_generate_guide(
    *,
    vision: bool = False,
    shot_sizes: bool = False,
    include_gemini: bool = True,
) -> dict[str, Any]:
    """Aggregate every analyzed film, optionally run vision passes, then write
    style-guide.md (markdown for humans) and style-profile.json (typed contract
    for AI consumption).

    Args:
      vision: if True, run Claude vision to label chapter scene types.
      shot_sizes: if True, run Claude vision to label per-clip composition.
      include_gemini: include Gemini qualitative analyses in the guide if present.

    Both vision passes use ANTHROPIC_API_KEY.
    """
    from .aggregator import aggregate
    from .config import load as load_config
    from .guide_writer import write_guide
    from .profile_writer import build_profile

    cfg = load_config()
    genre = getattr(cfg, "default_genre", "wedding")
    genre_root = DATA_ROOT / genre
    analyses_dir = genre_root / "analyses"
    profile_path = genre_root / "style-profile.json"
    guide_path = genre_root / "style-guide.md"
    stats_path = genre_root / "aggregate-stats.json"

    analyses = _load_all_films()
    if not analyses:
        raise MCPServerError(
            "no analyses found — call analyze_films() first."
        )

    notes: list[str] = []

    from .genre_pack import load as load_genre_pack
    pack = load_genre_pack(genre)

    if vision:
        from .vision_classify import VisionError, classify_chapters, gather_existing_examples
        # Thumbnails are stored relative to the GENRE root.
        examples = gather_existing_examples(analyses_dir, genre_root)
        for a in analyses:
            # Only feed chapters whose thumbnail actually exists on disk.
            # A missing file would otherwise be sent to the model as
            # "[missing]", wasting tokens AND getting a garbage 'other' label
            # persisted back onto the chapter. Skip those instead.
            unlabeled = [
                c for c in a.chapters
                if not c.label and c.representative_thumbnail
                and (genre_root / c.representative_thumbnail).is_file()
            ]
            missing = [
                c for c in a.chapters
                if not c.label and c.representative_thumbnail
                and not (genre_root / c.representative_thumbnail).is_file()
            ]
            if missing:
                notes.append(
                    f"vision: {len(missing)} chapter thumbnail(s) missing for "
                    f"{a.film.filename}; left unlabeled."
                )
            if not unlabeled:
                continue
            try:
                labels = classify_chapters(
                    [genre_root / c.representative_thumbnail for c in unlabeled],
                    pack,
                    model=cfg.anthropic_model,
                    examples=examples,
                )
                for ch, label in zip(unlabeled, labels):
                    ch.label = label
                (analyses_dir / f"{Path(a.film.filename).stem}.json").write_text(
                    a.model_dump_json(indent=2)
                )
            except VisionError as e:
                notes.append(f"vision skipped {a.film.filename}: {e}")

    if shot_sizes:
        from .shot_size import ShotSizeError, classify_shots
        for a in analyses:
            # Same missing-thumbnail guard as the vision pass above.
            unlabeled = [
                c for c in a.cuts.clips
                if not c.shot_size and c.thumbnail
                and (genre_root / c.thumbnail).is_file()
            ]
            missing = [
                c for c in a.cuts.clips
                if not c.shot_size and c.thumbnail
                and not (genre_root / c.thumbnail).is_file()
            ]
            if missing:
                notes.append(
                    f"shot-size: {len(missing)} clip thumbnail(s) missing for "
                    f"{a.film.filename}; left unlabeled."
                )
            if not unlabeled:
                continue
            try:
                labels = classify_shots(
                    [genre_root / c.thumbnail for c in unlabeled],
                    pack,
                    model=cfg.anthropic_model,
                )
                for clip, lbl in zip(unlabeled, labels):
                    clip.shot_size = lbl
                (analyses_dir / f"{Path(a.film.filename).stem}.json").write_text(
                    a.model_dump_json(indent=2)
                )
            except ShotSizeError as e:
                notes.append(f"shot-size skipped {a.film.filename}: {e}")

    stats = aggregate(analyses)
    if not include_gemini:
        stats = {**stats, "gemini_analyses": []}

    profile = build_profile(analyses, stats, pack=pack)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(profile, indent=2, default=str))
    stats_path.write_text(json.dumps(stats, indent=2, default=str))

    try:
        md = write_guide(stats, pack, model=cfg.anthropic_model,
                         backend=getattr(cfg, "claude_backend", "api"))
        guide_path.write_text(md)
        guide_status = "written"
    except Exception as e:
        guide_status = f"failed: {e}"

    return {
        "film_count": len(analyses),
        "profile_path": str(profile_path),
        "guide_path": str(guide_path),
        "guide_status": guide_status,
        "rule_count": len(profile.get("rules", [])),
        "notes": notes,
    }


def tool_import_videos(
    url: str,
    output_dir: str | None = None,
    *,
    cookies_browser: str | None = None,
) -> dict[str, Any]:
    """Download videos from any yt-dlp-supported URL — Vimeo, YouTube, or
    other platforms.

    Args:
      url: any yt-dlp-supported URL. Examples:
        - https://vimeo.com/123456789  (single)
        - https://vimeo.com/showcase/12345  (multiple)
        - https://vimeo.com/your-handle  (account)
        - https://www.youtube.com/watch?v=dQw4w9WgXcQ  (single)
        - https://www.youtube.com/playlist?list=PL...  (playlist)
        - https://www.youtube.com/@channelhandle  (channel)
      output_dir: where to save MP4s. Default: ~/films/imports.
      cookies_browser: 'safari', 'chrome', 'firefox', etc. — needed for
        private/age-gated videos.

    Returns the list of files downloaded plus a suggested next call.
    """
    from .vimeo_import import VideoImportError, download

    # Constrain the download target to a sane root (under home or DATA_ROOT).
    target = _contained_write_path(output_dir or "~/films/imports",
                                   what="import output_dir")
    before = {p for p in target.glob("*.mp4")} if target.exists() else set()

    transcript_lines: list[str] = []
    try:
        for line in download(url, target, cookies_browser=cookies_browser):
            transcript_lines.append(line)
    except VideoImportError as e:
        raise MCPServerError(str(e))

    after = {p for p in target.glob("*.mp4")}
    new_files = sorted(str(p) for p in (after - before))
    return {
        "url": url,
        "output_dir": str(target),
        "downloaded": new_files,
        "transcript_tail": transcript_lines[-12:],
        "next_step": (
            f"Call analyze_films(paths=['{target}'])"
            if new_files else "Nothing new downloaded."
        ),
    }


# Back-compat alias.
tool_import_vimeo = tool_import_videos


def tool_analyze_url(
    url: str,
    *,
    cookies_browser: str | None = None,
    skip_audio: bool = False,
    skip_color: bool = False,
    color_every_n: int = 1,
    music: bool = False,
) -> dict[str, Any]:
    """One-step pipeline: download from a URL (Vimeo / YouTube / etc.) AND
    analyze every video that lands.

    The convenience tool for "analyze this Vimeo showcase" or "analyze this
    YouTube playlist" — saves a download → analyze round-trip.

    Args:
      url: any yt-dlp-supported URL.
      cookies_browser: needed for private/age-gated content.
      skip_audio / skip_color / color_every_n / music: passed through to
        analyze_films. Default skip_audio=False; pass True for ~10x speedup.
    """
    download_result = tool_import_videos(url, cookies_browser=cookies_browser)
    new_files = download_result.get("downloaded") or []
    if not new_files:
        # A repeat call downloads nothing (yt-dlp's download-archive short
        # circuits), which previously dead-ended at 'nothing_to_analyze' —
        # even though the file is sitting on disk from the first call. Fall
        # back to re-analyzing the already-downloaded file(s) in the output
        # dir. analyze_films() will itself skip anything already analyzed
        # (unless force), so this is safe and idempotent.
        output_dir = download_result.get("output_dir")
        candidates: list[str] = []
        if output_dir and Path(output_dir).is_dir():
            candidates = [str(p) for p in sorted(Path(output_dir).glob("*.mp4"))]
        if not candidates:
            return {
                "url": url,
                "status": "nothing_to_analyze",
                "import": download_result,
            }
        new_files = candidates

    analysis_result = tool_analyze_films(
        new_files,
        skip_audio=skip_audio,
        skip_color=skip_color,
        color_every_n=color_every_n,
        music=music,
    )

    return {
        "url": url,
        "status": "ok",
        "downloaded": new_files,
        "import": download_result,
        "analysis": analysis_result,
        "next_step": (
            "Call generate_guide() to update the style guide and profile."
            if analysis_result.get("succeeded") else None
        ),
    }


def tool_analyze_youtube_via_gemini(
    url: str,
    *,
    custom_prompt: str | None = None,
    save_as_inspiration: bool = True,
) -> dict[str, Any]:
    """Analyze a YouTube video via Gemini's native YouTube URL support.

    Same engine that powers NotebookLM — Gemini fetches and watches the
    video. ~30-second qualitative analysis covering pacing, shots, audio,
    color grade, structure, distinctive choices, wedding-film relevance.

    No download needed. Fast. Use this for:
      - Studying a film whose style you admire (won't be in your archive,
        no full local pipeline needed).
      - Quickly evaluating a YouTube reference before deciding whether to
        download it for the full analysis.
      - Building an "inspirations" file that the NotebookLM export
        (export_for_notebooklm) folds in as additional qualitative context.

    Args:
      url: youtube.com or youtu.be URL.
      custom_prompt: optional override for the default analysis prompt.
      save_as_inspiration: append the result to
        ~/.film-style-analyzer/<genre>/inspirations.json. The NotebookLM
        brief (export_for_notebooklm) reads these as qualitative context.
        Note: the style-guide writer does NOT currently read them. Default True.

    Returns the Gemini analysis dict.
    """
    from .config import load as load_config
    from .gemini_analyzer import GeminiError, analyze_youtube_url
    from .genre_pack import load as load_genre_pack

    cfg = load_config()
    pack = load_genre_pack(_active_genre())
    try:
        result = analyze_youtube_url(url, pack, custom_prompt=custom_prompt)
    except GeminiError as e:
        raise MCPServerError(str(e))

    if save_as_inspiration:
        inspirations_path = _genre_root() / "inspirations.json"
        existing = []
        if inspirations_path.is_file():
            try:
                existing = json.loads(inspirations_path.read_text())
            except json.JSONDecodeError:
                existing = []
        # Replace if same URL already present, otherwise append.
        existing = [e for e in existing if e.get("url") != url]
        existing.append({
            "url": url,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "analysis": result.get("analysis"),
        })
        inspirations_path.parent.mkdir(parents=True, exist_ok=True)
        inspirations_path.write_text(json.dumps(existing, indent=2, default=str))
        result["saved_to"] = str(inspirations_path)

    return result


def tool_list_inspirations() -> dict[str, Any]:
    """List the YouTube inspirations saved by analyze_youtube_via_gemini."""
    inspirations_path = _genre_root() / "inspirations.json"
    if not inspirations_path.is_file():
        return {"count": 0, "inspirations": []}
    try:
        data = json.loads(inspirations_path.read_text())
    except json.JSONDecodeError:
        data = []
    return {"count": len(data), "inspirations": data}


def tool_export_for_notebooklm(
    output_path: str | None = None,
    *,
    include_inspirations: bool = True,
    title: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Generate a markdown brief suitable for NotebookLM ingestion.

    NotebookLM has no public API, so this is a paste-bridge: this tool
    writes the brief to disk and returns its content + path. Upload it as a
    source in your NotebookLM notebook (alongside any YouTube reference
    videos), then NotebookLM can chat about your style with both quantitative
    rules AND qualitative video context.

    Args:
      output_path: where to save. Must resolve under DATA_ROOT or your home
        directory. Default: ~/.film-style-analyzer/<genre>/notebooklm-brief.md.
      include_inspirations: include any saved YouTube inspirations.
      title: title at the top of the brief.
      overwrite: allow replacing an existing custom output_path. The default
        path is always regenerated in place; a custom path that already
        exists is refused unless overwrite=True.

    Returns the path and content (so the LLM can preview / discuss it).
    """
    from .config import load as load_config
    from .genre_pack import load as load_genre_pack
    from .notebooklm_export import write_brief

    cfg = load_config()
    genre_root = _genre_root()
    pack = load_genre_pack(_active_genre())
    films = _load_all_films()
    if not films:
        raise MCPServerError(
            "no analyses to export. Call analyze_films() first."
        )

    profile_path = genre_root / "style-profile.json"
    profile: dict = {}
    if profile_path.is_file():
        try:
            profile = json.loads(profile_path.read_text())
        except json.JSONDecodeError:
            profile = {}

    inspirations: list[dict] | None = None
    if include_inspirations:
        ins_path = genre_root / "inspirations.json"
        if ins_path.is_file():
            try:
                inspirations = json.loads(ins_path.read_text())
            except json.JSONDecodeError:
                inspirations = None

    if output_path:
        # Constrain a caller-supplied path and refuse to clobber it silently.
        target = _contained_write_path(output_path, what="export output_path")
        if target.exists() and not overwrite:
            raise MCPServerError(
                f"{target} already exists; pass overwrite=True to replace it."
            )
    else:
        target = genre_root / "notebooklm-brief.md"

    write_brief(
        films, profile, target, pack,
        inspirations=inspirations,
        title=title or "Editing Style Profile (for NotebookLM)",
        brand_name=cfg.brand_name,
        allowed_roots=[DATA_ROOT, Path.home()],
    )
    content = target.read_text()
    return {
        "path": str(target),
        "byte_count": len(content),
        "section_count": content.count("\n## "),
        "content": content,
        "next_step": (
            f"Open {target}, copy its contents, then in NotebookLM click "
            "'+ Add source' → 'Paste text' and paste it. Add your YouTube "
            "reference videos as additional sources in the same notebook."
        ),
    }


def tool_corpus_report() -> dict[str, Any]:
    """Build a one-shot summary the LLM can turn into a report.

    Combines: aggregate stats, every film summary, presence flags for guide
    and profile, plus a sketch of the most stylistically distinctive films
    (the ones farthest from the corpus centroid). Designed so a single tool
    call gives Claude everything it needs to write a coherent corpus report
    without further round-trips.
    """
    from .aggregator import aggregate

    films = _load_all_films()
    genre_root = _genre_root()
    summary = {
        "film_count": len(films),
        "guide_present": (genre_root / "style-guide.md").is_file(),
        "profile_present": (genre_root / "style-profile.json").is_file(),
        "data_root": str(genre_root),
    }
    if not films:
        summary["status"] = "empty"
        summary["next_step"] = (
            "Call analyze_films(paths=[...]) on a folder of films to begin."
        )
        return summary

    stats = aggregate(films)
    summary["aggregate_stats"] = stats
    summary["films"] = [_film_summary(a) for a in films]

    # Outliers: films farthest from the corpus mean by cosine distance.
    if len(films) >= 3:
        from .matchmaker import build_vector
        vectors = [build_vector(f) for f in films]
        keys = sorted(vectors[0].dimensions)
        # Centroid.
        centroid = {k: sum(v.dimensions[k] for v in vectors) / len(vectors)
                    for k in keys}
        import math
        def _cos(a_dims, b_dims):
            dot = sum(a_dims[k] * b_dims[k] for k in keys)
            na = math.sqrt(sum(a_dims[k] ** 2 for k in keys))
            nb = math.sqrt(sum(b_dims[k] ** 2 for k in keys))
            return dot / (na * nb) if na and nb else 0.0
        ranked = sorted(
            [(v.filename, _cos(v.dimensions, centroid)) for v in vectors],
            key=lambda kv: kv[1],
        )
        summary["outliers"] = [
            {"filename": fn, "centroid_similarity": round(s, 4)}
            for fn, s in ranked[:3]
        ]

    # Coverage flags — what dimensions are still missing for the LLM to call out.
    has_color = sum(1 for f in films if f.color)
    has_audio = sum(1 for f in films if f.audio)
    has_music = sum(1 for f in films if f.music)
    has_vision = sum(1 for f in films if any(c.label for c in f.chapters))
    has_shot_sizes = sum(1 for f in films
                         if any(c.shot_size for c in f.cuts.clips))
    has_metadata = sum(1 for f in films if f.metadata)
    summary["coverage"] = {
        "color":      f"{has_color}/{len(films)}",
        "audio":      f"{has_audio}/{len(films)}",
        "music":      f"{has_music}/{len(films)}",
        "vision":     f"{has_vision}/{len(films)}",
        "shot_sizes": f"{has_shot_sizes}/{len(films)}",
        "metadata":   f"{has_metadata}/{len(films)}",
    }

    summary["status"] = "ready"
    return summary


def tool_predict_cuts(song_path: str, target_duration_sec: float | None = None,
                      snap_tolerance_sec: float = 0.12) -> dict[str, Any]:
    """Predict cut times for a song using the established style profile.

    Walks the profile's decile pacing curve, snapping each ideal cut to the
    nearest beat in the song. Returns timestamps + an FCPXML marker track
    string ready to import into Resolve / Premiere / FCP.

    Requires librosa: pip install 'film-style-analyzer[music]'.
    """
    from .predict_cuts import PredictCutsError, predict_cuts, to_fcpxml_markers

    p = Path(song_path).expanduser()
    if not p.is_file():
        raise MCPServerError(f"song file not found: {p}")
    profile_path = _profile_path()
    if not profile_path.is_file():
        raise MCPServerError(
            f"no style profile at {profile_path}. Run `film-style guide` first."
        )
    profile_data = json.loads(profile_path.read_text())
    try:
        prediction = predict_cuts(
            p, profile_data,
            target_duration_sec=target_duration_sec,
            snap_tolerance_sec=snap_tolerance_sec,
        )
    except PredictCutsError as e:
        raise MCPServerError(str(e))

    return {
        "summary": {
            "song": str(p),
            "song_duration_sec": prediction["song_duration_sec"],
            "tempo_bpm": prediction["song_tempo_bpm"],
            "predicted_cuts": prediction["predicted_cut_count"],
            "on_beat_pct": prediction["on_beat_pct"],
        },
        "cuts": prediction["cuts"],
        "fcpxml_marker_track": to_fcpxml_markers(prediction, song_basename=p.stem),
    }


# ---------------------------------------------------------------------------
# Resources — exposed at film-style:// URIs.
# ---------------------------------------------------------------------------

def resource_profile() -> str:
    profile_path = _profile_path()
    if not profile_path.is_file():
        return json.dumps({
            "error": "style-profile.json does not exist yet",
            "remedy": "Run `film-style analyze <folder>` then `film-style guide`.",
        }, indent=2)
    return profile_path.read_text()


def resource_guide() -> str:
    guide_path = _guide_path()
    if not guide_path.is_file():
        return "# Style guide not yet generated\n\nRun `film-style guide`."
    return guide_path.read_text()


def resource_films_index() -> str:
    return json.dumps(tool_list_films(), indent=2)


def resource_film(stem: str) -> str:
    return json.dumps(tool_get_film(stem), indent=2, default=str)


# ---------------------------------------------------------------------------
# Prompts — pre-built conversation starters for the most common workflow.
# ---------------------------------------------------------------------------

# Genre-neutral workflow guidance. The genre-specific framing (who the editor
# is, what they're cutting) is supplied by the active pack's `mcp_edit_in_style`
# prompt and prepended by `_build_edit_in_style_prompt()` below.
EDIT_IN_STYLE_WORKFLOW = """The full toolkit is available; pick the right tool
for the ask. Always begin by calling get_style_profile() so your suggestions are
grounded in the editor's measured patterns, not generic conventions.

Common workflows:

  A. "Analyze these films and give me a report"
     1. analyze_films(paths=[...])  — slow; ~5 min per film with audio,
        ~30s with skip_audio=True. Default to skip_audio=True for first pass.
     2. generate_guide(vision=True)  — writes guide + profile.
     3. corpus_report()  — single call returns everything needed for a report.
     4. Compose the report from corpus_report() output.

  B. "Pull films from Vimeo or YouTube and analyze them"
     1. analyze_url(url=..., cookies_browser='safari' if private) — single
        call that downloads + analyzes. Works for Vimeo, YouTube, playlists,
        showcases, channel URLs, etc.
     OR explicit two-step:
     1. import_videos(url=...)
     2. analyze_films(paths=[downloaded folder])
     3. generate_guide()

  B'. "Just analyze this YouTube video qualitatively, no download"
     1. analyze_youtube_via_gemini(url=...) — same engine as NotebookLM.
        Saves to inspirations.json by default.
     Use this for fast study of films you admire but don't want to ingest
     into the full local pipeline.

  B''. "Build a NotebookLM source from my archive"
     1. export_for_notebooklm() — writes a markdown brief.
     2. User pastes the brief into NotebookLM as a source, alongside YouTube
        videos. NotebookLM then chats about the style using both.

  C. "Edit a video in my style"
     1. get_style_profile()  — load the typed contract.
     2. get_style_guide()    — prose context.
     3. find_similar_films(stem=...)  — tighter reference if a similar
        prior film is named.
     4. predict_cuts(song_path=...)  — if music is given.

  D. "Why did film X come out a certain way" / corrections
     1. get_film(stem)
     2. set_chapter_label() / set_film_metadata() — corrections feed back
        into the next vision pass automatically.

Editing rules:
  - The profile.rules array is binding. Don't invent rules.
  - Flag deviations from the profile explicitly when you propose them.
  - For long-running tools, set realistic expectations in the response.
"""


def _build_edit_in_style_prompt() -> str:
    """Compose the edit_in_style prompt from the ACTIVE genre pack's
    `mcp_edit_in_style` field (shipped in every pack) plus the genre-neutral
    workflow guidance. Previously the whole prompt was hardcoded wedding text
    and the pack's tested `mcp_edit_in_style` prompt was never used."""
    from .config import load as load_config
    cfg = load_config()
    try:
        pack = _active_pack()
        intro = pack.prompts["mcp_edit_in_style"].format(
            brand_name=getattr(cfg, "brand_name", "the editor")
        )
    except Exception:
        intro = (
            "You are assisting an editor with their editing workflow, using "
            "their measured style profile as the reference."
        )
    return f"{intro}\n\n{EDIT_IN_STYLE_WORKFLOW}"


# ---------------------------------------------------------------------------
# MCP wiring — kept inside a function so the heavy import only happens when
# the server is actually started.
# ---------------------------------------------------------------------------

def build_server():
    """Construct the FastMCP server. Heavy: imports the mcp SDK."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise MCPServerError(
            "MCP SDK not installed. Install with: pip install 'film-style-analyzer[mcp]'"
        ) from e

    mcp = FastMCP("film-style-analyzer")

    # --- read tools ---
    @mcp.tool()
    def list_films() -> dict:
        """List every analyzed film in the archive (summaries only)."""
        return tool_list_films()

    @mcp.tool()
    def corpus_report() -> dict:
        """Build a complete corpus snapshot in one call: aggregate stats,
        every film summary, presence flags for guide/profile, coverage report,
        and stylistic outliers. Call this when the user asks for a 'report'
        or 'summary' of the archive — one tool call gives you everything you
        need to write the response."""
        return tool_corpus_report()

    @mcp.tool()
    def analyze_films(
        paths: list[str],
        skip_audio: bool = False,
        skip_color: bool = False,
        color_every_n: int = 1,
        music: bool = False,
        force: bool = False,
    ) -> dict:
        """Run the analyzer on one or more video files (or folders).

        SLOW. Each 6-min film is ~5-6 minutes on CPU with full audio, or
        ~30 seconds with skip_audio=True. For an initial fast pass, use
        skip_audio=True; re-run with force=True later for the full pipeline.

        Returns per-file outcome (succeeded / skipped / failed) + summary."""
        return tool_analyze_films(
            paths,
            skip_audio=skip_audio,
            skip_color=skip_color,
            color_every_n=color_every_n,
            music=music,
            force=force,
        )

    @mcp.tool()
    def generate_guide(
        vision: bool = False,
        shot_sizes: bool = False,
        include_gemini: bool = True,
    ) -> dict:
        """Aggregate all analyses, optionally run vision passes, then write
        style-guide.md (markdown for humans) and style-profile.json (the typed
        contract for AI consumption). Calls Anthropic API. Run after
        analyze_films."""
        return tool_generate_guide(
            vision=vision,
            shot_sizes=shot_sizes,
            include_gemini=include_gemini,
        )

    @mcp.tool()
    def analyze_url(
        url: str,
        cookies_browser: str | None = None,
        skip_audio: bool = False,
        skip_color: bool = False,
        color_every_n: int = 1,
        music: bool = False,
    ) -> dict:
        """One-step download-and-analyze for any Vimeo/YouTube URL. Use this
        when the user says 'analyze this Vimeo showcase' or 'analyze this
        YouTube playlist' — it pulls the video(s) and runs the full analyzer
        in a single call."""
        return tool_analyze_url(
            url,
            cookies_browser=cookies_browser,
            skip_audio=skip_audio, skip_color=skip_color,
            color_every_n=color_every_n, music=music,
        )

    @mcp.tool()
    def analyze_youtube_via_gemini(
        url: str,
        custom_prompt: str | None = None,
        save_as_inspiration: bool = True,
    ) -> dict:
        """Analyze a YouTube video via Gemini's native URL support — the
        same engine NotebookLM uses. ~30 sec qualitative analysis covering
        pacing, shots, audio, color, structure, distinctive choices, and
        wedding-film relevance. No download needed.

        Use this for studying films whose style inspires you, or quickly
        evaluating a YouTube reference before deciding to download it for
        the full local pipeline. Results save to <genre>/inspirations.json by
        default — the NotebookLM export (export_for_notebooklm) folds them in
        as qualitative context (the style-guide writer does not read them)."""
        return tool_analyze_youtube_via_gemini(
            url, custom_prompt=custom_prompt,
            save_as_inspiration=save_as_inspiration,
        )

    @mcp.tool()
    def list_inspirations() -> dict:
        """List the YouTube inspirations saved by analyze_youtube_via_gemini."""
        return tool_list_inspirations()

    @mcp.tool()
    def export_for_notebooklm(
        output_path: str | None = None,
        include_inspirations: bool = True,
        title: str | None = None,
        overwrite: bool = False,
    ) -> dict:
        """Generate a markdown brief for NotebookLM ingestion.

        NotebookLM has no public API, so this is a paste-bridge: writes the
        brief to disk, returns its content. The user uploads it to NotebookLM
        as a 'paste text' source — alongside any YouTube reference videos —
        and NotebookLM can then chat about the editor's style grounded in
        both the measured quantitative profile and the qualitative video refs.

        A custom output_path must resolve under DATA_ROOT or your home dir,
        and an existing one is refused unless overwrite=True."""
        return tool_export_for_notebooklm(
            output_path=output_path,
            include_inspirations=include_inspirations,
            title=title,
            overwrite=overwrite,
        )

    @mcp.tool()
    def import_videos(url: str, output_dir: str | None = None,
                      cookies_browser: str | None = None) -> dict:
        """Download videos from a Vimeo or YouTube URL (or any yt-dlp source).

        Examples:
          - vimeo.com/123 (single), vimeo.com/showcase/12 (multiple),
            vimeo.com/handle (account)
          - youtube.com/watch?v=..., youtube.com/playlist?list=...,
            youtube.com/@channel

        Pass cookies_browser='safari' (or 'chrome', etc.) for private or
        age-gated videos."""
        return tool_import_videos(url, output_dir, cookies_browser=cookies_browser)

    @mcp.tool()
    def get_film(stem: str) -> dict:
        """Get the full analysis for one film. `stem` is the filename without extension."""
        return tool_get_film(stem)

    @mcp.tool()
    def get_style_profile() -> dict:
        """Return the typed style-profile.json — the canonical artifact for
        editing in the editor's style. Contains pacing, transitions, audio, color,
        shot mix, music, scene rules, plus a human-readable rules array."""
        return tool_get_style_profile()

    @mcp.tool()
    def get_style_guide() -> str:
        """Return the human-readable markdown style guide."""
        return tool_get_style_guide()

    @mcp.tool()
    def get_aggregate_stats() -> dict:
        """Return aggregate statistics across all analyzed films."""
        return tool_get_aggregate_stats()

    @mcp.tool()
    def find_similar_films(stem: str, top: int = 3) -> dict:
        """Find the films in the archive most stylistically similar to `stem`.
        Useful as a tighter reference than the corpus average."""
        return tool_find_similar_films(stem, top)

    @mcp.tool()
    def set_film_metadata(stem: str, metadata: dict) -> dict:
        """Merge metadata onto a film. Use null values to delete keys.
        Curated keys: venue, season, time_of_day, ceremony, guest_count,
        music_genre, weather, duration_target."""
        return tool_set_film_metadata(stem, metadata)

    @mcp.tool()
    def set_chapter_label(stem: str, chapter_index: int, label: str | None) -> dict:
        """Correct a chapter's scene label. Used by the feedback loop —
        the vision pass picks these up as few-shot examples on next run.
        Pass label=null to clear."""
        return tool_set_chapter_label(stem, chapter_index, label)

    @mcp.tool()
    def get_chapter_thumbnails_to_label(stem: str, max_chapters: int = 12):
        """Return image content blocks for up to `max_chapters` UNLABELED
        chapters of `stem`. Look at each image and decide a wedding-genre
        scene label, then call `set_chapter_labels_bulk` with the mapping.

        This is the Claude-Pro/Max-subscription path: vision passes happen
        in chat (you, the assistant, see the thumbnails) instead of via the
        Anthropic API. Use it to label your own corpus without consuming
        API tokens."""
        from mcp.server.fastmcp.utilities.types import Image as MCPImage
        info = tool_get_unlabeled_chapter_thumbnails(stem, max_chapters=max_chapters)
        out: list = [
            f"Film: {info['stem']}",
            f"Showing {len(info['chapters'])} unlabeled chapter(s); "
            f"{info['remaining_after_batch']} remaining after this batch.",
            f"Valid labels: {', '.join(info['valid_labels'])}",
        ]
        for ch in info["chapters"]:
            out.append(
                f"--- chapter_index={ch['chapter_index']} "
                f"(t={ch['start_sec']:.1f}s, dur={ch['duration_sec']:.1f}s) ---"
            )
            try:
                out.append(MCPImage(path=ch["thumbnail_path"]))
            except Exception as e:
                out.append(f"[failed to load thumbnail: {e}]")
        out.append(
            "Now call set_chapter_labels_bulk(stem=..., labels={chapter_index: label, ...}) "
            "to write your decisions back."
        )
        return out

    @mcp.tool()
    def set_chapter_labels_bulk(stem: str, labels: dict) -> dict:
        """Apply many chapter labels at once. `labels` maps chapter_index
        (int) → scene label (str), or chapter_index → null to clear.

        Used after `get_chapter_thumbnails_to_label` — look at the images
        you got back, then send the bulk label dict here. Validates each
        label against the active genre pack's scene_labels; invalid ones
        are listed in the response's `skipped` array but don't abort the
        rest of the batch."""
        return tool_set_chapter_labels_bulk(stem, labels)

    @mcp.tool()
    def get_clip_thumbnails_to_label_shots(stem: str, start_index: int = 0,
                                            batch_size: int = 12):
        """Return image content blocks for up to `batch_size` UNLABELED clip
        thumbnails of `stem`, starting at clip index `start_index`. Look at
        each, decide a shot size from the pack's shot_labels, then call
        `set_shot_sizes_bulk` with the mapping. Iterate via `start_index` to
        cover the full film."""
        from mcp.server.fastmcp.utilities.types import Image as MCPImage
        info = tool_get_unlabeled_clip_thumbnails(
            stem, start_index=start_index, batch_size=batch_size,
        )
        out: list = [
            f"Film: {info['stem']}",
            f"Showing {len(info['clips'])} unlabeled clip(s); "
            f"{info['remaining_after_batch']} remaining after this batch.",
            f"Valid shot labels: {', '.join(info['valid_shot_labels'])}",
        ]
        for c in info["clips"]:
            out.append(
                f"--- clip_index={c['clip_index']} "
                f"(t={c['start_sec']:.1f}s, dur={c['duration_sec']:.2f}s) ---"
            )
            try:
                out.append(MCPImage(path=c["thumbnail_path"]))
            except Exception as e:
                out.append(f"[failed to load thumbnail: {e}]")
        out.append(
            "Now call set_shot_sizes_bulk(stem=..., sizes={clip_index: label, ...})."
        )
        return out

    @mcp.tool()
    def set_shot_sizes_bulk(stem: str, sizes: dict) -> dict:
        """Apply many per-clip shot sizes at once. `sizes` maps clip_index
        (int) → shot label (str), or clip_index → null to clear. Validates
        each label against the active pack's shot_labels."""
        return tool_set_shot_sizes_bulk(stem, sizes)

    @mcp.tool()
    def get_clip_thumbnails_to_describe(stem: str, start_index: int = 0,
                                        batch_size: int = 8):
        """Return image content blocks for up to `batch_size` clips that
        DON'T yet have a shot_description, starting at clip index
        `start_index`. Look at each thumbnail and emit a structured
        ShotDescription per clip — subjects, action, setting, lighting,
        camera, mood, plus a one-line free-form `description`. Then call
        `set_clip_descriptions_bulk` with the mapping.

        Shot descriptions answer 'what's in this clip?' so downstream tools
        can pick clips from raw footage that match the editor's choices.
        Iterate via `start_index` to cover the full film. The reply
        includes a `schema_hint` with controlled vocabularies for each
        field — use those values where they fit, free text where they
        don't."""
        from mcp.server.fastmcp.utilities.types import Image as MCPImage
        info = tool_get_undescribed_clip_thumbnails(
            stem, start_index=start_index, batch_size=batch_size,
        )
        out: list = [
            f"Film: {info['stem']}",
            f"Showing {len(info['clips'])} clip(s); "
            f"{info['remaining_after_batch']} remaining after this batch.",
            f"Schema vocabularies: {info['schema_hint']}",
        ]
        for c in info["clips"]:
            shot_size = c.get("shot_size") or "(unlabeled)"
            out.append(
                f"--- clip_index={c['clip_index']} "
                f"(t={c['start_sec']:.1f}s, dur={c['duration_sec']:.2f}s, "
                f"shot_size={shot_size}) ---"
            )
            try:
                out.append(MCPImage(path=c["thumbnail_path"]))
            except Exception as e:
                out.append(f"[failed to load thumbnail: {e}]")
        out.append(
            "Now call set_clip_descriptions_bulk(stem=..., descriptions={"
            "clip_index: {subjects: [...], action: ..., setting: ..., "
            "lighting: ..., camera: ..., mood: ..., description: ...}, ...})."
        )
        return out

    @mcp.tool()
    def set_clip_descriptions_bulk(stem: str, descriptions: dict) -> dict:
        """Apply many clip shot_descriptions at once. `descriptions` maps
        clip_index (int) → ShotDescription dict (or null to clear). Each
        ShotDescription is a dict with optional fields: subjects (list),
        action (str), setting (str), lighting (str), camera (str), mood
        (str), description (str)."""
        return tool_set_clip_descriptions_bulk(stem, descriptions)

    @mcp.tool()
    def compare_fcpxml(fcpxml_content: str | None = None,
                       fcpxml_path: str | None = None) -> dict:
        """Compare a rough-cut FCPXML against the established profile.
        Provide either the XML content or a filesystem path."""
        return tool_compare_fcpxml(fcpxml_content, fcpxml_path)

    @mcp.tool()
    def predict_cuts(song_path: str, target_duration_sec: float | None = None,
                     snap_tolerance_sec: float = 0.12) -> dict:
        """Predict cut times for a song using the editor's pacing profile.
        Snaps each ideal cut to the nearest beat in the song. Returns
        timestamps + an FCPXML marker track string."""
        return tool_predict_cuts(song_path, target_duration_sec, snap_tolerance_sec)

    # --- resources ---
    @mcp.resource("film-style://profile")
    def res_profile() -> str:
        """Style profile (JSON)."""
        return resource_profile()

    @mcp.resource("film-style://guide")
    def res_guide() -> str:
        """Markdown style guide."""
        return resource_guide()

    @mcp.resource("film-style://films")
    def res_films() -> str:
        """Index of analyzed films (JSON)."""
        return resource_films_index()

    @mcp.resource("film-style://films/{stem}")
    def res_film(stem: str) -> str:
        """Full analysis for one film (JSON)."""
        return resource_film(stem)

    # --- prompts ---
    @mcp.prompt()
    def edit_in_style() -> str:
        """A conversation primer that briefs Claude on the editor's
        conventions and how to use the rest of the tools to assemble cuts."""
        return _build_edit_in_style_prompt()

    return mcp


def run_stdio() -> None:
    """Start the MCP server on stdio. Blocks. Used by `film-style mcp-serve`."""
    server = build_server()
    server.run()
