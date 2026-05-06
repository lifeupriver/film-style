"""Call Claude to turn aggregated stats into a markdown style guide."""

from __future__ import annotations

import json
import os

from .genre_pack import GenrePack


def build_system_prompt(pack: GenrePack) -> str:
    return pack.prompts["guide_writer_system"]


def write_guide(stats: dict, pack: GenrePack, model: str = "claude-sonnet-4-20250514") -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Run: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    n = stats.get("film_count", 0)
    user = (
        f"Here is the aggregated analysis of {n} {pack.display_name}s:\n\n"
        f"{json.dumps(stats, indent=2)}\n\n"
        f"Write the complete editing style guide."
    )

    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=build_system_prompt(pack),
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in msg.content if hasattr(block, "text"))
