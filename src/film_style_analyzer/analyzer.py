"""Per-film analysis orchestrator."""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .chapters import group as group_chapters
from .color_analysis import analyze_film_color
from .dissolve_measure import measure_dissolves
from .genre_pack import GenrePack
from .media_probe import probe
from .scene_detect import detect_clips
from .schemas import ChapterRecord, Cuts, FilmAnalysis, Pacing, Structure, Transitions
from .thumbnails import extract as extract_thumbs

logger = logging.getLogger(__name__)

HISTOGRAM_BUCKETS = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8)]


def _histogram(durations: list[float]) -> dict[str, int]:
    h = {f"{lo}-{hi}s": 0 for lo, hi in HISTOGRAM_BUCKETS}
    h["8s+"] = 0
    for d in durations:
        placed = False
        for lo, hi in HISTOGRAM_BUCKETS:
            if lo <= d < hi:
                h[f"{lo}-{hi}s"] += 1
                placed = True
                break
        if not placed:
            h["8s+"] += 1
    return h


def _quartile_avgs(durations: list[float]) -> dict[str, float]:
    if not durations:
        return {f"q{i}_avg_sec": 0.0 for i in range(1, 5)}
    n = len(durations)
    out = {}
    for i in range(4):
        chunk = durations[i * n // 4:(i + 1) * n // 4] or [0.0]
        out[f"q{i + 1}_avg_sec"] = round(statistics.fmean(chunk), 2)
    return out


def _decile_avgs(durations: list[float]) -> list[float]:
    if not durations:
        return [0.0] * 10
    n = len(durations)
    return [round(statistics.fmean(durations[i * n // 10:(i + 1) * n // 10] or [0.0]), 2) for i in range(10)]


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
    meta = probe(path)
    clips = detect_clips(
        path,
        min_scene_length_sec=min_scene_length_sec,
        threshold=threshold,
    )

    thumbs_dir = thumbs_root / path.stem
    extract_thumbs(path, clips, thumbs_dir)
    chapters = [
        ChapterRecord(**vars(c)) for c in group_chapters(clips)
    ]

    audio_data: dict | None = None
    transcript_data: dict | None = None
    gemini_data: dict | None = None
    color_summary: dict | None = None
    music_data: dict | None = None

    # Color pass.
    if not skip_color:
        try:
            result = analyze_film_color(path, clips, every_n=color_every_n_clips)
            color_summary = result.get("summary")
            for clip, per in zip(clips, result.get("per_clip") or []):
                if per is not None:
                    clip.color = per
        except Exception as e:
            logger.warning("color analysis failed for %s: %s", path.name, e)

    wav_path: Path | None = None  # kept around for the music pass below
    audio_dir = (audio_root or (thumbs_root.parent / "audio"))

    # If music analysis is requested but full audio is skipped, we still need
    # to extract a WAV — just don't run classification or transcription on it.
    need_wav = (not skip_audio) or (not skip_music)

    if need_wav:
        from .audio_extract import AudioExtractError, extract_wav
        wav_path = audio_dir / f"{path.stem}.wav"
        try:
            extract_wav(path, wav_path)
        except AudioExtractError as e:
            logger.warning("audio extraction failed for %s: %s", path.name, e)
            wav_path = None  # type: ignore[assignment]

    if not skip_audio and wav_path is not None:
        from .audio_classify import ClassifyError, classify
        from .audio_transcribe import TranscribeError, transcribe

        try:
            audio_data = classify(wav_path, total_duration_sec=meta.duration_sec)
        except ClassifyError as e:
            logger.warning("audio classification failed for %s: %s", path.name, e)

        try:
            transcript_data = transcribe(
                wav_path, model_name=whisper_model, language=language, diarize=diarize,
            )
        except TranscribeError as e:
            logger.warning("transcription failed for %s: %s", path.name, e)

    # Music pass — uses the WAV from the audio block. Works even when audio
    # classification was skipped: we then treat the entire track as music.
    if not skip_music and wav_path is not None:
        from .music_analyze import MusicAnalyzeError, analyze_music, score_cut_beat_alignment
        # Prefer real classified music segments. Otherwise treat the whole
        # track as one music segment — for wedding films that's a fair
        # approximation since music is almost always running.
        if audio_data and audio_data.get("segments"):
            segments = audio_data.get("segments")
        else:
            segments = [{
                "type": "music",
                "start_sec": 0.0,
                "end_sec": meta.duration_sec,
                "duration_sec": meta.duration_sec,
            }]
        try:
            music_data = analyze_music(wav_path, segments)
            cut_times = [c.start_sec for c in clips[1:]]
            beats = music_data.get("beats") or []
            if cut_times and beats:
                music_data["beat_alignment"] = score_cut_beat_alignment(cut_times, beats)
        except MusicAnalyzeError as e:
            logger.warning("music analysis failed for %s: %s", path.name, e)

    if not skip_audio and wav_path is not None and cleanup_audio:
        try:
            wav_path.unlink(missing_ok=True)
        except OSError:
            pass

    if run_gemini:
        from .gemini_analyzer import GeminiError, analyze as run_gemini_analyze
        try:
            gemini_data = run_gemini_analyze(
                path, pack, duration_sec=meta.duration_sec, cut_count=len(clips),
                model_name=gemini_model,
            )
        except GeminiError as e:
            logger.warning("gemini analysis failed for %s: %s", path.name, e)

    durations = [c.duration_sec for c in clips]
    timestamps = [c.start_sec for c in clips]

    pacing = Pacing(
        avg_clip_duration_sec=round(statistics.fmean(durations), 2) if durations else 0.0,
        median_clip_duration_sec=round(statistics.median(durations), 2) if durations else 0.0,
        std_dev_sec=round(statistics.pstdev(durations), 2) if len(durations) > 1 else 0.0,
        min_clip_sec=round(min(durations), 2) if durations else 0.0,
        max_clip_sec=round(max(durations), 2) if durations else 0.0,
        clip_duration_histogram=_histogram(durations),
        pacing_curve_by_quartile=_quartile_avgs(durations),
        pacing_curve_by_decile=_decile_avgs(durations),
    )

    transitions = Transitions()
    dissolve_positions = []
    total = len(clips)
    for c in clips:
        # Count transition_out as the canonical transition between this clip and the next.
        t = c.transition_out
        if t == "hard_cut":
            transitions.hard_cut += 1
        elif t == "dissolve":
            transitions.dissolve += 1
            if total:
                dissolve_positions.append(round(c.index / total, 3))
        elif t == "fade_in":
            transitions.fade_in += 1
        elif t == "fade_out":
            transitions.fade_out += 1
        elif t == "still_hold":
            transitions.still_hold += 1
        if c.index == 0 and c.transition_in == "fade_in":
            transitions.fade_in += 1
    transitions.dissolve_positions_pct = dissolve_positions

    dissolve_boundary_times = [
        c.end_sec for c in clips if c.transition_out == "dissolve"
    ]
    if dissolve_boundary_times:
        try:
            measured = measure_dissolves(path, dissolve_boundary_times, fps=meta.frame_rate)
            transitions.avg_dissolve_duration_sec = round(
                sum(measured) / len(measured), 3
            ) if measured else 0.0
        except Exception as e:
            logger.warning("dissolve measurement failed for %s: %s", path.name, e)
            transitions.avg_dissolve_duration_sec = 0.5
    else:
        transitions.avg_dissolve_duration_sec = 0.0

    first_5 = durations[:5]
    last_5 = durations[-5:]
    structure = Structure(
        opening={
            "first_cut_at_sec": round(clips[0].end_sec, 2) if clips else 0.0,
            "first_5_clips_avg_duration_sec": round(statistics.fmean(first_5), 2) if first_5 else 0.0,
        },
        closing={
            "last_cut_at_sec": round(clips[-1].start_sec, 2) if clips else 0.0,
            "last_5_clips_avg_duration_sec": round(statistics.fmean(last_5), 2) if last_5 else 0.0,
            "fade_to_black": clips[-1].transition_out == "fade_out" if clips else False,
            "fade_duration_sec": 2.0 if clips and clips[-1].transition_out == "fade_out" else 0.0,
        },
    )

    return FilmAnalysis(
        analyzed_at=datetime.now(timezone.utc),
        analyzer_version=__version__,
        film=meta,
        cuts=Cuts(total=len(clips), timestamps_sec=timestamps, clips=clips),
        pacing=pacing,
        transitions=transitions,
        chapters=chapters,
        structure=structure,
        audio=audio_data,
        transcript=transcript_data,
        gemini_analysis=gemini_data,
        color=color_summary,
        music=music_data,
    )
