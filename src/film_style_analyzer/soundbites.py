"""Learn how the editor chooses spoken lines.

Wedding films are built on spoken audio: vows, letters, toasts. Eddie builds
cuts by choosing soundbites from transcripts, so the most useful thing to
learn is which lines this editor keeps.

For every registered project, each source with a transcript is matched
against the audio the editor actually used from it (audible, non-music
events, in the source's own time). Each transcript line is marked kept or
dropped. The result is a labelled set of examples plus measured tendencies:
how much of a speech is kept, which part of it, how long the kept lines are,
whether lines are reordered, and which lines open and close the films.
"""

from __future__ import annotations

import os
import statistics
from typing import Any

from .edit_decisions import intersect_length, merge_ranges

KEPT_MIN_OVERLAP = 0.5       # share of a line that must be used to count as kept
MAX_EXAMPLE_LINES = 150      # per source, in examples

SOUNDBITE_RULES_SYSTEM = (
    "You are helping a wedding filmmaker write down how they choose spoken "
    "lines (vows, letters, toasts, speeches) for their films. You get "
    "transcripts of raw recordings with each line marked KEPT or dropped, "
    "plus measured tendencies. Write 6-12 short, concrete rules an assistant "
    "could follow to pick lines the same way: what kind of line is kept, "
    "what is cut, how long the kept passages run, where in a speech they "
    "come from, what opens and closes the film. Use the editor's own lines "
    "as brief examples. Plain markdown bullet list, no preamble."
)


def normalize_transcript(t: dict) -> list[dict]:
    """Accept WhisperX output (start_sec/end_sec), Eddie get_transcript
    output or similar (start/end), and return sorted segments."""
    segs = t.get("segments") if isinstance(t, dict) else t
    out = []
    for s in segs or []:
        start = s.get("start_sec", s.get("start"))
        end = s.get("end_sec", s.get("end"))
        text = (s.get("text") or "").strip()
        if start is None or end is None or not text:
            continue
        out.append({"start": float(start), "end": float(end), "text": text,
                    "speaker": s.get("speaker") or s.get("speakerName")})
    out.sort(key=lambda s: s["start"])
    return out


def _spoken_use(project: dict) -> dict[str, list[dict]]:
    """Per source: used spoken ranges in file-relative time, with the film
    time each range plays at."""
    by: dict[str, list[dict]] = {}
    for e in project["events"]:
        if not e["audible"] or e.get("is_music") or e.get("multicam"):
            continue
        if e["track"] == "video" and e["layer"] != 0:
            continue  # cutaway sound is rarely the line
        s0 = e.get("source_start") or 0.0
        lo, hi = sorted((e["source_in"] - s0, e["source_out"] - s0))
        by.setdefault(e["source_key"], []).append(
            {"lo": lo, "hi": hi, "film_sec": e["timeline_start"],
             "speed": e["speed"] or 1.0})
    return by


def label_lines(project: dict, transcripts: dict[str, dict]) -> list[dict]:
    """One record per source that has a transcript and was used."""
    out = []
    for key, uses in _spoken_use(project).items():
        if key not in transcripts:
            continue
        segs = normalize_transcript(transcripts[key])
        if not segs:
            continue
        ranges = merge_ranges([(u["lo"], u["hi"]) for u in uses])
        lines = []
        for i, s in enumerate(segs):
            dur = max(1e-6, s["end"] - s["start"])
            frac = intersect_length([(s["start"], s["end"])], ranges) / dur
            film_sec = None
            if frac >= KEPT_MIN_OVERLAP:
                for u in uses:
                    if u["lo"] <= s["start"] < u["hi"] or u["lo"] < s["end"] <= u["hi"]:
                        film_sec = round(u["film_sec"] + max(0.0, s["start"] - u["lo"]) / u["speed"], 2)
                        break
            lines.append({
                "i": i,
                "start": round(s["start"], 2),
                "end": round(s["end"], 2),
                "text": s["text"],
                "speaker": s["speaker"],
                "kept": frac >= KEPT_MIN_OVERLAP,
                "film_sec": film_sec,
            })
        if any(l["kept"] for l in lines):
            out.append({"source_key": key, "lines": lines})
    return out


