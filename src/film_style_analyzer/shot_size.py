"""Per-clip shot-size classification via Claude vision.

Sends batched per-clip middle-frame thumbnails to Claude and gets back a label
per image. Tighter label set than chapter classification — these answer
'what kind of shot is this?' (composition), not 'what part of the film'.

Shot taxonomy is genre-agnostic (extreme_wide ... aerial), but the prompt's
framing and 'insert' definition come from the active genre pack.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from .genre_pack import GenrePack

# Canonical shot-size taxonomy. All shipped genre packs use this same list,
# so the matchmaker (and similar consumers) can rely on it as a stable
# feature-vector dimension set.
SHOT_LABELS = [
    "extreme_wide", "wide", "medium_wide", "medium", "medium_close",
    "close_up", "extreme_close", "insert", "over_shoulder", "aerial", "other",
]


def build_shot_system_prompt(pack: GenrePack) -> str:
    """Render the shot-classification system prompt for the given pack."""
    template = pack.prompts["shot_classify_system"]
    return template.format(
        shot_labels=", ".join(pack.shot_labels),
        insert_definition=pack.insert_definition,
    )


class ShotSizeError(RuntimeError):
    pass


def _encode_image(path: Path) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(path.read_bytes()).decode("ascii"),
        },
    }


def classify_shots(
    thumbnail_paths: list[Path],
    pack: GenrePack,
    model: str = "claude-sonnet-4-20250514",
    batch_size: int = 16,
) -> list[str]:
    """Returns one label per thumbnail, in input order. Missing files → 'other'."""
    if not thumbnail_paths:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ShotSizeError("ANTHROPIC_API_KEY not set")
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise ShotSizeError("anthropic SDK not installed") from e

    client = Anthropic(api_key=api_key)
    system_prompt = build_shot_system_prompt(pack)
    valid_labels = set(pack.shot_labels)
    out: list[str] = []

    for start in range(0, len(thumbnail_paths), batch_size):
        batch = thumbnail_paths[start:start + batch_size]
        content: list[dict] = []
        for i, p in enumerate(batch, 1):
            content.append({"type": "text", "text": f"Image {i}:"})
            if p and p.exists():
                content.append(_encode_image(p))
            else:
                content.append({"type": "text", "text": "[missing]"})

        try:
            msg = client.messages.create(
                model=model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": content}],
            )
        except Exception as e:
            raise ShotSizeError(f"Anthropic API call failed: {e}") from e

        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        try:
            payload = json.loads(text[text.find("{"):text.rfind("}") + 1])
            labels = payload.get("labels") or []
        except (json.JSONDecodeError, ValueError):
            labels = []

        while len(labels) < len(batch):
            labels.append("other")
        labels = labels[: len(batch)]
        out.extend(l if l in valid_labels else "other" for l in labels)

    return out


def summarize_shot_mix(clips: list) -> dict:
    """Aggregate shot-size distribution + per-chapter mix."""
    counts: dict[str, int] = {}
    n_labeled = 0
    for c in clips:
        if not c.shot_size:
            continue
        n_labeled += 1
        counts[c.shot_size] = counts.get(c.shot_size, 0) + 1
    if not n_labeled:
        return {"labeled_clips": 0, "distribution": {}, "dominant": None}
    pct = {k: round(100 * v / n_labeled, 1) for k, v in counts.items()}
    dominant = max(pct.items(), key=lambda kv: kv[1])[0]
    return {
        "labeled_clips": n_labeled,
        "total_clips": len(clips),
        "distribution": pct,
        "dominant": dominant,
    }
