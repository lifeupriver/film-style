"""Load an edited timeline (FCPXML or OpenTimelineIO) for comparison.

Both loaders return the same dict shape as ``fcpxml_parser.parse`` plus a
``visible_clips`` list: the shots a viewer actually sees, in order, after
higher video lanes (b-roll, cutaways) are laid over the primary storyline.
That list is what per-shot pacing checks run against, because a cut to
b-roll is a cut to the viewer even when the A-roll underneath keeps going.
"""

from __future__ import annotations

import json
from pathlib import Path

# Slivers shorter than this (about one frame) are dropped when flattening.
_MIN_VISIBLE_SEC = 0.02

TIMELINE_SUFFIXES = {".fcpxml", ".xml", ".otio"}


def flatten_visible(intervals: list[dict]) -> list[dict]:
    """Collapse overlapping video intervals into the sequence a viewer sees.

    Each interval is ``{"start": s, "end": e, "layer": n, "name": str}``; at
    any moment the interval on the highest layer wins (later intervals win
    ties). Returns ``[{index, name, start_sec, end_sec, duration_sec, layer}]``.
    """
    ivs = [iv for iv in intervals if iv["end"] - iv["start"] > 1e-6]
    if not ivs:
        return []
    points = sorted({p for iv in ivs for p in (iv["start"], iv["end"])})

    spans: list[tuple[float, float, int]] = []
    for a, b in zip(points, points[1:]):
        mid = (a + b) / 2
        top = None
        for i, iv in enumerate(ivs):
            if iv["start"] <= mid < iv["end"]:
                if top is None or iv["layer"] >= ivs[top]["layer"]:
                    top = i
        if top is not None:
            if spans and spans[-1][2] == top and abs(spans[-1][1] - a) < 1e-6:
                spans[-1] = (spans[-1][0], b, top)
            else:
                spans.append((a, b, top))

    out: list[dict] = []
    for a, b, i in spans:
        if b - a < _MIN_VISIBLE_SEC:
            continue
        out.append({
            "index": len(out),
            "name": ivs[i].get("name") or "",
            "start_sec": round(a, 3),
            "end_sec": round(b, 3),
            "duration_sec": round(b - a, 3),
            "layer": ivs[i]["layer"],
        })
    return out


def load_timeline(path: Path) -> dict:
    """Parse an FCPXML or OTIO file, chosen by extension."""
    suffix = path.suffix.lower()
    if suffix == ".otio":
        from .otio_parser import parse as parse_otio
        return parse_otio(json.loads(path.read_text()))
    if suffix in (".fcpxml", ".xml"):
        from .fcpxml_parser import parse as parse_fcpxml
        return parse_fcpxml(path)
    raise ValueError(
        f"unsupported timeline format {suffix!r}; expected .fcpxml or .otio"
    )


def load_timeline_content(content: str | bytes) -> dict:
    """Parse timeline text, detecting OTIO (JSON) versus FCPXML (XML)."""
    import tempfile

    text = content.decode("utf-8") if isinstance(content, bytes) else content
    if text.lstrip().startswith("{"):
        from .otio_parser import parse as parse_otio
        return parse_otio(json.loads(text))

    from .fcpxml_parser import parse as parse_fcpxml
    with tempfile.NamedTemporaryFile(suffix=".fcpxml", delete=False, mode="w") as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    try:
        return parse_fcpxml(tmp_path)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass
