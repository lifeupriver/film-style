"""Genre structure templates for rough-cut assembly.

Each template is an ordered list of segment names with duration budgets
(expressed as fractions of total runtime). Used by the assembler and
Claude edit planner to allocate time across narrative sections.
"""

from __future__ import annotations

STRUCTURE_TEMPLATES: dict[str, list[dict[str, float | str]]] = {
    "wedding-classic": [
        {"name": "getting_ready", "pct": 0.08},
        {"name": "details", "pct": 0.04},
        {"name": "first_look", "pct": 0.10},
        {"name": "portraits", "pct": 0.06},
        {"name": "ceremony", "pct": 0.22},
        {"name": "cocktail_hour", "pct": 0.04},
        {"name": "reception_entrance", "pct": 0.04},
        {"name": "speeches", "pct": 0.08},
        {"name": "first_dance", "pct": 0.06},
        {"name": "dancing", "pct": 0.18},
        {"name": "send_off", "pct": 0.06},
        {"name": "establishing", "pct": 0.04},
    ],
    "wedding-short": [
        {"name": "getting_ready", "pct": 0.06},
        {"name": "ceremony", "pct": 0.28},
        {"name": "portraits", "pct": 0.08},
        {"name": "reception_entrance", "pct": 0.05},
        {"name": "speeches", "pct": 0.08},
        {"name": "dancing", "pct": 0.35},
        {"name": "send_off", "pct": 0.10},
    ],
    "commercial-30": [
        {"name": "hook", "pct": 0.15},
        {"name": "product_reveal", "pct": 0.25},
        {"name": "demo", "pct": 0.35},
        {"name": "cta", "pct": 0.25},
    ],
    "commercial-60": [
        {"name": "hook", "pct": 0.12},
        {"name": "product_reveal", "pct": 0.20},
        {"name": "demo", "pct": 0.40},
        {"name": "kicker", "pct": 0.13},
        {"name": "cta", "pct": 0.15},
    ],
    "montage": [
        {"name": "montage", "pct": 1.0},
    ],
}


def list_templates() -> list[str]:
    return sorted(STRUCTURE_TEMPLATES.keys())


def get_template(name: str) -> list[dict[str, float | str]]:
    key = name.strip().lower()
    if key not in STRUCTURE_TEMPLATES:
        known = ", ".join(list_templates())
        raise KeyError(f"unknown structure template {name!r}; known: {known}")
    return STRUCTURE_TEMPLATES[key]


def segment_budgets(name: str, total_sec: float) -> list[dict[str, float | str]]:
    """Return segments with target_duration_sec filled in."""
    rows = get_template(name)
    out: list[dict[str, float | str]] = []
    for row in rows:
        pct = float(row["pct"])
        out.append(
            {
                "name": row["name"],
                "pct": pct,
                "target_duration_sec": round(total_sec * pct, 2),
            }
        )
    return out