def _runs(flags: list[bool]) -> list[int]:
    runs, n = [], 0
    for f in flags:
        if f:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    return runs


def build_soundbite_profile(project_records: list[dict],
                            transcripts: dict[str, dict]) -> dict:
    keep_rates, kept_dur, dropped_dur, kept_words = [], [], [], []
    position = {"beginning": 0, "middle": 0, "end": 0}
    run_lengths: list[int] = []
    reordered = 0
    sources = 0
    speakers: dict[str, int] = {}
    openers, closers, examples = [], [], []

    for rec in project_records:
        project = rec.get("project") or rec
        labelled = label_lines(project, transcripts)
        film_lines = []
        for src in labelled:
            lines = src["lines"]
            sources += 1
            n = len(lines)
            kept = [l for l in lines if l["kept"]]
            keep_rates.append(100 * len(kept) / n)
            for l in lines:
                (kept_dur if l["kept"] else dropped_dur).append(l["end"] - l["start"])
            for l in kept:
                kept_words.append(len(l["text"].split()))
                pos = l["i"] / max(1, n - 1)
                position["beginning" if pos < 1 / 3 else "middle" if pos < 2 / 3 else "end"] += 1
                if l["speaker"]:
                    speakers[l["speaker"]] = speakers.get(l["speaker"], 0) + 1
                if l["film_sec"] is not None:
                    film_lines.append((l["film_sec"], l["text"], src["source_key"]))
            run_lengths += _runs([l["kept"] for l in lines])
            order = [l["film_sec"] for l in kept if l["film_sec"] is not None]
            if any(b < a for a, b in zip(order, order[1:])):
                reordered += 1
            examples.append({
                "project": rec.get("name"),
                "film_stem": rec.get("film_stem"),
                "source_key": src["source_key"],
                "lines_total": n,
                "lines_kept": len(kept),
                "lines": lines[:MAX_EXAMPLE_LINES],
                "truncated": n > MAX_EXAMPLE_LINES,
            })
        if film_lines:
            film_lines.sort()
            openers.append({"project": rec.get("name"), "text": film_lines[0][1],
                            "source_key": film_lines[0][2]})
            closers.append({"project": rec.get("name"), "text": film_lines[-1][1],
                            "source_key": film_lines[-1][2]})

    def med(v):
        return round(statistics.median(v), 2) if v else None

    total_kept = sum(position.values())
    stats: dict[str, Any] = {
        "sources_with_speech": sources,
        "keep_rate_pct": med(keep_rates),
        "kept_line_sec": med(kept_dur),
        "dropped_line_sec": med(dropped_dur),
        "kept_line_words": med(kept_words),
        "kept_run_lines": med(run_lengths),
        "kept_from_pct": ({k: round(100 * v / total_kept, 1) for k, v in position.items()}
                          if total_kept else None),
        "reordered_sources_pct": round(100 * reordered / sources, 1) if sources else None,
        "kept_by_speaker": speakers,
    }
    return {
        "schema_version": "1.0",
        "project_count": len(project_records),
        "stats": stats,
        "rules": soundbite_rules(stats),
        "written_rules": None,
        "openers": openers,
        "closers": closers,
        "examples": examples,
    }


def soundbite_rules(s: dict) -> list[str]:
    if not s.get("sources_with_speech"):
        return []
    rules = []
    if s.get("keep_rate_pct") is not None:
        rules.append(f"Keep about {s['keep_rate_pct']:.0f}% of the lines of a speech or vow.")
    if s.get("kept_line_sec"):
        r = f"Kept lines run about {s['kept_line_sec']:.1f}s"
        if s.get("kept_line_words"):
            r += f" ({s['kept_line_words']:.0f} words)"
        if s.get("dropped_line_sec"):
            r += f"; dropped lines average {s['dropped_line_sec']:.1f}s"
        rules.append(r + ".")
    if s.get("kept_run_lines"):
        rules.append(f"Lines are kept in runs of about {s['kept_run_lines']:g} in a row.")
    if s.get("kept_from_pct"):
        p = s["kept_from_pct"]
        top = max(p, key=p.get)
        rules.append(f"Most kept lines come from the {top} of a speech "
                     f"({p['beginning']:.0f}% beginning, {p['middle']:.0f}% middle, "
                     f"{p['end']:.0f}% end).")
    if s.get("reordered_sources_pct") is not None:
        if s["reordered_sources_pct"] >= 25:
            rules.append(f"Lines are often reordered ({s['reordered_sources_pct']:.0f}% of "
                         "speeches play out of their spoken order).")
        else:
            rules.append("Lines usually play in the order they were spoken.")
    return rules


