"""Where learned edit data lives, under the active genre's folder.

    <genre>/projects/<name>.json       parsed project timelines (add-project)
    <genre>/edit-profile.json          learned edit decisions (learn-edits)
    <genre>/structure-template.json    section order (learn-edits)
    <genre>/soundbite-profile.json     how lines are chosen (learn-soundbites)
    <genre>/transcripts/<key>.json     raw-source transcripts used for that
    <genre>/corrections.jsonl          one record per learn-correction
    <genre>/eddie/<kind>/<name>.json   Eddie shot lists and style cards
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:80] or "untitled"


class Store:
    def __init__(self, genre_root: Path):
        self.root = genre_root

    # -- paths ---------------------------------------------------------------
    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    @property
    def transcripts_dir(self) -> Path:
        return self.root / "transcripts"

    @property
    def edit_profile(self) -> Path:
        return self.root / "edit-profile.json"

    @property
    def structure_template(self) -> Path:
        return self.root / "structure-template.json"

    @property
    def soundbite_profile(self) -> Path:
        return self.root / "soundbite-profile.json"

    @property
    def corrections(self) -> Path:
        return self.root / "corrections.jsonl"

    def eddie_dir(self, kind: str) -> Path:
        return self.root / "eddie" / kind

    # -- projects --------------------------------------------------------------
    def save_project(self, project: dict, *, name: str | None = None,
                     film_stem: str | None = None, source_path: str = "") -> Path:
        name = slug(name or project.get("name") or Path(source_path).stem)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "name": name,
            "film_stem": film_stem,
            "source_path": source_path,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "project": project,
        }
        p = self.projects_dir / f"{name}.json"
        p.write_text(json.dumps(record, indent=2))
        return p

    def load_projects(self) -> list[dict]:
        if not self.projects_dir.is_dir():
            return []
        out = []
        for p in sorted(self.projects_dir.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
        return out

    def project_for_film(self, film_stem: str) -> dict | None:
        for rec in self.load_projects():
            if rec.get("film_stem") == film_stem:
                return rec
        return None

    # -- transcripts ------------------------------------------------------------
    def load_transcripts(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if self.transcripts_dir.is_dir():
            for p in self.transcripts_dir.glob("*.json"):
                try:
                    out[p.stem] = json.loads(p.read_text())
                except (OSError, json.JSONDecodeError):
                    continue
        return out

    def save_transcript(self, key: str, transcript: dict) -> Path:
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        p = self.transcripts_dir / f"{key}.json"
        p.write_text(json.dumps(transcript, indent=2))
        return p

    # -- json helpers -------------------------------------------------------------
    @staticmethod
    def read_json(path: Path) -> dict | None:
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def write_json(path: Path, data: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))
        return path

    # -- corrections ----------------------------------------------------------
    def append_correction(self, record: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.corrections.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def load_corrections(self) -> list[dict]:
        if not self.corrections.is_file():
            return []
        out = []
        for line in self.corrections.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    # -- Eddie references -----------------------------------------------------------
    def save_eddie_reference(self, kind: str, data: dict, name: str,
                             film_stem: str | None = None) -> Path:
        d = self.eddie_dir(kind)
        d.mkdir(parents=True, exist_ok=True)
        record = {
            "kind": kind,
            "name": slug(name),
            "film_stem": film_stem,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        p = d / f"{slug(name)}.json"
        p.write_text(json.dumps(record, indent=2))
        return p

    def load_eddie_references(self, kind: str | None = None) -> list[dict]:
        base = self.root / "eddie"
        if not base.is_dir():
            return []
        kinds = [kind] if kind else [p.name for p in base.iterdir() if p.is_dir()]
        out = []
        for k in kinds:
            for p in sorted((base / k).glob("*.json")):
                try:
                    out.append(json.loads(p.read_text()))
                except (OSError, json.JSONDecodeError):
                    continue
        out.sort(key=lambda r: r.get("saved_at", ""))
        return out
