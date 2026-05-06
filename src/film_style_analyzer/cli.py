"""click CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table

from . import __version__
from .aggregator import aggregate
from .analyzer import analyze_film
from .config import CONFIG_PATH, load as load_config, write_default as write_default_config
from .fcpxml_parser import parse as parse_fcpxml
from .guide_writer import write_guide
from .profile_writer import build_profile
from .schemas import FilmAnalysis
from .genre_pack import load as load_genre_pack
from .vision_classify import VisionError, classify_chapters, gather_existing_examples

DATA_ROOT = Path.home() / ".film-style-analyzer"
ANALYSES_DIR = DATA_ROOT / "analyses"
THUMBS_DIR = DATA_ROOT / "thumbs"
AUDIO_DIR = DATA_ROOT / "audio"
DEFAULT_GUIDE = DATA_ROOT / "style-guide.md"
DEFAULT_STATS = DATA_ROOT / "aggregate-stats.json"
DEFAULT_PROFILE = DATA_ROOT / "style-profile.json"
SUPPORTED = {".mp4", ".mov", ".m4v", ".mkv"}

console = Console()


def _films_in(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix.lower() in SUPPORTED else []
    return sorted(p for p in target.iterdir() if p.suffix.lower() in SUPPORTED)


def _load_analyses() -> list[FilmAnalysis]:
    if not ANALYSES_DIR.exists():
        return []
    out = []
    for p in sorted(ANALYSES_DIR.glob("*.json")):
        try:
            out.append(FilmAnalysis.model_validate_json(p.read_text()))
        except Exception as e:
            console.print(f"[yellow]skip {p.name}: {e}[/yellow]")
    return out


@click.group()
@click.version_option(__version__)
def cli() -> None:
    """Analyze finished wedding films and generate an editing style guide."""


@cli.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), default=ANALYSES_DIR,
              help="Where to write analysis JSONs.")
@click.option("--force", is_flag=True, help="Re-analyze even if JSON exists.")
@click.option("--min-scene-sec", type=float, default=None,
              help="Min scene length (sec). Default from config.")
@click.option("--threshold", type=float, default=None,
              help="Adaptive scene-detect threshold override.")
@click.option("--skip-audio", is_flag=True, help="Skip transcription and audio classification.")
@click.option("--skip-color", is_flag=True, help="Skip per-clip color analysis.")
@click.option("--color-every-n", type=int, default=1, show_default=True,
              help="Analyze color on every Nth clip. Higher = faster.")
@click.option("--music/--no-music", default=False, help="Run librosa music characterization.")
@click.option("--whisper-model", default=None, help="WhisperX model size.")
@click.option("--language", default=None, help="WhisperX language code.")
@click.option("--no-diarize", is_flag=True, help="Disable speaker diarization.")
@click.option("--gemini", is_flag=True, help="Run Gemini narrative analysis (paid, slow).")
@click.option("--gemini-model", default=None)
@click.option("--keep-audio", is_flag=True, help="Keep extracted WAV files after analysis.")
def analyze(
    path: Path, output: Path, force: bool, min_scene_sec: float | None,
    threshold: float | None,
    skip_audio: bool, skip_color: bool, color_every_n: int, music: bool,
    whisper_model: str | None, language: str | None, no_diarize: bool,
    gemini: bool, gemini_model: str | None, keep_audio: bool,
) -> None:
    """Analyze one or more finished wedding films."""
    cfg = load_config()
    min_scene_sec = min_scene_sec if min_scene_sec is not None else cfg.min_scene_length_sec
    threshold = threshold if threshold is not None else cfg.scene_detect_threshold
    whisper_model = whisper_model or cfg.whisper_model
    language = language or cfg.language
    gemini_model = gemini_model or cfg.gemini_model
    cleanup = (not keep_audio) and cfg.cleanup_audio_after_analysis
    films = _films_in(path)
    if not films:
        raise click.ClickException(f"no supported video files found at {path}")

    output.mkdir(parents=True, exist_ok=True)
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("analyzing", total=len(films))
        for film in films:
            out_path = output / f"{film.stem}.json"
            if out_path.exists() and not force:
                console.print(f"[dim]skip[/dim] {film.name} (exists; use --force)")
                progress.advance(task)
                continue
            progress.update(task, description=f"analyzing {film.name}")
            try:
                result = analyze_film(
                    film, THUMBS_DIR,
                    audio_root=AUDIO_DIR,
                    min_scene_length_sec=min_scene_sec,
                    threshold=threshold,
                    skip_audio=skip_audio,
                    skip_color=skip_color,
                    color_every_n_clips=max(1, color_every_n),
                    skip_music=not music,
                    whisper_model=whisper_model,
                    language=language,
                    diarize=not no_diarize,
                    run_gemini=gemini,
                    gemini_model=gemini_model,
                    cleanup_audio=cleanup,
                )
                out_path.write_text(result.model_dump_json(indent=2))
                extras = []
                if result.audio:
                    extras.append(f"audio:{result.audio['summary']['speech_segment_count']}sp")
                if result.transcript:
                    extras.append(f"words:{result.transcript['total_words']}")
                if result.gemini_analysis:
                    extras.append("gemini✓")
                tail = (" " + " ".join(extras)) if extras else ""
                console.print(f"[green]ok[/green] {film.name} — {result.cuts.total} clips, "
                              f"avg {result.pacing.avg_clip_duration_sec}s{tail}")
            except Exception as e:
                console.print(f"[red]fail[/red] {film.name}: {e}")
            progress.advance(task)


@cli.command()
@click.option("--output", type=click.Path(path_type=Path), default=DEFAULT_GUIDE)
@click.option("--profile-output", type=click.Path(path_type=Path), default=DEFAULT_PROFILE,
              help="Where to write style-profile.json (consumed by downstream AI tools).")
@click.option("--model", default=None)
@click.option("--include-gemini/--no-include-gemini", default=True,
              help="Include Gemini qualitative analyses if available.")
@click.option("--vision", is_flag=True,
              help="Use Claude vision to label chapter scene types from thumbnails.")
@click.option("--shot-sizes", is_flag=True,
              help="Use Claude vision to label per-clip shot sizes (slower; uses more API calls).")
def guide(output: Path, profile_output: Path, model: str | None,
          include_gemini: bool, vision: bool, shot_sizes: bool) -> None:
    """Generate the editing style guide from analyzed films."""
    cfg = load_config()
    model = model or cfg.anthropic_model
    analyses = _load_analyses()
    if not analyses:
        raise click.ClickException("no analyses found — run `film-style analyze <path>` first")

    pack = load_genre_pack(cfg.default_genre if hasattr(cfg, "default_genre") else "wedding")
    if vision:
        console.print("[bold]Vision pass[/bold] — classifying chapter scene types…")
        # Gather already-labeled chapters across the archive as few-shot examples.
        examples = gather_existing_examples(ANALYSES_DIR, DATA_ROOT)
        if examples:
            console.print(f"  [dim]using {len(examples)} prior labels as few-shot reference[/dim]")
        for a in analyses:
            unlabeled = [c for c in a.chapters if not c.label and c.representative_thumbnail]
            if not unlabeled:
                continue
            thumb_paths = [DATA_ROOT / c.representative_thumbnail for c in unlabeled]
            try:
                labels = classify_chapters(thumb_paths, pack, model=model, examples=examples)
            except VisionError as e:
                console.print(f"[yellow]vision skip[/yellow] {a.film.filename}: {e}")
                continue
            for ch, label in zip(unlabeled, labels):
                ch.label = label
            (ANALYSES_DIR / f"{Path(a.film.filename).stem}.json").write_text(
                a.model_dump_json(indent=2)
            )
            console.print(f"  [green]labeled[/green] {a.film.filename}: {len(labels)} chapters")

    if shot_sizes:
        from .shot_size import ShotSizeError, classify_shots
        console.print("[bold]Shot-size pass[/bold] — classifying per-clip composition…")
        for a in analyses:
            unlabeled = [c for c in a.cuts.clips if not c.shot_size and c.thumbnail]
            if not unlabeled:
                continue
            thumb_paths = [DATA_ROOT / c.thumbnail for c in unlabeled]
            try:
                labels = classify_shots(thumb_paths, pack, model=model)
            except ShotSizeError as e:
                console.print(f"[yellow]shot-size skip[/yellow] {a.film.filename}: {e}")
                continue
            for clip, label in zip(unlabeled, labels):
                clip.shot_size = label
            (ANALYSES_DIR / f"{Path(a.film.filename).stem}.json").write_text(
                a.model_dump_json(indent=2)
            )
            console.print(f"  [green]labeled[/green] {a.film.filename}: {len(labels)} clips")

    stats = aggregate(analyses)
    if not include_gemini:
        stats = {**stats, "gemini_analyses": []}
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    DEFAULT_STATS.write_text(json.dumps(stats, indent=2))

    # Write the structured JSON profile FIRST — that artifact is what
    # downstream AI tools consume, and it's deterministic (no API call).
    profile = build_profile(analyses, stats)
    profile_output.parent.mkdir(parents=True, exist_ok=True)
    profile_output.write_text(json.dumps(profile, indent=2, default=str))
    console.print(f"[green]wrote[/green] {profile_output} ({len(profile.get('rules', []))} rules)")

    console.print(f"[bold]Aggregated[/bold] {stats['film_count']} films → calling Claude…")
    md = write_guide(stats, model=model)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(md)
    console.print(f"[green]wrote[/green] {output}")


@cli.command()
def stats() -> None:
    """Print quick stats summary."""
    analyses = _load_analyses()
    if not analyses:
        raise click.ClickException("no analyses found")
    s = aggregate(analyses)
    console.print(f"Films analyzed: {s['film_count']}")
    console.print(f"Avg duration: {s['duration']['avg_sec']}s "
                  f"(range {s['duration']['min_sec']}-{s['duration']['max_sec']})")
    console.print(f"Avg clips/film: {s['clip_counts']['avg']} "
                  f"(range {s['clip_counts']['min']}-{s['clip_counts']['max']})")
    console.print(f"Avg clip duration: {s['pacing']['avg_clip_sec']}s "
                  f"(σ {s['pacing']['std_dev_sec']})")
    t = s["transitions"]
    parts = [
        f"{t['hard_cut_pct']}% hard cut",
        f"{t['dissolve_pct']}% dissolve",
        f"{t['fade_pct']}% fade",
    ]
    if t.get("still_hold_pct"):
        parts.append(f"{t['still_hold_pct']}% still hold")
    console.print("Transitions: " + ", ".join(parts))
    if s.get("audio"):
        a = s["audio"]
        console.print(f"First speech at: {a['first_speech_at_pct_avg']}% into film "
                      f"(~{a['first_speech_at_sec_avg']}s)")
        console.print(f"Speech % of film: {a['speech_over_music_pct_avg']}% over music, "
                      f"{a['speech_only_pct_avg']}% solo")


@cli.command(name="list")
def list_cmd() -> None:
    """List all analyzed films."""
    analyses = _load_analyses()
    if not analyses:
        raise click.ClickException("no analyses found")
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Film")
    table.add_column("Duration", justify="right")
    table.add_column("Clips", justify="right")
    table.add_column("Avg Clip", justify="right")
    table.add_column("Extras")
    table.add_column("Analyzed")
    for i, a in enumerate(analyses, 1):
        mins, secs = divmod(int(a.film.duration_sec), 60)
        extras = []
        if a.audio:
            extras.append("audio")
        if a.transcript:
            extras.append("trx")
        if a.gemini_analysis:
            extras.append("gemini")
        if any(c.label for c in a.chapters):
            extras.append("vision")
        table.add_row(
            str(i), a.film.filename, f"{mins}:{secs:02d}",
            str(a.cuts.total), f"{a.pacing.avg_clip_duration_sec}s",
            ",".join(extras) or "—",
            a.analyzed_at.date().isoformat(),
        )
    console.print(table)


@cli.command()
@click.argument("fcpxml_path", type=click.Path(exists=True, path_type=Path))
def compare(fcpxml_path: Path) -> None:
    """Compare a rough-cut FCPXML against the established style profile."""
    if not DEFAULT_STATS.exists():
        raise click.ClickException("no aggregate stats — run `film-style guide` first")
    profile = json.loads(DEFAULT_STATS.read_text())
    cut = parse_fcpxml(fcpxml_path)

    console.rule(f"Style Comparison: {fcpxml_path.name}")
    console.print(f"vs. profile of {profile['film_count']} films\n")

    # Duration
    dur = cut["total_duration_sec"]
    pdur = profile["duration"]
    mins, secs = divmod(int(dur), 60)
    in_range = pdur["min_sec"] <= dur <= pdur["max_sec"]
    badge = "[green]✓[/green]" if in_range else "[yellow]⚠[/yellow]"
    console.print(f"DURATION  {mins}:{secs:02d}  "
                  f"(profile {int(pdur['min_sec'])}s–{int(pdur['max_sec'])}s)  {badge}")

    # Clip count
    expected_clips = profile["clip_counts"]["avg"]
    delta_clips = (cut["clip_count"] - expected_clips) / expected_clips * 100 if expected_clips else 0
    console.print(f"CLIPS     {cut['clip_count']}  (profile avg {expected_clips})  "
                  f"{'+' if delta_clips >= 0 else ''}{delta_clips:.0f}%")

    # Avg clip duration
    expected_avg = profile["pacing"]["avg_clip_sec"]
    actual_avg = cut["avg_clip_sec"]
    delta_pace = (actual_avg - expected_avg) / expected_avg * 100 if expected_avg else 0
    console.print(f"AVG CLIP  {actual_avg:.2f}s  (profile {expected_avg}s)  "
                  f"{'+' if delta_pace >= 0 else ''}{delta_pace:.0f}%")

    # Dissolves
    expected_diss = profile["transitions"].get("avg_dissolves_per_film") or 0
    console.print(f"DISSOLVES {cut['dissolves']}  (profile avg {expected_diss})")

    # Decile pacing comparison.
    pacing_deviations: list[tuple[int, float, float]] = []
    expected_deciles = profile["pacing"].get("avg_deciles") or []
    durations = cut.get("clip_durations") or []
    if expected_deciles and durations:
        n = len(durations)
        actual_deciles = [
            sum(durations[i * n // 10:(i + 1) * n // 10] or [0.0])
            / max(1, len(durations[i * n // 10:(i + 1) * n // 10]))
            for i in range(10)
        ]
        console.print("\nPACING CURVE (decile)")
        for i, (a, e) in enumerate(zip(actual_deciles, expected_deciles)):
            tag = ""
            if e:
                d = (a - e) / e * 100
                if abs(d) > 25:
                    tag = f"  [yellow]{'+' if d >= 0 else ''}{d:.0f}%[/yellow]"
                    pacing_deviations.append((i, a, e))
            console.print(f"  {i*10:>3}-{(i+1)*10:<3}%  actual {a:.2f}s  profile {e:.2f}s{tag}")

    # Audio (FCPXML).
    audio = cut.get("audio") or {}
    if audio.get("has_audio"):
        console.print(f"\nAUDIO TRACK  {audio['audio_clip_count']} clips, "
                      f"{audio['audio_total_duration_sec']}s"
                      + (f"  roles: {', '.join(audio['audio_roles'])}" if audio['audio_roles'] else ""))
    else:
        console.print("\nAUDIO TRACK  none detected in FCPXML")

    console.print()
    suggestions = []
    if abs(delta_pace) > 15:
        direction = "tighten" if delta_pace > 0 else "lengthen"
        suggestions.append(f"{direction} clips toward {expected_avg}s avg")
    if abs(delta_clips) > 20:
        direction = "remove" if delta_clips > 0 else "add"
        suggestions.append(f"{direction} clips toward {expected_clips} total")
    if expected_diss and cut["dissolves"] > expected_diss * 1.5:
        suggestions.append(f"reduce dissolves toward ~{expected_diss}")
    for i, actual_d, expected_d in pacing_deviations:
        direction = "tighten" if actual_d > expected_d else "lengthen"
        suggestions.append(
            f"{direction} clips at {i*10}-{(i+1)*10}% mark "
            f"({actual_d:.2f}s → {expected_d:.2f}s)"
        )
    if suggestions:
        console.print("[bold]Suggestions:[/bold]")
        for i, s in enumerate(suggestions, 1):
            console.print(f"  {i}. {s}")
    else:
        console.print("[green]No significant deviations.[/green]")


@cli.command()
@click.argument("stem")
@click.option("--top", default=3, show_default=True,
              help="How many similar films to return.")
def match(stem: str, top: int) -> None:
    """Find the films in the archive most stylistically similar to STEM."""
    from .matchmaker import biggest_differences, find_similar

    target_path = ANALYSES_DIR / f"{stem}.json"
    if not target_path.exists():
        raise click.ClickException(f"no analysis at {target_path}")
    target = FilmAnalysis.model_validate_json(target_path.read_text())

    archive: list[FilmAnalysis] = []
    for p in sorted(ANALYSES_DIR.glob("*.json")):
        try:
            archive.append(FilmAnalysis.model_validate_json(p.read_text()))
        except Exception:
            continue

    matches = find_similar(target, archive, top_n=top)
    if not matches:
        console.print(f"[yellow]No other films in the archive to compare against.[/yellow]")
        return

    console.rule(f"Most similar to {target.film.filename}")
    for i, m in enumerate(matches, 1):
        console.print(
            f"  {i}. [bold]{m['filename']}[/bold]  "
            f"similarity {m['similarity']:.3f}  "
            f"(distance {m['distance']:.3f})"
        )
        # Show the top-2 dimensions where they differ most.
        target_film = next((f for f in archive
                            if f.film.filename == m["filename"]), None)
        if target_film:
            diffs = biggest_differences(target, target_film, top_n=2)
            for d in diffs:
                console.print(f"     [dim]{d['dimension']:<22}[/dim] Δ {d['delta']:.3f}")


@cli.command()
@click.argument("stem")
@click.option("--set", "set_", multiple=True, metavar="KEY=VALUE",
              help="Set or update a metadata field. Repeatable.")
@click.option("--unset", multiple=True, metavar="KEY",
              help="Remove a metadata field. Repeatable.")
@click.option("--show", is_flag=True, help="Print existing tags and exit.")
def tag(stem: str, set_: tuple[str, ...], unset: tuple[str, ...], show: bool) -> None:
    """View / edit per-film metadata (venue, season, music genre, etc.)."""
    from .metadata import CURATED_KEYS, parse_set_arg, merge as merge_md

    target = ANALYSES_DIR / f"{stem}.json"
    if not target.exists():
        raise click.ClickException(f"no analysis at {target}")

    analysis = FilmAnalysis.model_validate_json(target.read_text())

    if show or not (set_ or unset):
        if not analysis.metadata:
            console.print(f"[dim]{stem}[/dim] has no tags.")
        else:
            for k, v in sorted(analysis.metadata.items()):
                console.print(f"  [bold]{k}[/bold] = {v}")
        if not (set_ or unset):
            return

    updates: dict = {}
    for arg in set_:
        try:
            k, v = parse_set_arg(arg)
        except ValueError as e:
            raise click.ClickException(str(e))
        if k in CURATED_KEYS and v not in CURATED_KEYS[k]:
            console.print(
                f"[yellow]note[/yellow] '{v}' is not in the curated values for '{k}': "
                f"{', '.join(CURATED_KEYS[k])}. Saving anyway."
            )
        updates[k] = v
    for k in unset:
        updates[k.strip().lower()] = None

    analysis.metadata = merge_md(analysis.metadata, updates)
    target.write_text(analysis.model_dump_json(indent=2))
    console.print(f"[green]wrote[/green] {target}")
    for k, v in sorted(analysis.metadata.items()):
        console.print(f"  [bold]{k}[/bold] = {v}")


@cli.command(name="predict-cuts")
@click.argument("song", type=click.Path(exists=True, path_type=Path))
@click.option("--profile", type=click.Path(path_type=Path), default=DEFAULT_PROFILE,
              show_default=True, help="style-profile.json to read pacing from.")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Write FCPXML marker track to this path. Default: <song>.predicted.fcpxml")
@click.option("--target-duration-sec", type=float, default=None,
              help="Stop predicting after this many seconds of song.")
@click.option("--snap-tolerance-sec", type=float, default=0.12, show_default=True,
              help="How close to a beat counts as 'snapped'.")
def predict_cuts_cmd(song: Path, profile: Path, output: Path | None,
                     target_duration_sec: float | None, snap_tolerance_sec: float) -> None:
    """Predict cut times for a song in your established style. Emits FCPXML."""
    from .predict_cuts import PredictCutsError, predict_cuts, to_fcpxml_markers

    if not profile.exists():
        raise click.ClickException(
            f"no style profile at {profile}. Run `film-style guide` first."
        )
    profile_data = json.loads(profile.read_text())

    console.print(f"[bold]Predicting cuts[/bold] for {song.name}")
    try:
        result = predict_cuts(
            song, profile_data,
            target_duration_sec=target_duration_sec,
            snap_tolerance_sec=snap_tolerance_sec,
        )
    except PredictCutsError as e:
        raise click.ClickException(str(e))

    console.print(
        f"  tempo {result['song_tempo_bpm']} BPM · "
        f"{result['predicted_cut_count']} cuts · "
        f"{result['on_beat_pct']}% on beat"
    )
    out_path = output or song.with_suffix(".predicted.fcpxml")
    out_path.write_text(to_fcpxml_markers(result, song_basename=song.stem))
    console.print(f"[green]wrote[/green] {out_path}")


@cli.command(name="import")
@click.argument("url")
@click.option("--output", "-o", type=click.Path(path_type=Path),
              default=Path.home() / "films" / "imports",
              show_default=True, help="Where downloaded MP4s land.")
@click.option("--cookies-browser",
              type=click.Choice(["safari", "chrome", "firefox", "edge", "brave",
                                 "vivaldi", "chromium", "opera"]),
              help="Read cookies from this browser to access private videos.")
@click.option("--quality", default="bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
              help="yt-dlp -f format string.")
@click.option("--no-archive", is_flag=True,
              help="Don't maintain a re-run-safe download archive.")
def import_videos(url: str, output: Path, cookies_browser: str | None,
                  quality: str, no_archive: bool) -> None:
    """Download videos from a URL — Vimeo, YouTube, or any yt-dlp source.

    \b
    Vimeo:    vimeo.com/123, vimeo.com/showcase/12, vimeo.com/handle
    YouTube:  youtube.com/watch?v=..., youtube.com/playlist?list=...,
              youtube.com/@channel
    """
    from .vimeo_import import VimeoImportError, download

    console.print(f"[bold]Importing[/bold] {url}")
    console.print(f"  → {output}")
    if cookies_browser:
        console.print(f"  cookies via {cookies_browser}")
    console.print()

    try:
        for line in download(
            url, output,
            cookies_browser=cookies_browser,
            quality=quality,
            archive=not no_archive,
        ):
            console.print(f"[dim]{line}[/dim]")
    except VimeoImportError as e:
        raise click.ClickException(str(e))

    console.print(f"\n[green]Done.[/green] Now run: [bold]film-style analyze {output}[/bold]")


# Legacy alias — keep `import-vimeo` working for anyone scripted on it.
@cli.command(name="import-vimeo", hidden=True)
@click.argument("url")
@click.pass_context
def _legacy_import_vimeo(ctx, url: str) -> None:
    """Deprecated; use `film-style import` instead."""
    ctx.invoke(import_videos, url=url, output=Path.home() / "films" / "imports",
               cookies_browser=None,
               quality="bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
               no_archive=False)


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Interface to bind. Loopback by default — local-only.")
@click.option("--port", default=7421, show_default=True, type=int,
              help="Port to bind.")
@click.option("--no-browser", is_flag=True, help="Don't auto-open the browser.")
def serve(host: str, port: int, no_browser: bool) -> None:
    """Open the Atelier dashboard in your browser."""
    from .server import serve as _serve
    _serve(host=host, port=port, open_browser=not no_browser)


@cli.command(name="export-notebooklm")
@click.option("--output", "-o", type=click.Path(path_type=Path),
              default=DATA_ROOT / "notebooklm-brief.md",
              show_default=True, help="Where to write the brief.")
@click.option("--no-inspirations", is_flag=True,
              help="Omit saved YouTube inspirations.")
def export_notebooklm(output: Path, no_inspirations: bool) -> None:
    """Export a markdown brief suitable for ingesting into NotebookLM."""
    from .notebooklm_export import write_brief

    analyses: list[FilmAnalysis] = []
    for p in sorted(ANALYSES_DIR.glob("*.json")):
        try:
            analyses.append(FilmAnalysis.model_validate_json(p.read_text()))
        except Exception:
            continue
    if not analyses:
        raise click.ClickException(
            "no analyses found — run `film-style analyze` first."
        )

    profile: dict = {}
    if DEFAULT_PROFILE.is_file():
        try:
            profile = json.loads(DEFAULT_PROFILE.read_text())
        except json.JSONDecodeError:
            profile = {}

    inspirations = None
    if not no_inspirations:
        ins_path = DATA_ROOT / "inspirations.json"
        if ins_path.is_file():
            try:
                inspirations = json.loads(ins_path.read_text())
            except json.JSONDecodeError:
                inspirations = None

    write_brief(analyses, profile, output, inspirations=inspirations)
    console.print(f"[green]wrote[/green] {output}")
    console.print(
        f"  Open it, copy its contents, and in NotebookLM click "
        "[bold]+ Add source[/bold] → [bold]Paste text[/bold]."
    )


@cli.command(name="mcp-serve")
def mcp_serve() -> None:
    """Run the MCP server over stdio (for Claude Desktop and other MCP clients).

    Configure Claude Desktop via ~/Library/Application Support/Claude/
    claude_desktop_config.json — see the README for the exact JSON snippet.
    Do not run this command manually in a terminal; the MCP client launches it.
    """
    from .mcp_server import MCPServerError, run_stdio
    try:
        run_stdio()
    except MCPServerError as e:
        raise click.ClickException(str(e))


@cli.command()
@click.option("--init", is_flag=True, help="Write a default config.json.")
def config(init: bool) -> None:
    """Show or initialize ~/.film-style-analyzer/config.json."""
    if init:
        path = write_default_config()
        console.print(f"[green]wrote[/green] {path}")
        return
    cfg = load_config()
    console.print(f"Config path: {CONFIG_PATH} (exists: {CONFIG_PATH.exists()})")
    for k, v in cfg.__dict__.items():
        console.print(f"  {k} = {v}")