def examples_as_text(profile: dict, max_sources: int = 8, max_lines: int = 60) -> str:
    """Examples rendered for a prompt: ✓ marks a kept line."""
    parts = []
    for ex in profile.get("examples", [])[:max_sources]:
        parts.append(f"## {ex.get('project')} · {ex['source_key']} "
                     f"({ex['lines_kept']} of {ex['lines_total']} lines kept)")
        for l in ex["lines"][:max_lines]:
            parts.append(f"{'✓' if l['kept'] else '·'} {l['text']}")
    return "\n".join(parts)


def write_soundbite_rules(profile: dict, model: str, backend: str = "api") -> str:
    """Ask Claude to put the labelled examples into rules."""
    import json

    user = (
        "Measured tendencies:\n" + json.dumps(profile["stats"], indent=2)
        + "\n\nOpening lines of films:\n" + "\n".join(f"- {o['text']}" for o in profile["openers"])
        + "\n\nClosing lines of films:\n" + "\n".join(f"- {c['text']}" for c in profile["closers"])
        + "\n\nTranscripts (✓ = kept in the film, · = cut):\n" + examples_as_text(profile)
    )
    if backend == "cli":
        from .claude_cli import complete as claude_cli_complete
        return claude_cli_complete(prompt=user, system=SOUNDBITE_RULES_SYSTEM, max_turns=1)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set (or use claude_backend \"cli\").")
    from anthropic import Anthropic
    msg = Anthropic(api_key=api_key).messages.create(
        model=model, max_tokens=16000, system=SOUNDBITE_RULES_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


def transcribe_sources(project_records: list[dict], store, *, media_roots: list,
                       model: str = "large-v3", language: str = "en",
                       progress=None) -> dict[str, str]:
    """Transcribe each spoken source that has no transcript yet.

    Looks for the file at its recorded path, then by name under
    ``media_roots``. Returns {source_key: "transcribed" | "missing" | error}.
    """
    import tempfile
    from pathlib import Path

    from .audio_extract import extract_wav
    from .audio_transcribe import transcribe

    have = set(store.load_transcripts())
    wanted: dict[str, str] = {}
    for rec in project_records:
        project = rec.get("project") or rec
        for key in _spoken_use(project):
            if key in have or key in wanted:
                continue
            src = project["sources"].get(key) or {}
            wanted[key] = src.get("path") or src.get("name") or key

    index: dict[str, Path] = {}
    if media_roots:
        from .edit_decisions import source_key
        exts = {".mov", ".mp4", ".mxf", ".m4v", ".wav", ".mp3", ".m4a", ".aif", ".aiff"}
        for root in media_roots:
            for p in Path(root).expanduser().rglob("*"):
                if p.is_file() and p.suffix.lower() in exts:
                    index.setdefault(source_key(p.name), p)

    status: dict[str, str] = {}
    for n, (key, hint) in enumerate(wanted.items(), 1):
        path = Path(hint)
        if not path.is_file():
            path = index.get(key)
        if not path:
            status[key] = "missing"
            continue
        if progress:
            progress(n, len(wanted), path.name)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                wav = extract_wav(path, Path(tmp) / "a.wav")
                store.save_transcript(key, transcribe(wav, model_name=model, language=language))
            status[key] = "transcribed"
        except Exception as e:  # report and continue with the next file
            status[key] = f"failed: {e}"
    return status
