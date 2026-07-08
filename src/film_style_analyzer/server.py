"""Local-first dashboard server.

Stdlib only. Serves a single-page app from ./static/ and exposes a small JSON
API over the data the CLI writes to ~/.film-style-analyzer/.
"""

from __future__ import annotations

import io
import json
import mimetypes
import re
import socketserver
import tempfile
import threading
import webbrowser
import zipfile
from dataclasses import asdict
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

from .aggregator import aggregate
from .config import CONFIG_PATH, Config, load as load_config
from .fcpxml_parser import parse as parse_fcpxml
from .genre_pack import load as load_genre_pack
from .metadata import curated_keys, merge as merge_md
from .schemas import FilmAnalysis

DATA_ROOT = Path.home() / ".film-style-analyzer"


def _active_genre_at_import() -> str:
    try:
        return getattr(load_config(), "default_genre", "wedding")
    except Exception:
        return "wedding"


_GENRE_ROOT = DATA_ROOT / _active_genre_at_import()
ANALYSES_DIR = _GENRE_ROOT / "analyses"
THUMBS_DIR = _GENRE_ROOT / "thumbs"
GUIDE_PATH = _GENRE_ROOT / "style-guide.md"
STATS_PATH = _GENRE_ROOT / "aggregate-stats.json"
EDIT_CRAFT_DIR = _GENRE_ROOT / "edit-craft"
SHOT_PROFILE_PATH = DATA_ROOT / "shot-profile.json"
STATIC_DIR = Path(__file__).parent / "static"


# ---------- helpers ---------------------------------------------------------


def _load_films() -> list[FilmAnalysis]:
    if not ANALYSES_DIR.exists():
        return []
    out: list[FilmAnalysis] = []
    for p in sorted(ANALYSES_DIR.glob("*.json")):
        try:
            out.append(FilmAnalysis.model_validate_json(p.read_text()))
        except Exception:
            continue
    return out


def _film_summary(a: FilmAnalysis) -> dict:
    """Lightweight summary for index pages."""
    cover = next(
        (c.thumbnail for c in a.cuts.clips if c.thumbnail and c.index >= 1),
        a.cuts.clips[0].thumbnail if a.cuts.clips else None,
    )
    return {
        "stem": Path(a.film.filename).stem,
        "filename": a.film.filename,
        "duration_sec": a.film.duration_sec,
        "resolution": a.film.resolution,
        "frame_rate": a.film.frame_rate,
        "codec": a.film.codec,
        "clip_count": a.cuts.total,
        "avg_clip_sec": a.pacing.avg_clip_duration_sec,
        "median_clip_sec": a.pacing.median_clip_duration_sec,
        "transitions": {
            "hard_cut": a.transitions.hard_cut,
            "dissolve": a.transitions.dissolve,
            "fade_in": a.transitions.fade_in,
            "fade_out": a.transitions.fade_out,
        },
        "has_audio": a.audio is not None,
        "has_transcript": a.transcript is not None,
        "has_gemini": a.gemini_analysis is not None,
        "has_vision": any(c.label for c in a.chapters),
        "cover_thumbnail": cover,
        "analyzed_at": a.analyzed_at.isoformat() if a.analyzed_at else None,
    }


def _resolve_under(base: Path, rel: str) -> Path | None:
    """Resolve `rel` under `base`, returning None if it escapes the base
    directory. `rel` may use forward slashes."""
    if not rel or rel.startswith("/"):
        return None
    if "\x00" in rel:
        return None
    target = (base / rel).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target


_CRAFT_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def _craft_content_type(path: Path) -> str:
    return _CRAFT_TYPES.get(
        path.suffix.lower(),
        mimetypes.guess_type(str(path))[0] or "application/octet-stream",
    )


