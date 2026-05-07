"""Claude Code CLI text-completion backend.

Lets the analyzer route text-only LLM calls (guide writer, future
NotebookLM intro generation) through the local `claude` binary instead
of the Anthropic Python SDK. Calls bill against the user's Claude
Pro/Max subscription quota — no ANTHROPIC_API_KEY required.

The local CLI is text-only — image inputs (vision passes) are not
supported here. For those, use the API backend or drive labeling from
Claude Desktop via the MCP server.
"""

from __future__ import annotations

import json
import shutil
import subprocess


class ClaudeCLIError(RuntimeError):
    pass


def is_available() -> bool:
    """True iff the `claude` binary is on PATH."""
    return shutil.which("claude") is not None


def complete(
    prompt: str,
    *,
    system: str | None = None,
    max_turns: int = 1,
    output_format: str = "json",
    timeout_sec: int = 600,
) -> str:
    """Run a one-shot text completion via `claude -p`.

    Concatenates system + user prompt (the CLI's `-p` mode doesn't expose a
    separate system slot), runs the binary, and returns the model's text
    response. For `output_format="json"` the CLI returns a JSON envelope —
    we extract the `result` field, which is the model's text.

    Args:
      prompt: User-side prompt body.
      system: Optional system-style guidance prepended to the prompt.
      max_turns: Cap on assistant turns (defaults to 1 — single-shot).
      output_format: "text" or "json". JSON parses cleanly; text is raw.
      timeout_sec: Subprocess timeout.

    Raises:
      ClaudeCLIError if the binary is missing, exits non-zero, or returns
      malformed JSON.
    """
    if not is_available():
        raise ClaudeCLIError(
            "`claude` CLI not found on PATH. Install Claude Code and run "
            "`claude auth login`, or set claude_backend=\"api\" in config."
        )

    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    cmd = [
        "claude", "-p",
        "--output-format", output_format,
        "--max-turns", str(max_turns),
    ]

    try:
        proc = subprocess.run(
            cmd,
            input=full_prompt,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeCLIError(f"`claude -p` timed out after {timeout_sec}s") from e
    except FileNotFoundError as e:
        raise ClaudeCLIError("`claude` CLI not found on PATH") from e

    if proc.returncode != 0:
        raise ClaudeCLIError(
            f"`claude -p` exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '').strip()[:500]}"
        )

    out = proc.stdout.strip()
    if output_format == "text":
        return out
    try:
        envelope = json.loads(out)
    except json.JSONDecodeError as e:
        raise ClaudeCLIError(
            f"`claude -p --output-format json` returned non-JSON: {out[:300]}"
        ) from e

    # The CLI's JSON envelope wraps the model's text in "result". Older
    # versions used "messages" or "content"; fall back gracefully.
    if isinstance(envelope, dict):
        for key in ("result", "response", "content"):
            val = envelope.get(key)
            if isinstance(val, str):
                return val
        # Some versions return {"messages":[{"content":[{"text":"..."}]}]}.
        msgs = envelope.get("messages")
        if isinstance(msgs, list):
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                content = m.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            return block.get("text", "")
    raise ClaudeCLIError(
        f"could not extract result from `claude -p` JSON envelope: {out[:300]}"
    )
