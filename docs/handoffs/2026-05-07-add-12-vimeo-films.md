# Handoff: add 12 wedding films from Vimeo to the archive

> **Paste this whole document into a fresh Claude Code session** (or open
> the project and reference this file). It's self-contained — assume the new
> session has zero prior context about this work.

## Goal

Add 12 finished wedding films to the existing labeled-and-described
`wedding` archive at `~/.film-style-analyzer/wedding/`, then regenerate
`style-profile.json` + `style-guide.md` and refresh the dashboard.

The films, by Vimeo title (some IDs known, some need lookup):

| Film | Known Vimeo ID |
|---|---|
| Juliette and Andrew | (look up) |
| Marlene and David | (look up) |
| Jess and John | (look up) |
| Amelia and Omar | (look up) |
| Sarah and Mike | (look up) |
| Isabelle and Michael | (look up) |
| Danielle and Anthony | 1034043523 |
| Ashley and Luke | (look up) |
| Becca and Jason | 906099992 *(also exists as "Rebecca and Jason" 898627262)* |
| Sarah and Dave | 1089125688 |
| Carrie and Rose | 1099451979 *(or 1096571101 — pick the newer "final")* |
| Lizzie and Justin | 971075026 *(or 910150367 — pick the newer)* |

The user owns these films (Joshua Brown Photography, Vimeo Pro). All
films are direct-downloadable via the API.

## State of the world (as of 2026-05-07)

**Project:** `/Users/joshua/Documents/GitHub/film-style` — clean tree on
`main`. Multi-genre `film-style-analyzer` CLI.

**Active workspace:** `~/.film-style-analyzer/wedding/`. Per-genre layout
(`config.default_genre = "wedding"`).

**LLM backend:** `claude_backend = "cli"` is set in
`~/.film-style-analyzer/config.json`. The guide writer shells out to the
local `claude` Code CLI — calls bill against the user's Pro/Max
subscription, NOT an Anthropic API key. The user does not want API
tokens consumed.

**Already in the archive (full pipeline complete):**
- Amanda_and_Kenton — 154 clips, 54 chapters, all labeled + described
- Autumn_and_Ketan — 149 clips, 34 chapters, all labeled + described
- Maddie_Max_final — 157 clips, 41 chapters, all labeled + described
- Olivia_and_Marc — 163 clips, 36 chapters, all labeled + described
- Rachel_and_Jack — 136 clips, 35 chapters, all labeled + described

**Removed in the previous session:** Marisa and Zach (deleted analysis
JSON + thumbnails per user request).

**Not labeled / probably should be removed before the next guide pass:**
- audreysdinner.json (rehearsal-dinner short, 56s, 5 chapters, no labels)
- Dinner-Apple Devices HD (Best Quality).json (36s, 3 chapters, no labels)

These two were desktop test clips. Recommend deleting them before
regenerating the profile so they don't pollute pacing/transition stats.
**Confirm with the user before deleting** — the user explicitly removed
Marisa but said nothing about these.

## Setup the new session needs

### 1. Vimeo access token (env var, do NOT commit)

```bash
export VIMEO_ACCESS_TOKEN=ffd420163a0e3b022b7caa7ba96c2f83
```

That's the token from the previous session — Joshua Brown Photography,
Vimeo Pro account. If it's been rotated, the user will paste a new one.
Verify with:

```bash
curl -s -H "Authorization: bearer $VIMEO_ACCESS_TOKEN" \
  "https://api.vimeo.com/me?fields=name,account"
```

Expect `{"name": "Joshua Brown Photography", "account": "pro"}`.

### 2. Tools that must be installed

- `ffmpeg` (already installed via Homebrew)
- The project's venv at `/Users/joshua/Documents/GitHub/film-style/.venv`
  with `film-style` on its bin path. Test: `.venv/bin/film-style genre current`
- `claude` CLI on PATH (already there at `~/.nvm/.../bin/claude`)

### 3. Dashboard server

The user keeps a dashboard server running at `http://localhost:8765/`.
If `curl http://localhost:8765/` returns non-200, restart with:

