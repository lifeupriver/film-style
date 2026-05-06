"""WhisperX transcription with word-level alignment + speaker diarization."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class TranscribeError(RuntimeError):
    pass


def _select_device() -> tuple[str, str]:
    """Return (device, compute_type). WhisperX uses CTranslate2 which only
    supports CUDA + CPU — MPS is not supported, so Apple Silicon falls back to CPU."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def transcribe(
    wav_path: Path,
    model_name: str = "large-v3",
    language: str = "en",
    diarize: bool = True,
    batch_size: int = 16,
) -> dict:
    """Transcribe a WAV file. Returns {segments, total_words, speakers_detected,
    longest_speech_excerpt_sec}. Raises TranscribeError on hard failures."""
    try:
        import whisperx
    except ImportError as e:
        raise TranscribeError(
            "whisperx not installed. Install with: pip install 'film-style-analyzer[audio]'"
        ) from e

    device, compute_type = _select_device()

    try:
        model = whisperx.load_model(model_name, device, compute_type=compute_type, language=language)
        audio = whisperx.load_audio(str(wav_path))
        result: dict[str, Any] = model.transcribe(audio, batch_size=batch_size, language=language)

        # Word-level alignment.
        try:
            align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
            result = whisperx.align(
                result["segments"], align_model, metadata, audio, device,
                return_char_alignments=False,
            )
        except Exception:
            # Alignment is best-effort; segments without word timestamps are still useful.
            pass

        # Speaker diarization (requires HF_TOKEN for pyannote model download).
        speakers_detected = 0
        if diarize and os.environ.get("HF_TOKEN"):
            try:
                diarize_model = whisperx.DiarizationPipeline(
                    use_auth_token=os.environ["HF_TOKEN"], device=device,
                )
                diarize_segments = diarize_model(audio)
                result = whisperx.assign_word_speakers(diarize_segments, result)
                speakers_detected = len({
                    s.get("speaker") for s in result.get("segments", []) if s.get("speaker")
                })
            except Exception:
                pass
    except Exception as e:
        raise TranscribeError(f"whisperx failed: {e}") from e

    segments = []
    total_words = 0
    longest = 0.0
    for s in result.get("segments", []):
        seg_start = float(s.get("start", 0.0))
        seg_end = float(s.get("end", 0.0))
        words = [
            {"word": w.get("word", ""), "start": w.get("start"), "end": w.get("end")}
            for w in s.get("words", [])
        ]
        total_words += len(s.get("text", "").split())
        longest = max(longest, seg_end - seg_start)
        segments.append({
            "start_sec": seg_start,
            "end_sec": seg_end,
            "text": s.get("text", "").strip(),
            "speaker": s.get("speaker"),
            "words": words,
        })

    return {
        "segments": segments,
        "total_words": total_words,
        "speakers_detected": speakers_detected,
        "longest_speech_excerpt_sec": round(longest, 2),
    }
