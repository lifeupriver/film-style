"""Optional Gemini 2.5 Pro narrative analysis of a wedding film."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

PROMPT = """You are analyzing a finished wedding film to extract the editor's style.
This film is {duration} long with {cuts} cuts.

Analyze the film and answer these questions precisely:

1. OPENING: Describe the first 30 seconds. What is the first shot? How many
   establishing shots before the first "story" shot? When does the music start?
   When does the first cut happen?

2. SCENE FLOW: List every scene transition you observe. What visual or audio
   cue marks each transition? Are scenes strictly chronological or does the
   editor intercut between parallel timelines?

3. AUDIO DESIGN: When does ceremony/speech audio first appear? Over what
   visuals is it placed? How long do speech excerpts run? Does the music ever
   fully cut out or always play underneath?

4. PACING FEEL: Where does the edit feel slow and lingering vs. fast and
   energetic? Is there a build? Where is the emotional peak?

5. SHOT SELECTION: Does the editor favor wide shots, close-ups, or a specific
   mix? Do you see a pattern in how shot sizes alternate?

6. CLOSING: Describe the final 30 seconds. How does the film end? What is the
   last shot? Is there a fade? How long does the final shot hold?

7. DISTINCTIVE CHOICES: What 3 things make this editor's style recognizable?
   What would you notice if you watched 10 of their films?

Respond in structured JSON with one top-level key per question:
{{"opening": ..., "scene_flow": ..., "audio_design": ..., "pacing_feel": ...,
"shot_selection": ..., "closing": ..., "distinctive_choices": [...]}}"""


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


YOUTUBE_PROMPT = """You are analyzing a wedding film (or a film whose editing
style might inspire wedding-film editing) on YouTube.

Answer these questions precisely:

1. PACING: How does the editor handle pacing? Is it fast or slow? Does it
   build, plateau, or release? Where does it accelerate?

2. SHOT SELECTION: What kinds of shots dominate (wide/medium/close-up,
   handheld/locked, drone)? Is there a pattern in how shot sizes alternate?

3. AUDIO DESIGN: When does music play? When does speech enter? Does music
   continue under speech or drop out? Are ambient sounds featured?

4. COLOR / GRADE: What's the dominant tonal approach (warm/cool, low-key/
   high-key, saturated/desaturated)? Any signature looks (e.g., milky shadows,
   crushed blacks, lifted contrast)?

5. STRUCTURE: How does the film open and close? What's the narrative arc?

6. DISTINCTIVE CHOICES: Three things that make this editor's style
   recognizable. What would you notice if you watched 10 of their films?

7. RELEVANCE: How might this style translate to wedding-film editing?
   What would be a clear and specific takeaway for the user's edits?

Respond in structured JSON with one top-level key per question:
opening, pacing, shot_selection, audio_design, color_grade, structure,
distinctive_choices (array), relevance.
"""


def analyze_youtube_url(
    url: str,
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
    prompt = custom_prompt or YOUTUBE_PROMPT

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


def analyze(film_path: Path, duration_sec: float, cut_count: int,
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
        prompt = PROMPT.format(duration=_format_duration(duration_sec), cuts=cut_count)
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
