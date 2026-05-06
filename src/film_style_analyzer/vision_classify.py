"""Classify chapter scene types via Claude vision.

Sends one representative thumbnail per chapter and asks Claude to label each
chapter according to the active genre pack's scene-label vocabulary.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from .genre_pack import GenrePack


def build_chapter_system_prompt(pack: GenrePack) -> str:
    """Render the chapter-classification system prompt for the given pack."""
    template = pack.prompts["chapter_classify_system"]
    return template.format(scene_labels=", ".join(pack.scene_labels))


class VisionError(RuntimeError):
    pass


def _encode(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": data},
    }


def classify_chapters(
    thumbnail_paths: list[Path],
    pack: GenrePack,
    model: str = "claude-sonnet-4-20250514",
    examples: list[tuple[Path, str]] | None = None,
    max_examples: int = 6,
) -> list[str]:
    """Classify chapters. If `examples` is provided, the most diverse subset
    is sent as few-shot reference images in a prior assistant turn so Claude
    learns the editor's preferred label conventions."""
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

    # Build the few-shot prelude messages, if examples were provided.
    example_msgs: list[dict] = []
    if examples:
        chosen = _pick_diverse_examples(examples, max_examples)
        if chosen:
            example_user_content: list[dict] = [{
                "type": "text",
                "text": (
                    "Reference labels from this editor's prior work — match this "
                    "labeling convention when in doubt. For each image below, the "
                    "expected label is shown."
                ),
            }]
            for path, label in chosen:
                if not path or not path.exists():
                    continue
                example_user_content.append({
                    "type": "text",
                    "text": f"Reference: {label}",
                })
                example_user_content.append(_encode(path))
            if len(example_user_content) > 1:
                example_msgs = [
                    {"role": "user", "content": example_user_content},
                    {"role": "assistant",
                     "content": "Understood. I will follow these conventions."},
                ]

    BATCH = 20
    labels: list[str] = []
    for start in range(0, len(thumbnail_paths), BATCH):
        batch = thumbnail_paths[start:start + BATCH]
        content = []
        for i, p in enumerate(batch, 1):
            if not p.exists():
                content.append({"type": "text", "text": f"Image {i}: [missing]"})
                continue
            content.append({"type": "text", "text": f"Image {i}:"})
            content.append(_encode(p))

        try:
            msg = client.messages.create(
                model=model,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    *example_msgs,
                    {"role": "user", "content": content},
                ],
            )
        except Exception as e:
            raise VisionError(f"Anthropic API call failed: {e}") from e
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        try:
            payload = json.loads(text[text.find("{"):text.rfind("}") + 1])
            batch_labels = payload.get("labels", [])
        except (json.JSONDecodeError, ValueError):
            batch_labels = []
        while len(batch_labels) < len(batch):
            batch_labels.append("other")
        labels.extend(batch_labels[:len(batch)])

    return [l if l in valid_labels else "other" for l in labels]


def _pick_diverse_examples(
    examples: list[tuple[Path, str]], max_examples: int
) -> list[tuple[Path, str]]:
    """Pick at most `max_examples` examples spread across distinct labels."""
    by_label: dict[str, list[tuple[Path, str]]] = {}
    for path, label in examples:
        by_label.setdefault(label, []).append((path, label))

    chosen: list[tuple[Path, str]] = []
    label_iters = {k: iter(v) for k, v in by_label.items()}
    while len(chosen) < max_examples and label_iters:
        for label in list(label_iters):
            try:
                chosen.append(next(label_iters[label]))
                if len(chosen) >= max_examples:
                    break
            except StopIteration:
                del label_iters[label]
    return chosen


def gather_existing_examples(analyses_dir: Path, data_root: Path) -> list[tuple[Path, str]]:
    """Walk all analysis JSONs and collect (thumbnail_path, label) pairs from
    chapters that already have human-corrected (or vision-applied) labels."""
    out: list[tuple[Path, str]] = []
    if not analyses_dir.exists():
        return out
    import json as _json
    for jp in sorted(analyses_dir.glob("*.json")):
        try:
            data = _json.loads(jp.read_text())
        except Exception:
            continue
        for ch in data.get("chapters") or []:
            label = ch.get("label")
            thumb = ch.get("representative_thumbnail")
            if label and thumb:
                out.append((data_root / thumb, label))
    return out