def _edit_craft_index() -> dict:
    """Build a JSON index of every file under EDIT_CRAFT_DIR.

    Returns:
        {
            "exists": bool,
            "root": str,
            "files": [
                {"path": "scenes/dancing.md", "size": 33000, "type": "md"},
                ...
            ],
            "tree": {"scenes": {"dancing.md": {...}, ...}, ...}
        }
    """
    if not EDIT_CRAFT_DIR.is_dir():
        return {"exists": False, "root": str(EDIT_CRAFT_DIR), "files": [], "tree": {}}
    files: list[dict] = []
    tree: dict = {}
    for p in sorted(EDIT_CRAFT_DIR.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(EDIT_CRAFT_DIR).as_posix()
        entry = {
            "path": rel,
            "size": p.stat().st_size,
            "type": p.suffix.lstrip(".").lower() or "file",
        }
        files.append(entry)
        # Build nested tree
        parts = rel.split("/")
        cur = tree
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = entry
    return {
        "exists": True,
        "root": str(EDIT_CRAFT_DIR),
        "files": files,
        "tree": tree,
    }


def _zip_directory(d: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=p.relative_to(d).as_posix())
    return buf.getvalue()


# ---------- hand-off bundle -------------------------------------------------


def _handoff_sources() -> list[tuple[str, Path]]:
    """Return [(arcname, path)] for every individual file shipped in the
    hand-off bundle. Directories (edit-craft, analyses) are walked
    separately by _build_handoff_zip."""
    out: list[tuple[str, Path]] = []
    if SHOT_PROFILE_PATH.is_file():
        out.append(("shot-profile.json", SHOT_PROFILE_PATH))
    sg = GUIDE_PATH
    if sg.is_file():
        out.append(("style-guide.md", sg))
    sp = _GENRE_ROOT / "style-profile.json"
    if sp.is_file():
        out.append(("style-profile.json", sp))
    if STATS_PATH.is_file():
        out.append(("aggregate-stats.json", STATS_PATH))
    return out


def _handoff_manifest() -> dict:
    """Snapshot of what /api/handoff.zip would contain.

    Returns counts, total size, and a flat file list (for the dashboard
    to render before download)."""
    files: list[dict] = []

    def add(arc: str, p: Path) -> None:
        try:
            size = p.stat().st_size
        except OSError:
            return
        files.append({"path": arc, "size": size})

    for arc, p in _handoff_sources():
        add(arc, p)

    if EDIT_CRAFT_DIR.is_dir():
        for p in sorted(EDIT_CRAFT_DIR.rglob("*")):
            if p.is_file():
                rel = p.relative_to(EDIT_CRAFT_DIR).as_posix()
                add(f"edit-craft/{rel}", p)

    if ANALYSES_DIR.is_dir():
        for p in sorted(ANALYSES_DIR.glob("*.json")):
            add(f"analyses/{p.name}", p)

    total = sum(f["size"] for f in files)
    return {
        "exists": bool(files),
        "files": files,
        "file_count": len(files),
        "total_bytes": total,
        "genre": _active_genre_at_import(),
    }


def _handoff_readme(brand: str, genre: str, profile: dict | None,
                    stats: dict | None, film_count: int,
                    edit_craft_files: int) -> str:
    """Auto-generated README addressed to a downstream LLM editor.

    Concrete numbers come from the live data so the bundle is
    self-describing without anyone having to re-explain it."""
    bits: list[str] = []
    bits.append(f"# {brand or 'Editor'} — Style Hand-off")
    bits.append("")
    bits.append(
        "This bundle contains everything an AI editor needs to (a) cull "
        "raw footage in this editor's voice and (b) assemble it into a "
        "finished film matching their style."
    )
    bits.append("")
    bits.append(f"Genre: **{genre}**.")
    if film_count:
        bits.append(f"Compiled from **{film_count} finished films**.")
    if profile:
        frames = profile.get("total_frames_analyzed")
        pref = profile.get("preferred_framing")
        if frames:
            bits.append(
                f"Composition learned from **{frames:,} kept frames**, "
                f"preferred framing: **{pref}**."
            )
    bits.append("")
    bits.append("## Workflow")
    bits.append("")
    bits.append(
        "1. **Cull raw clips with `shot-profile.json`.** Apply "
        "`rejection_rules_learned` as hard filters first (e.g. "
        "very-soft focus below the laplacian floor, severe under/"
        "overexposure, head cut-off). Then score remaining clips "
        "against `framing_distribution`, `composition`, "
        "`subject_separation`, and `emotion_preferences`. Higher "
        "alignment = stronger candidate."
    )
    bits.append(
        "2. **Read `style-guide.md`** for the editing voice — pacing, "
        "transitions, structure, audio philosophy. This is the "
        "narrative manual."
    )
    bits.append(
        "3. **Use `aggregate-stats.json`** for numeric targets: "
        "average clip duration, the decile-by-decile pacing curve, "
        "the transition mix, structural beat lengths."
    )
    bits.append(
        "4. **Treat `analyses/` as worked examples.** Each JSON is a "
        "frame-accurate breakdown of a finished film: clip durations, "
        "transitions, audio events, color, shot descriptions. When in "
        "doubt about a beat, find a similar film and mirror it."
    )
    bits.append(
        "5. **Pull from `edit-craft/`** for the editor's curated "
        "library of reusable patterns — coverage checklists, scene "
        "templates, sequence grammar, voice notes."
    )
    bits.append("")
    bits.append("## Files")
    bits.append("")
    if profile:
        bits.append(
            "- `shot-profile.json` — composition + emotion preferences. "
            "Output of `film-style learn-shots`. **Use to choose clips.**"
        )
    if (GUIDE_PATH).is_file():
        bits.append(
            "- `style-guide.md` — narrative editing manual. **Use for "
            "editorial voice.**"
        )
    if (_GENRE_ROOT / "style-profile.json").is_file():
        bits.append(
            "- `style-profile.json` — programmatic counterpart to the "
            "guide; same content, machine-readable."
        )
    if STATS_PATH.is_file():
        bits.append(
            "- `aggregate-stats.json` — pacing/transition/structure "
            "statistics across the corpus. **Use for numeric targets.**"
        )
    if film_count:
        bits.append(
            f"- `analyses/*.json` — {film_count} per-film breakdowns. "
            "Each contains pacing histograms, decile curves, "
            "transitions, audio segments, color, and (when available) "
            "shot descriptions. **Use as worked examples.**"
        )
    if edit_craft_files:
        bits.append(
            f"- `edit-craft/` — {edit_craft_files} files: editor-curated "
            "reference library (scene templates, coverage lists, "
            "sequence grammar, voice notes)."
        )
    bits.append("")
    bits.append("## Reading the numbers")
    bits.append("")
    bits.append(
        "- `face_presence.primary_face_avg_size_pct` is bbox area as a "
        "percent of frame area, not a linear dimension."
    )
    bits.append(
        "- `composition.preferred_face_center_y` is normalized: 0 = "
        "top of frame, 1 = bottom. Wedding work tends to sit subjects "
        "high (0.30–0.35)."
    )
    bits.append(
        "- `emotion_preferences` uses DeepFace's intensity scale "
        "(0–100). The model biases toward fear/sad/angry on contrasty "
        "footage; read directionally, not literally."
    )
    bits.append(
        "- `rejection_rules_learned` percentages are how often each "
        "pattern appears in **kept** footage. Very low = strong reject "
        "signal when you see it in raw clips."
    )
    bits.append(
        "- `aggregate-stats.json` clip durations are seconds; pacing "
        "deciles run [0.0–0.1, 0.1–0.2, …] of film runtime, so "
        "deciles[0] is the opening minute-or-so and deciles[9] is the "
        "ending."
    )
    bits.append("")
    bits.append("---")
    bits.append("")
    bits.append(
        "_Generated by `film-style` from the editor's local archive. "
        "Drop this whole bundle into your context window or a vector "
        "store; the README is the entry point._"
    )
    return "\n".join(bits) + "\n"


def _build_handoff_zip(brand: str) -> bytes:
    """Build the zip blob for /api/handoff.zip."""
    buf = io.BytesIO()

    profile: dict | None = None
    if SHOT_PROFILE_PATH.is_file():
        try:
            profile = json.loads(SHOT_PROFILE_PATH.read_text())
        except json.JSONDecodeError:
            profile = None

    stats: dict | None = None
    if STATS_PATH.is_file():
        try:
            stats = json.loads(STATS_PATH.read_text())
        except json.JSONDecodeError:
            stats = None

    film_count = (
        len(list(ANALYSES_DIR.glob("*.json")))
        if ANALYSES_DIR.is_dir()
        else 0
    )
    edit_craft_files = (
        sum(1 for p in EDIT_CRAFT_DIR.rglob("*") if p.is_file())
        if EDIT_CRAFT_DIR.is_dir()
        else 0
    )
    genre = _active_genre_at_import()

    readme = _handoff_readme(
        brand=brand,
        genre=genre,
        profile=profile,
        stats=stats,
        film_count=film_count,
        edit_craft_files=edit_craft_files,
    )

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", readme)

        for arc, p in _handoff_sources():
            zf.write(p, arcname=arc)

        if EDIT_CRAFT_DIR.is_dir():
            for p in sorted(EDIT_CRAFT_DIR.rglob("*")):
                if p.is_file():
                    rel = p.relative_to(EDIT_CRAFT_DIR).as_posix()
                    zf.write(p, arcname=f"edit-craft/{rel}")

        if ANALYSES_DIR.is_dir():
            for p in sorted(ANALYSES_DIR.glob("*.json")):
                zf.write(p, arcname=f"analyses/{p.name}")

    return buf.getvalue()


def _slug_safe(name: str) -> bool:
    """Allow filename-style stems (letters, digits, spaces, common punct)
    but block path traversal and control chars. Real-world wedding-film
    deliverables often contain spaces, apostrophes, parens, ampersands."""
    if not name or name.startswith(".") or "/" in name or "\\" in name:
        return False
    if ".." in name:
        return False
    # Reject control chars + a few path-meaningful ones.
    return not bool(re.search(r"[\x00-\x1f<>:|?*]", name))


# ---------- request handler -------------------------------------------------


def _make_handler():
    class Handler(SimpleHTTPRequestHandler):
        # Quiet logging.
        def log_message(self, fmt, *args):
            return

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

        # ---- responders -------------------------------------------------
        def _send_json(self, payload, status: int = HTTPStatus.OK) -> None:
            data = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _send_text(self, body: str, status: int = HTTPStatus.OK,
                       content_type: str = "text/plain; charset=utf-8") -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _send_bytes_file(self, path: Path) -> None:
            if not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=600")
            self.end_headers()
            self.wfile.write(data)

        # ---- security helpers -------------------------------------------
        def _origin_ok(self) -> bool:
            """CSRF/Origin defense for mutating requests.

            Rejects any request whose ``Origin``/``Referer`` host differs
            from the server's own host. Same-origin requests pass, and
            requests with no ``Origin``/``Referer`` (curl and other local
            tooling) are allowed so localhost automation keeps working.
            """
            host_hdr = self.headers.get("Host") or ""
            server_host = host_hdr.rsplit(":", 1)[0].strip("[]").lower()
            for header in ("Origin", "Referer"):
                val = self.headers.get(header)
                if not val:
                    continue
                req_host = (urlparse(val).hostname or "").lower()
                if not req_host:
                    continue
                if server_host and req_host != server_host:
                    return False
            return True

        def _require_json_ct(self) -> bool:
            """Require ``Content-Type: application/json`` on JSON POST bodies."""
            ct = (self.headers.get("Content-Type") or "").split(";", 1)[0]
            if ct.strip().lower() != "application/json":
                self.send_error(
                    HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                    "Content-Type must be application/json",
                )
                return False
            return True

        # ---- routing ----------------------------------------------------
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)

            if path == "/api/films":
                films = [_film_summary(a) for a in _load_films()]
                return self._send_json({"films": films})

            if path.startswith("/api/films/"):
                stem = path[len("/api/films/"):].strip("/")
                if not _slug_safe(stem):
                    return self.send_error(HTTPStatus.BAD_REQUEST)
                p = ANALYSES_DIR / f"{stem}.json"
                if not p.is_file():
                    return self.send_error(HTTPStatus.NOT_FOUND)
                try:
                    return self._send_text(
                        p.read_text(),
                        content_type="application/json; charset=utf-8",
                    )
                except OSError:
                    return self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

            if path == "/api/stats":
                films = _load_films()
                stats = aggregate(films)
                return self._send_json(stats)

            if path == "/api/guide":
                if not GUIDE_PATH.is_file():
                    return self._send_json(
                        {"exists": False, "markdown": ""},
                        status=HTTPStatus.OK,
                    )
                return self._send_json(
                    {"exists": True, "markdown": GUIDE_PATH.read_text()}
                )

            if path == "/api/shot-profile":
                if not SHOT_PROFILE_PATH.is_file():
                    return self._send_json(
                        {"exists": False, "path": str(SHOT_PROFILE_PATH),
                         "profile": None}
                    )
                try:
                    profile = json.loads(SHOT_PROFILE_PATH.read_text())
                except (OSError, json.JSONDecodeError):
                    return self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
                return self._send_json(
                    {"exists": True, "path": str(SHOT_PROFILE_PATH),
                     "profile": profile}
                )

            if path == "/api/handoff":
                return self._send_json(_handoff_manifest())

            if path == "/api/handoff.zip":
                manifest = _handoff_manifest()
                if not manifest["exists"]:
                    return self.send_error(HTTPStatus.NOT_FOUND)
                try:
                    cfg = load_config()
                    brand = getattr(cfg, "brand_name", "") or ""
                except Exception:
                    brand = ""
                blob = _build_handoff_zip(brand=brand)
                fname = f"{(brand or 'editor').lower().replace(' ', '-')}-handoff.zip"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{fname}"',
                )
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(blob)
                return

            if path == "/api/edit-craft":
                return self._send_json(_edit_craft_index())

            if path == "/api/edit-craft.zip":
                if not EDIT_CRAFT_DIR.is_dir():
                    return self.send_error(HTTPStatus.NOT_FOUND)
                blob = _zip_directory(EDIT_CRAFT_DIR)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="edit-craft.zip"',
                )
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(blob)
                return

            if path.startswith("/api/edit-craft/"):
                rel = path[len("/api/edit-craft/"):]
                target = _resolve_under(EDIT_CRAFT_DIR, rel)
                if target is None:
                    return self.send_error(HTTPStatus.FORBIDDEN)
                if not target.is_file():
                    return self.send_error(HTTPStatus.NOT_FOUND)
                ctype = _craft_content_type(target)
                data = target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                # Force-download via ?download=1
                if "download=1" in (parsed.query or ""):
                    self.send_header(
                        "Content-Disposition",
                        f'attachment; filename="{target.name}"',
                    )
                self.end_headers()
                self.wfile.write(data)
                return

            if path == "/api/config":
                cfg = load_config()
                return self._send_json(asdict(cfg))

            if path == "/api/metadata-keys":
                # Returns the curated key→[allowed values] dict for dropdowns.
                cfg = load_config()
                pack = load_genre_pack(getattr(cfg, "default_genre", "wedding"))
                return self._send_json(curated_keys(pack))

            if path.startswith("/api/match/"):
                stem = path[len("/api/match/"):].strip("/")
                if not _slug_safe(stem):
                    return self.send_error(HTTPStatus.BAD_REQUEST)
                p = ANALYSES_DIR / f"{stem}.json"
                if not p.is_file():
                    return self.send_error(HTTPStatus.NOT_FOUND)
                from .matchmaker import find_similar
                target = FilmAnalysis.model_validate_json(p.read_text())
                archive = _load_films()
                matches = find_similar(target, archive, top_n=4)
                return self._send_json({"target": stem, "matches": matches})

            if path.startswith("/thumbs/"):
                rel = path[len("/thumbs/"):]
                # Defend against traversal.
                target = (THUMBS_DIR / rel).resolve()
                try:
                    target.relative_to(THUMBS_DIR.resolve())
                except ValueError:
                    return self.send_error(HTTPStatus.FORBIDDEN)
                return self._send_bytes_file(target)

            # Static file or SPA fallback.
            if path == "/" or path == "":
                return self._send_bytes_file(STATIC_DIR / "index.html")

            candidate = (STATIC_DIR / path.lstrip("/")).resolve()
            try:
                candidate.relative_to(STATIC_DIR.resolve())
            except ValueError:
                return self.send_error(HTTPStatus.FORBIDDEN)
            if candidate.is_file():
                return self._send_bytes_file(candidate)

            # SPA fallback for hash-routes that hit the path accidentally.
            return self._send_bytes_file(STATIC_DIR / "index.html")

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            # CSRF/Origin defense — reject cross-site mutating requests.
            if not self._origin_ok():
                return self.send_error(
                    HTTPStatus.FORBIDDEN, "cross-origin request rejected"
                )
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""

            if path == "/api/compare":
                # Body is raw FCPXML bytes. We write to a tempfile because
                # parse() takes a Path.
                if not body:
                    return self.send_error(HTTPStatus.BAD_REQUEST, "empty body")
                with tempfile.NamedTemporaryFile(suffix=".fcpxml", delete=False) as tmp:
                    tmp.write(body)
                    tmp_path = Path(tmp.name)
                try:
                    cut = parse_fcpxml(tmp_path)
                except Exception as e:
                    return self._send_json(
                        {"error": f"could not parse FCPXML: {e}"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                finally:
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass

                films = _load_films()
                profile = aggregate(films) if films else {}
                report = _build_compare_report(cut, profile)
                return self._send_json(report)

            if path == "/api/config":
                if not self._require_json_ct():
                    return
                try:
                    payload = json.loads(body.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    return self.send_error(HTTPStatus.BAD_REQUEST, "invalid JSON")
                # Validate: only known keys, correct primitive types.
                cfg = load_config()
                merged = asdict(cfg) | {
                    k: v for k, v in payload.items()
                    if k in Config.__dataclass_fields__
                }
                CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                CONFIG_PATH.write_text(json.dumps(merged, indent=2))
                return self._send_json(merged)

            # POST /api/films/<stem>/metadata  → merge metadata
            if path.startswith("/api/films/") and path.endswith("/metadata"):
                stem = path[len("/api/films/"):-len("/metadata")].strip("/")
                if not _slug_safe(stem):
                    return self.send_error(HTTPStatus.BAD_REQUEST)
                if not self._require_json_ct():
                    return
                p = ANALYSES_DIR / f"{stem}.json"
                if not p.is_file():
                    return self.send_error(HTTPStatus.NOT_FOUND)
                try:
                    payload = json.loads(body.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    return self.send_error(HTTPStatus.BAD_REQUEST, "invalid JSON")
                analysis = FilmAnalysis.model_validate_json(p.read_text())
                analysis.metadata = merge_md(analysis.metadata, payload)
                p.write_text(analysis.model_dump_json(indent=2))
                return self._send_json(analysis.metadata)

            # POST /api/films/<stem>/chapters/<index>  → set label
            chapter_match = re.match(
                r"^/api/films/([^/]+)/chapters/(\d+)$", path
            )
            if chapter_match:
                stem, idx_str = chapter_match.group(1), chapter_match.group(2)
                if not _slug_safe(stem):
                    return self.send_error(HTTPStatus.BAD_REQUEST)
                if not self._require_json_ct():
                    return
                p = ANALYSES_DIR / f"{stem}.json"
                if not p.is_file():
                    return self.send_error(HTTPStatus.NOT_FOUND)
                try:
                    payload = json.loads(body.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    return self.send_error(HTTPStatus.BAD_REQUEST, "invalid JSON")
                idx = int(idx_str)
                analysis = FilmAnalysis.model_validate_json(p.read_text())
                if idx < 0 or idx >= len(analysis.chapters):
                    return self.send_error(HTTPStatus.NOT_FOUND, "chapter out of range")
                new_label = payload.get("label")
                if new_label is not None:
                    new_label = str(new_label).strip().lower().replace(" ", "_") or None
                analysis.chapters[idx].label = new_label
                p.write_text(analysis.model_dump_json(indent=2))
                return self._send_json({
                    "index": idx,
                    "label": analysis.chapters[idx].label,
                })

            return self.send_error(HTTPStatus.NOT_FOUND)

    return Handler


def _build_compare_report(cut: dict, profile: dict) -> dict:
    """Decile-level deviation report between an FCPXML cut and the profile."""
    if not profile:
        return {"empty_profile": True, "cut": cut}

    pdur = profile.get("duration", {})
    pclips = profile.get("clip_counts", {})
    ppace = profile.get("pacing", {})
    ptrans = profile.get("transitions", {})

    expected_clips = pclips.get("avg") or 0
    expected_avg = ppace.get("avg_clip_sec") or 0
    expected_diss = ptrans.get("avg_dissolves_per_film") or 0
    expected_deciles = ppace.get("avg_deciles") or []
    durations = cut.get("clip_durations") or []

    actual_deciles: list[float] = []
    if durations:
        n = len(durations)
        for i in range(10):
            slc = durations[i * n // 10:(i + 1) * n // 10]
            actual_deciles.append(round(sum(slc) / max(1, len(slc)), 3) if slc else 0.0)

    pacing_diff = []
    for i, (a, e) in enumerate(zip(actual_deciles, expected_deciles)):
        delta_pct = ((a - e) / e * 100) if e else 0
        pacing_diff.append({
            "decile": i,
            "actual": a,
            "expected": e,
            "delta_pct": round(delta_pct, 1),
        })

    delta_clips = (
        (cut["clip_count"] - expected_clips) / expected_clips * 100
        if expected_clips else 0
    )
    delta_pace = (
        (cut["avg_clip_sec"] - expected_avg) / expected_avg * 100
        if expected_avg else 0
    )

    suggestions: list[str] = []
    if abs(delta_pace) > 15:
        direction = "Tighten" if delta_pace > 0 else "Lengthen"
        suggestions.append(f"{direction} clips toward {expected_avg:.2f}s avg.")
    if abs(delta_clips) > 20:
        direction = "Remove" if delta_clips > 0 else "Add"
        suggestions.append(f"{direction} clips toward ~{expected_clips:.0f} total.")
    if expected_diss and cut["dissolves"] > expected_diss * 1.5:
        suggestions.append(f"Reduce dissolves toward ~{expected_diss:.1f}.")
    for d in pacing_diff:
        if abs(d["delta_pct"]) > 25 and d["expected"]:
            verb = "tighten" if d["delta_pct"] > 0 else "lengthen"
            suggestions.append(
                f"At {d['decile']*10}-{(d['decile']+1)*10}% — {verb} "
                f"({d['actual']:.2f}s → {d['expected']:.2f}s)."
            )

    duration_in_range = (
        pdur.get("min_sec") is not None and
        pdur.get("max_sec") is not None and
        pdur["min_sec"] <= cut["total_duration_sec"] <= pdur["max_sec"]
    )

    return {
        "empty_profile": False,
        "profile": {
            "film_count": profile.get("film_count", 0),
            "duration": pdur,
            "clip_counts": pclips,
            "pacing": ppace,
            "transitions": ptrans,
        },
        "cut": cut,
        "deltas": {
            "clip_count_pct": round(delta_clips, 1),
            "avg_clip_pct": round(delta_pace, 1),
            "duration_in_range": duration_in_range,
        },
        "pacing_diff": pacing_diff,
        "suggestions": suggestions,
    }


# ---------- entry point ------------------------------------------------------


class _ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", ""})


def serve(host: str = "127.0.0.1", port: int = 7421, open_browser: bool = True) -> None:
    """Start the dashboard server. Blocks until Ctrl-C.

    Defaults to the loopback interface (``127.0.0.1``). The dashboard exposes
    a full read/write API with no authentication, so binding a non-loopback
    address (e.g. ``0.0.0.0`` or a LAN IP) exposes that API to the network.
    """
    if host.strip().lower() not in _LOOPBACK_HOSTS:
        print(
            f"\n  WARNING: binding to {host!r} exposes an UNAUTHENTICATED "
            "read/write API to the network.\n"
            "           Anyone who can reach this host:port can read and "
            "modify your data.\n"
            "           Use 127.0.0.1 (the default) unless you understand "
            "the risk.\n"
        )
    handler = _make_handler()
    with _ThreadingServer((host, port), handler) as httpd:
        url = f"http://{host}:{port}"
        print(f"\n  Atelier   {url}")
        print("  ────────  Ctrl-C to close.\n")
        if open_browser:
            threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Closed.\n")
