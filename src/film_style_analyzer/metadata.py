"""Per-film metadata. Free-form key/value, with a curated set the dashboard
surfaces as dropdowns. The curated keys come from the active genre pack —
weddings cut differently along venue/season/ceremony, commercials along
client/product_category/placement, and so on.
"""

from __future__ import annotations

from .genre_pack import GenrePack


def curated_keys(pack: GenrePack) -> dict[str, list[str]]:
    """The metadata keys/values surfaced as dropdowns for this genre."""
    return pack.metadata_keys


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