```bash
pkill -f "film-style serve"; sleep 1
nohup .venv/bin/film-style serve --port 8765 > /tmp/dashboard.log 2>&1 &
```

## Pipeline (do this for each film)

### Step 1 — find Vimeo IDs by name

Some IDs are listed above. For the rest, query the user's video list and
grep by name:

```bash
mkdir -p ~/film-style-demo/vimeo-meta
curl -s -H "Authorization: bearer $VIMEO_ACCESS_TOKEN" \
  "https://api.vimeo.com/me/videos?fields=name,uri,duration,download&per_page=100&page=1&sort=date&direction=desc" \
  -o ~/film-style-demo/vimeo-meta/page1.json
# Repeat for page=2, page=3, page=4 — 375 total videos.
```

Then in Python:

```python
import json, re
from pathlib import Path
targets = [
    "Juliette and Andrew", "Marlene and David", "Jess and John",
    "Amelia and Omar", "Sarah and Mike", "Isabelle and Michael",
    "Ashley and Luke",
]
hits = {}
for p in sorted(Path("~/film-style-demo/vimeo-meta").expanduser().glob("page*.json")):
    for v in json.loads(p.read_text()).get("data", []):
        for t in targets:
            if t.lower() in v["name"].lower():
                vid = v["uri"].split("/")[-1]
                hits.setdefault(t, []).append((vid, v["name"], v["duration"]))
for t, lst in hits.items():
    print(t, lst)
```

If multiple matches per target, prefer the one ending in "final" or the
3-7 minute duration (typical full wedding film). Skip ceremony-only or
speeches-only cuts unless the user confirms.

### Step 2 — download at 720p

```bash
mkdir -p ~/film-style-demo/downloads
# For each (id, slugified_name) pair:
curl -s -H "Authorization: bearer $VIMEO_ACCESS_TOKEN" \
  "https://api.vimeo.com/videos/$ID?fields=name,download" \
  -o /tmp/vimeo_$ID.json
# Then extract the 720p rendition URL from .download[] where rendition == "720p"
# and curl -L -o ~/film-style-demo/downloads/<slug>.mp4 <url>
```

Slugify the filename — letters, digits, underscore, dot, hyphen. The
dashboard's `_slug_safe` validator allows spaces and apostrophes now, but
underscored filenames are still cleaner.

### Step 3 — analyze

```bash
cd /Users/joshua/Documents/GitHub/film-style
.venv/bin/film-style analyze ~/film-style-demo/downloads --skip-audio --skip-color
```

`--skip-audio --skip-color` runs the fast pipeline — scene detect,
dissolve classification, chapter grouping, thumbnail extraction. Each
6-min film is ~30-50s. Audio + color can be added later by re-running
without the skip flags.

### Step 4 — chapter labels + film metadata (parallel subagents)

