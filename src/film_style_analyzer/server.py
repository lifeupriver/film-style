"""Local-first dashboard server.

Stdlib only. Serves a single-page app from ./static/ and exposes a small JSON
API over the data the CLI writes to ~/.film-style-analyzer/.
"""

from __future__ import annotations

import json
import mimetypes
import re
import socketserver
import tempfile
import threading
import webbrowser
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
ANALYSES_DIR = DATA_ROOT / "analyses"
THUMBS_DIR = DATA_ROOT / "thumbs"
GUIDE_PATH = DATA_ROOT / "style-guide.md"
STATS_PATH = DATA_ROOT / "aggregate-stats.json"
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


def _slug_safe(name: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9._\-]+$", name))


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


def serve(host: str = "127.0.0.1", port: int = 7421, open_browser: bool = True) -> None:
    """Start the dashboard server. Blocks until Ctrl-C."""
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
