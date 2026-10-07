import json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from film_style_analyzer.cut_diff import correction, correction_rules, evaluate
from film_style_analyzer.eddie import build_plan
from film_style_analyzer.edit_decisions import parse_otio_doc, parse_project, source_key
from film_style_analyzer.edit_profile import build_edit_profile
from film_style_analyzer.learning_store import Store, load_learned
from film_style_analyzer.soundbites import build_soundbite_profile, normalize_transcript
from film_style_analyzer.structure import build_structure_template, find_reference_films

FIXTURE = Path(__file__).parent / "fixtures" / "wedding_project.fcpxml"


def _rt(sec, rate=24):
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": sec * rate}


def _clip(name, url, start, dur, *, available=None, speed=None, markers=()):
    c = {"OTIO_SCHEMA": "Clip.2", "name": name,
         "source_range": {"OTIO_SCHEMA": "TimeRange.1", "start_time": _rt(start), "duration": _rt(dur)},
         "media_reference": {"OTIO_SCHEMA": "ExternalReference.1", "target_url": url},
         "markers": [{"OTIO_SCHEMA": "Marker.2", "name": m,
                      "marked_range": {"OTIO_SCHEMA": "TimeRange.1", "start_time": _rt(start),
                                       "duration": _rt(0)}} for m in markers]}
    if available:
        c["media_reference"]["available_range"] = {
            "OTIO_SCHEMA": "TimeRange.1", "start_time": _rt(0), "duration": _rt(available)}
    if speed:
        c["effects"] = [{"OTIO_SCHEMA": "LinearTimeWarp.1", "time_scalar": speed}]
    return c


def _otio(video, audio=(), name="cut"):
    tracks = [{"OTIO_SCHEMA": "Track.1", "kind": "Video", "children": list(ch)} for ch in video]
    tracks += [{"OTIO_SCHEMA": "Track.1", "kind": "Audio", "name": n, "children": list(ch)}
               for n, ch in audio]
    return {"OTIO_SCHEMA": "Timeline.1", "name": name,
            "tracks": {"OTIO_SCHEMA": "Stack.1", "children": tracks}}


def eddie_like_cut():
    """The fixture's cut as another tool might export it: proxy file names,
    no b-roll, the dance shot longer, plus a shot the editor did not use."""
    return parse_otio_doc(_otio(
        video=[[_clip("vows", "file:///eddie/A001_vows_proxy.mp4", 10, 20, available=120),
                _clip("dance", "file:///eddie/B003_dance_proxy.mp4", 5, 24, available=30),
                _clip("extra", "file:///eddie/C009_cake_proxy.mp4", 0, 6, available=10)]],
        audio=[("Dialogue", [_clip("vows", "file:///eddie/A001_vows_proxy.mp4", 10, 20)])],
    ), "eddie")


# --- 1 & 7: project files --------------------------------------------------

def test_source_key_matches_proxies_and_originals():
    assert source_key("/Volumes/A/A001_C003_proxy.mov") == source_key("A001_C003.MXF") == "a001c003"


def test_fcpxml_project_decisions():
    p = parse_project(FIXTURE)
    assert p["name"] == "Smith Highlight" and p["duration_sec"] == 40
    by = {e["source_key"]: e for e in p["events"]}
    assert by["a001vows"]["source_in"] == 10 and by["a001vows"]["audible"]
    assert by["b002rings"]["speed"] == 0.5 and by["b002rings"]["timeline_start"] == 5
    assert not by["b002rings"]["audible"]
    assert by["b003dance"]["scale"] == 1.2
    assert by["song"]["is_music"] and by["song"]["track"] == "audio"
    assert [t["kind"] for t in p["transitions"]] == ["dissolve", "fade"]
    assert [m["name"] for m in p["markers"]] == ["Ceremony", "Reception"]


def test_otio_project_decisions():
    p = parse_otio_doc(_otio(
        video=[[_clip("a", "file:///m/A.mov", 2, 4, available=10, markers=["Getting ready"]),
                _clip("b", "file:///m/B.mov", 0, 3, speed=0.5)]],
        audio=[("Music", [_clip("song", "file:///m/song.wav", 0, 7)]),
               ("Dialogue", [_clip("a", "file:///m/A.mov", 2, 4)])]))
    by = {(e["track"], e["source_key"]): e for e in p["events"]}
    assert by[("video", "a")]["audible"] and not by[("video", "b")]["audible"]
    assert by[("video", "b")]["speed"] == 0.5
    assert by[("audio", "song")]["is_music"]
    assert p["markers"][0]["name"] == "Getting ready"
    assert p["sources"]["a"]["duration"] == 10


def test_edit_profile_rules():
    prof = build_edit_profile([parse_project(FIXTURE)])
    d = prof["decisions"]
    assert d["dissolve_sec"] == 2.0 and d["slow_motion_speed"] == 0.5
    assert d["punch_in_scale"] == 1.2 and d["broll_coverage_pct"] == 10.0
    assert d["ends_with_fade_ratio"] == 1.0 and d["music_tracks"] == 1
    assert any("slow motion" in r for r in prof["rules"])


# --- 3 & 4: running order, reference film ---------------------------------

def _film(stem, sections, *, metadata=None, dur=100.0):
    chapters = []
    t = 0.0
    for label, length in sections:
        chapters.append(SimpleNamespace(label=label, start_sec=t, end_sec=t + length))
        t += length
    return SimpleNamespace(
        film=SimpleNamespace(filename=f"{stem}.mp4", duration_sec=dur),
        chapters=chapters, metadata=metadata or {},
        analyzed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        cuts=SimpleNamespace(total=30),
        pacing=SimpleNamespace(avg_clip_duration_sec=3.3, pacing_curve_by_decile=[3.3] * 10),
        transitions=SimpleNamespace(dissolve=4))


