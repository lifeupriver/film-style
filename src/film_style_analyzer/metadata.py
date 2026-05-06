"""Per-wedding metadata. Free-form key/value, but with a curated key set the
dashboard surfaces as dropdowns.

The interesting metadata isn't free text — it's the dimensions an editor
actually cuts differently along: venue type, season, ceremony length, music
genre. Profiles can be segmented by these axes downstream.
"""

from __future__ import annotations

CURATED_KEYS = {
    "venue":         ["indoor", "outdoor", "destination", "church", "barn",
                      "estate", "beach", "garden", "ballroom"],
    "season":        ["spring", "summer", "autumn", "winter"],
    "time_of_day":   ["morning", "afternoon", "golden_hour", "evening", "night"],
    "ceremony":      ["religious", "civil", "spiritual", "elopement", "vow_renewal"],
    "guest_count":   ["intimate", "small", "medium", "large", "huge"],
    "music_genre":   ["acoustic", "indie", "folk", "pop", "classical",
                      "instrumental", "jazz", "electronic", "soul"],
    "weather":       ["sunny", "overcast", "rainy", "snowy", "stormy"],
    "duration_target": ["short", "standard", "long"],
}


def parse_set_arg(arg: str) -> tuple[str, str]:
    """Parse `key=value` into a tuple. Strips whitespace, lowercases the key."""
    if "=" not in arg:
        raise ValueError(f"expected key=value, got: {arg!r}")
    k, v = arg.split("=", 1)
    return k.strip().lower(), v.strip()


def merge(existing: dict, updates: dict) -> dict:
    """Merge updates into existing. None values delete the key."""
    out = dict(existing or {})
    for k, v in updates.items():
        if v in (None, ""):
            out.pop(k, None)
        else:
            out[k] = v
    return out


def group_by(films: list, key: str) -> dict[str, list]:
    """Group analyses by a metadata key. Films missing the key bucket as '_unset'."""
    buckets: dict[str, list] = {}
    for f in films:
        v = (f.metadata or {}).get(key) or "_unset"
        buckets.setdefault(v, []).append(f)
    return buckets
