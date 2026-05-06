"""Optional Gemini 2.5 Pro narrative analysis of a finished film.

The narrative prompt comes from the active genre pack so commercial,
documentary, music-video, etc. analyses ask the right questions.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .genre_pack import GenrePack


def build_film_prompt(pack: GenrePack, duration: str, cuts: int) -> str:
    return pack.prompts["gemini_film_prompt"].format(duration=duration, cuts=cuts)


def build_youtube_prompt(pack: GenrePack) -> str:
    return pack.prompts["gemini_youtube_prompt"]


class GeminiError(RuntimeError):
    pass


def _format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _extract_json(text: str) -> dict:
    # Strip ```json … ``` fences first (greedy so nested braces survive).
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    payload = (fenced.group(1) if fenced else text).strip()
    # Anchor to first '{' / last '}' so any prose around the JSON is dropped.
    start = payload.find("{")
    end = payload.rfind("}")
    if start >= 0 and end > start:
        payload = payload[start:end + 1]
    return json.loads(payload)


def analyze_youtube_url(
    url: str,
    pack: GenrePack,
    *,
    custom_prompt: str | None = None,
    model_name: str = "gemini-2.5-pro",
) -> dict:
    """Analyze a YouTube video via Gemini's native YouTube URL support.

    No download required — Gemini fetches the video itself. Fast (~30 sec)
    qualitative analysis only; doesn't replace the local pipeline's
    pacing/color/audio measurement.

    Returns the parsed JSON response.
    """
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GOOGLE_API_KEY (or GEMINI_API_KEY) not set")

    if "youtube.com" not in url and "youtu.be" not in url:
        raise GeminiError(f"not a YouTube URL: {url}")

    try:
        import google.generativeai as genai
    except ImportError as e:
        raise GeminiError(
            "google-generativeai not installed. Install with: pip install 'film-style-analyzer[gemini]'"
        ) from e

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    prompt = custom_prompt or build_youtube_prompt(pack)

    try:
        response = model.generate_content(
            [
                {"file_data": {"file_uri": url, "mime_type": "video/mp4"}},
                prompt,
            ],
            generation_config={"response_mime_type": "application/json"},
        )
        text = response.text or ""
    except Exception as e:
        raise GeminiError(f"gemini analysis failed: {e}") from e

    try:
        parsed = _extract_json(text)
    except json.JSONDecodeError:
        parsed = {"raw_response": text}

    return {
        "source": "youtube",
        "url": url,
        "model": model_name,
        "analysis": parsed,
    }


def analyze(film_path: Path, pack: GenrePack, duration_sec: float, cut_count: int,
            model_name: str = "gemini-2.5-pro") -> dict:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise GeminiError("GOOGLE_API_KEY (or GEMINI_API_KEY) not set")

    try:
        import google.generativeai as genai
    except ImportError as e:
        raise GeminiError(
            "google-generativeai not installed. Install with: pip install 'film-style-analyzer[gemini]'"
        ) from e

    genai.configure(api_key=api_key)

    uploaded = None
    try:
        try:
            uploaded = genai.upload_file(path=str(film_path))
        except Exception as e:
            raise GeminiError(f"upload failed: {e}") from e

        # Wait for ACTIVE state — videos take time to process.
        deadline = time.time() + 600
        while uploaded.state.name == "PROCESSING" and time.time() < deadline:
            time.sleep(5)
            uploaded = genai.get_file(uploaded.name)
        if uploaded.state.name != "ACTIVE":
            raise GeminiError(f"upload did not become ACTIVE (state={uploaded.state.name})")

        model = genai.GenerativeModel(model_name)
        prompt = build_film_prompt(pack, duration=_format_duration(duration_sec), cuts=cut_count)
        try:
            response = model.generate_content(
                [uploaded, prompt],
                generation_config={"response_mime_type": "application/json"},
            )
            text = response.text or ""
        except Exception as e:
            raise GeminiError(f"gemini generate_content failed: {e}") from e
    finally:
        if uploaded is not None:
            try:
                genai.delete_file(uploaded.name)
            except Exception:
                pass

    try:
        return _extract_json(text)
    except json.JSONDecodeError:
        return {"raw_response": text}