For each new film, dispatch one general-purpose subagent. The reusable
prompt is in `docs/handoffs/prompts/chapter-labeler.md` (or copy from
this file's appendix below). Each subagent reads every chapter's
`representative_thumbnail`, picks a wedding scene_label, and writes the
metadata. Wedding pack scene_labels are loaded from
`src/film_style_analyzer/genre_packs/wedding.toml`. Allowed values:

```
getting_ready, details, first_look, portraits, ceremony,
ceremony_processional, ceremony_vows, ceremony_recessional,
cocktail_hour, reception_entrance, first_dance,
speeches, toasts, cake_cutting, dancing, send_off,
establishing, transition, other
```

Metadata vocab (all optional, skip when uncertain):

```
venue:        indoor | outdoor | destination | church | barn | estate |
              beach | garden | ballroom
season:       spring | summer | autumn | winter
time_of_day:  morning | afternoon | golden_hour | evening | night
ceremony:     religious | civil | spiritual | elopement | vow_renewal
weather:      sunny | overcast | rainy | snowy | stormy
```

### Step 5 — per-clip shot descriptions (parallel subagents)

Same parallel-subagent pattern. Each subagent reads every clip's
`thumbnail` and writes a structured `ShotDescription` to
`cuts.clips[i].shot_description`. Reusable prompt in this file's
appendix. Vocabularies (defined in `schemas.py`):

```python
subjects: bride, groom, couple, wedding_party, officiant, parents,
          family, kids, guests, details_only
setting:  altar, aisle, lawn, garden, dance_floor, tent, ballroom,
          ceremony_seating, getting_ready_room, reception_table,
          hallway, exterior_landscape, interior_other, vehicle
lighting: golden_hour, natural_daylight, overcast, candle, warm_indoor,
          mixed_indoor, dim_indoor, uplighting_warm, uplighting_cool,
          dance_floor, night_exterior
camera:   locked, slight_handheld, handheld, push_in, pull_back, pan,
          tilt, gimbal_walk, drone, rack_focus, slow_motion
mood:     tender, joyful, ceremonial, intimate, candid, kinetic,
          still, anticipatory, celebratory
action:   short imperative, ≤6 words
description: one short free-form sentence ≤20 words
```

### Step 6 — regenerate profile + guide

```bash
.venv/bin/film-style guide
```

This rewrites `~/.film-style-analyzer/wedding/style-profile.json` (local,
no LLM) and then calls the local `claude` CLI to write
`style-guide.md` (text-only, billed against subscription).

Known wart: the CLI sometimes prepends a one-line conversational preface
to the guide markdown like "I'll write the guide directly as the
response — it's the deliverable." Strip with sed if needed:

```bash
sed -i '' '/^I.ll write the guide/,/^---$/d' ~/.film-style-analyzer/wedding/style-guide.md
```

### Step 7 — verify dashboard

```bash
curl -s "http://localhost:8765/api/films/<stem>" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); cs=d['cuts']['clips']; \
   print(f'{sum(1 for c in cs if c.get(\"shot_description\"))}/{len(cs)} described')"
```

Open `http://localhost:8765/` in browser and click into each new film.
Filmstrip cells should show mood corner-tags; clicking opens the detail
panel with subjects/setting/lighting/camera/mood pills + free-form
description.

## Cost / time expectations

Based on the prior 6-film pass (~3 hours wall-clock total in this
session, all subscription-billed):

- 5 parallel describe-clips agents on ~150-clip films took ~15 min each
  wall-clock (parallelism makes it almost the slowest single one)
- Each describe-clips agent burns ~250K tokens of mostly-vision input
- Each chapter-labeler agent burns ~100K tokens
- For 12 films: budget ~3M tokens of vision input across ~24 subagent
  invocations. Heavy but well within Claude Max quota.

If the user wants to slow this down to control burn:
- Do films one at a time
- Or skip per-clip descriptions and only do chapter labels
- Or just do shot_size labels (~$0 quota — also vision but tighter prompt)

## Authorization

The user has explicitly authorized:
- Downloading these 12 films from their own Vimeo account
- Running parallel subagents for labeling/describing
- Burning subscription quota for the full describe-clips pass
- Regenerating profile + guide via `claude -p`

What still needs explicit permission:
- Deleting `audreysdinner.json` and `Dinner-Apple…json` (mention in
  first response, get a "yes" before removing)
- Anything outside `~/.film-style-analyzer/`, `~/film-style-demo/`,
  or the project repo

## Appendix A — chapter labeler prompt template

Copy this verbatim per film, swap STEM and CHAPTER_COUNT:

````
You are labeling chapters of a finished wedding film by looking at
representative thumbnails. Goal: write semantically correct scene labels
into the analysis JSON so the dashboard's per-scene rules table is meaningful.

**Target file:** `/Users/joshua/.film-style-analyzer/wedding/analyses/<STEM>.json`
**Thumbnail base:** `/Users/joshua/.film-style-analyzer/wedding/`
**Total chapters:** <CHAPTER_COUNT>

**For each entry in `chapters[*]`:**
1. Read the thumbnail at `<base>/<representative_thumbnail>` using the Read tool.
2. Pick exactly ONE label from this fixed vocabulary (do not invent labels):
   getting_ready, details, first_look, portraits, ceremony,
   ceremony_processional, ceremony_vows, ceremony_recessional,
   cocktail_hour, reception_entrance, first_dance, speeches, toasts,
   cake_cutting, dancing, send_off, establishing, transition, other

[Definitions block — see chapter-label prompts in prior session]

**After labeling:** edit the JSON file in place via Python+Bash, preserve
indent=2, only update chapters[i].label. Don't touch any other fields.

**Also infer film-level metadata** (venue/season/time_of_day/ceremony/
weather), only using values from the wedding pack vocabulary. Skip any
key you can't confidently infer.

**Process all <CHAPTER_COUNT> chapters.** Verify every chapter has a
non-null label.

**Report under 200 words:** count labeled, distribution, metadata set.
````

## Appendix B — describe-clips prompt template

````
You are populating per-clip ShotDescription objects for a finished
wedding film. Goal: capture what Claude can SEE in each clip (subjects,
action, setting, lighting, camera, mood, free-form notes) so downstream
tools can pick clips from raw footage that match the editor's choices.

**Target file:** `/Users/joshua/.film-style-analyzer/wedding/analyses/<STEM>.json`
**Thumbnail base:** `/Users/joshua/.film-style-analyzer/wedding/`
**Total clips:** <CLIP_COUNT>

**For EACH clip in `cuts.clips[*]`:**
1. Read its thumbnail at `<base>/<thumbnail>` using the Read tool.
2. Build a ShotDescription dict (skip a field if you can't infer):
   - subjects (list[str]): bride, groom, couple, wedding_party, officiant,
     parents, family, kids, guests, details_only
   - action (str): short imperative phrase, ≤6 words
   - setting (str): altar, aisle, lawn, garden, dance_floor, tent,
     ballroom, ceremony_seating, getting_ready_room, reception_table,
     hallway, exterior_landscape, interior_other, vehicle
   - lighting (str): golden_hour, natural_daylight, overcast, candle,
     warm_indoor, mixed_indoor, dim_indoor, uplighting_warm,
     uplighting_cool, dance_floor, night_exterior
   - camera (str): locked, slight_handheld, handheld, push_in, pull_back,
     pan, tilt, gimbal_walk, drone, rack_focus, slow_motion
   - mood (str): tender, joyful, ceremonial, intimate, candid, kinetic,
     still, anticipatory, celebratory
   - description (str): one short free-form sentence ≤20 words

**Write atomically at end via Python+Bash:**

import json
p = "/Users/joshua/.film-style-analyzer/wedding/analyses/<STEM>.json"
data = json.load(open(p))
descriptions = { ... }  # your mapping clip_index -> ShotDescription dict
for k, sd in descriptions.items():
    data["cuts"]["clips"][int(k)]["shot_description"] = sd
with open(p, "w") as f:
    json.dump(data, f, indent=2)

Don't touch any other fields.

**Process all <CLIP_COUNT> clips.** Verify by reloading.

**Report under 250 words:** count described/total, controlled-vocab
tallies (≥3), 3 example shot_descriptions.
````

## Acceptance criteria

When the new session is done, all 12 of these should be true:

1. `ls ~/.film-style-analyzer/wedding/analyses/` lists the 5 prior films
   PLUS 12 new ones
2. For each of the 12 new films:
   - Every chapter has a non-null `label` from the wedding vocab
   - Every clip has a non-null `shot_description` with at least subjects + setting set
   - Top-level `metadata` has at least 3 keys filled
3. `~/.film-style-analyzer/wedding/style-profile.json` reports
   `film_count: 17` (or 15 if audreysdinner + Dinner-Apple were removed)
4. `~/.film-style-analyzer/wedding/style-guide.md` regenerated and ≥10KB
5. `curl http://localhost:8765/api/films` returns the new films and the
   dashboard renders descriptions when clicked
6. No Anthropic API tokens were consumed (verify by checking that
   `ANTHROPIC_API_KEY` was never set during the session)
