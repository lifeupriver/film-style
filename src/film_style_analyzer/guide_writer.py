"""Call Claude to turn aggregated stats into a markdown style guide."""

from __future__ import annotations

import json
import os

SYSTEM_PROMPT = """You are helping a wedding filmmaker document their editing style.
You will receive detailed statistical analysis of their finished wedding films.
Write a comprehensive editing style guide in markdown that a junior editor (or an
AI rough cut assembler) could follow to produce edits that match this filmmaker's
style.

Be extremely specific. Use exact numbers from the data. Do not generalize when
you can be precise. Write rules, not descriptions. For example: "Ceremony clips:
4.8 seconds average, never exceed 7 seconds" is better than "ceremony clips tend
to be a bit longer."

The guide should be structured as actionable rules for assembling a rough cut,
not as a description of the filmmaker's work.

If the data includes a `scene_breakdown` array (per-scene-type statistics from
vision classification), produce a per-scene rules table. If it includes
`audio` and `transcript`, produce explicit audio-design rules. If it includes
`gemini_analyses`, treat them as qualitative observations and weave specific
distinctive choices into the guide.

Do not use the words: stunning, magical, seamless, breathtaking, cinematic,
captivating, mesmerizing, or any similar filler."""


def write_guide(stats: dict, model: str = "claude-sonnet-4-20250514") -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Run: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    user = f"Here is the aggregated analysis of {stats.get('film_count', 0)} wedding films:\n\n{json.dumps(stats, indent=2)}\n\nWrite the complete editing style guide."

    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in msg.content if hasattr(block, "text"))
