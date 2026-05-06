"""Per-clip shot-size classification via Claude vision.

Sends batched per-clip middle-frame thumbnails to Claude and gets back a label
per image. Tighter label set than chapter classification — these answer
'what kind of shot is this?' (composition), not 'what part of the wedding'.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

SHOT_LABELS = [
    "extreme_wide",     # establishing, landscape, environment
    "wide",             # full body, full venue
    "medium_wide",      # waist-up, two-shot
    "medium",           # mid-thigh up
    "medium_close",     # chest up
    "close_up",         # head + shoulders
    "extreme_close",    # eyes, hands, ring detail
    "insert",           # detail of an object: rings, glassware, paper
    "over_shoulder",    # OTS framing
    "aerial",           # drone / overhead
    "other",
]

SYSTEM = (
    "You are labeling shots from a wedding film by composition. Each image is "
    "the middle frame of one shot. For each image, output exactly one of:\n"
    + ", ".join(SHOT_LABELS)
    + ".\n\n"
    "Definitions:\n"
    "- extreme_wide: landscape / venue exterior with subjects tiny or absent.\n"
    "- wide: full body of subject(s), context dominates.\n"
    "- medium_wide: waist-up framing, two-shot, conversational distance.\n"
    "- medium: mid-thigh up.\n"
    "- medium_close: chest up.\n"
    "- close_up: head and shoulders.\n"
    "- extreme_close: face only / eyes / hands / ring.\n"
    "- insert: a detail of an object, no subject in frame (rings on a book, place card).\n"
    "- over_shoulder: shot framed past the back of someone's head/shoulder.\n"
    "- aerial: from above (drone, overhead).\n"
    "- other: cannot tell.\n\n"
    'Return JSON: {"labels": ["label1", "label2", ...]} in image order.'
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
                system=SYSTEM,
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

        # Pad / truncate to match batch.
        while len(labels) < len(batch):
            labels.append("other")
        labels = labels[: len(batch)]
        out.extend(l if l in SHOT_LABELS else "other" for l in labels)

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