def test_structure_template_order_and_rules():
    films = [
        _film("a", [("getting_ready", 20), ("ceremony", 50), ("reception", 30)]),
        _film("b", [("getting_ready", 10), ("first_look", 10), ("ceremony", 40), ("reception", 40)]),
        _film("c", [("ceremony", 60), ("reception", 40)]),
    ]
    t = build_structure_template(films)
    assert [s["label"] for s in t["sections"]][:2] == ["getting_ready", "first_look"]
    assert t["closing"][0] == {"label": "reception", "films": 3}
    assert t["rules"][0].startswith("Running order: getting ready")
    assert any("Sometimes included: first look" in r for r in t["rules"])


def test_structure_from_project_markers():
    t = build_structure_template([], [{"name": "p", "project": parse_project(FIXTURE)}])
    assert [s["label"] for s in t["sections"]] == ["ceremony", "reception"]


def test_reference_film_by_metadata():
    films = [_film("a", [("ceremony", 100)], metadata={"venue": "Mohonk"}),
             _film("b", [("ceremony", 100)], metadata={"venue": "Other"})]
    refs = find_reference_films(films, metadata={"venue": "mohonk"},
                                projects=[{"name": "p", "film_stem": "a",
                                           "project": parse_project(FIXTURE)}])
    assert [r["stem"] for r in refs] == ["a"]
    assert refs[0]["project"]["decisions"]["dissolve_sec"] == 2.0
    with pytest.raises(ValueError):
        find_reference_films(films, like="missing")


# --- 2: spoken lines ------------------------------------------------------

VOWS = {"segments": [
    {"start_sec": 0, "end_sec": 5, "text": "Okay, are we rolling?"},
    {"start_sec": 5, "end_sec": 12, "text": "I wrote this last night."},
    {"start_sec": 12, "end_sec": 20, "text": "You make every ordinary day feel like home."},
    {"start_sec": 20, "end_sec": 28, "text": "I promise to keep choosing you."},
    {"start_sec": 28, "end_sec": 35, "text": "Sorry, I lost my place."},
]}


def test_soundbite_labelling_and_rules():
    rec = {"name": "smith", "film_stem": "smith", "project": parse_project(FIXTURE)}
    prof = build_soundbite_profile([rec], {"a001vows": VOWS})
    lines = prof["examples"][0]["lines"]
    assert [l["kept"] for l in lines] == [False, False, True, True, False]
    assert lines[2]["film_sec"] == 2.0
    assert prof["stats"]["keep_rate_pct"] == 40.0
    assert prof["openers"][0]["text"].startswith("You make every")
    assert prof["closers"][0]["text"].startswith("I promise")
    assert prof["rules"]


def test_normalize_eddie_style_transcript():
    segs = normalize_transcript({"segments": [{"start": 1, "end": 2, "text": " hi ",
                                               "speakerName": "Ana"}]})
    assert segs == [{"start": 1.0, "end": 2.0, "text": "hi", "speaker": "Ana"}]


# --- 5 & 6: evaluation and corrections --------------------------------------

def test_evaluate_identical_cut_scores_100():
    p = parse_project(FIXTURE)
    r = evaluate(p, p)
    assert r["score"] == 100.0
    assert r["moments"]["recall"] == 1.0 and r["lines"]["recall"] == 1.0
    assert r["missed"] == []


def test_evaluate_other_tool_cut():
    r = evaluate(parse_project(FIXTURE), eddie_like_cut())
    assert r["sources"]["shared"] == 2  # proxies matched to originals
    assert 0 < r["score"] < 100
    assert r["moments"]["recall"] < 1.0
    assert any(g["source_key"] == "b002rings" for g in r["missed"])
    assert r["lines"]["recall"] == 1.0


def test_correction_and_rules():
    rec = correction(eddie_like_cut(), parse_project(FIXTURE), note="tightened dance")
    s = rec["summary"]
    assert s["removed_shots"] == 1 and rec["removed"][0]["source_key"] == "c009cake"
    assert s["added_shots"] == 1 and rec["added"][0]["source_key"] == "b002rings"
    dance = next(t for t in rec["trims"] if t["source_key"] == "b003dance")
    assert dance["tail_sec"] == 4.0
    rules = correction_rules([rec, rec])
    assert rules["corrections"] == 2
    assert rules["rules"]


# --- 8 + integration: store, Eddie references, plan ---------------------------

def test_plan_uses_everything_learned(tmp_path):
    store = Store(tmp_path)
    project = parse_project(FIXTURE)
    store.save_project(project, film_stem="smith")
    store.write_json(store.edit_profile, build_edit_profile([project]))
    store.write_json(store.structure_template,
                     build_structure_template([], store.load_projects()))
    store.write_json(store.soundbite_profile,
                     build_soundbite_profile(store.load_projects(), {"a001vows": VOWS}))
    store.append_correction(correction(eddie_like_cut(), project))
    store.save_eddie_reference("card", {"pace": "measured"}, "smith card", "smith")

    from test_eddie import PROFILE
    plan = build_plan(PROFILE, load_learned(store))
    brief = plan["create_edit_result"]["brief"]
    assert "How I build a cut" in brief and "Running order" in brief
    assert "How I choose spoken lines" in brief and "From my corrections" in brief
    assert plan["transitions"]["dissolve_duration_sec"] == 2.0
    assert plan["transitions"]["dissolve_duration_measured"] is True
    assert plan["visual"]["slow_motion"]["speed"] == 0.5
    assert plan["visual"]["punch_in"]["scale"] == 1.2
    assert plan["structure"][0]["label"] == "ceremony"
    assert plan["apply_style"]["card"] == {"pace": "measured"}
    assert plan["corrections"]
    json.dumps(plan)
