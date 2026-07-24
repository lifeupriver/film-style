"""Call Claude to turn aggregated stats into a markdown style guide.

Two backends:
  - "api" — Anthropic Python SDK (needs ANTHROPIC_API_KEY)
  - "cli" — local `claude` Code CLI (uses your Claude Pro/Max subscription)
"""

from __future__ import annotations

import json
import os

from .genre_pack import GenrePack


def build_system_prompt(pack: GenrePack) -> str:
    return pack.prompts["guide_writer_system"]


def write_guide(
    stats: dict,
    pack: GenrePack,
    model: str = "claude-sonnet-4-20250514",
    backend: str = "api",
) -> str:
    n = stats.get("film_count", 0)
    user = (
        f"Here is the aggregated analysis of {n} {pack.display_name}s:\n\n"
        f"{json.dumps(stats, indent=2)}\n\n"
        f"Write the complete editing style guide."
    )
    system = build_system_prompt(pack)

    if backend == "cli":
        from .claude_cli import complete as claude_cli_complete

        return claude_cli_complete(prompt=user, system=system, max_turns=1)

    # Default: API backend.
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Either export it, or set "
            'claude_backend="cli" in ~/.film-style-analyzer/config.json '
            "to route through your Claude Pro/Max subscription via the local "
            "`claude` CLI."
        )

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in msg.content if hasattr(block, "text"))
