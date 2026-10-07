import json

import pytest

from film_style_analyzer.eddie import (
    BRIEF_MAX_CHARS,
    STYLE_WORDS_MAX_CHARS,
    build_plan,
    selects_from_scores,
    style_words,
)

PROFILE = {
    "film_count": 12,
    "genre": "wedding",
    "genre_display_name": "Wedding Film",
    "duration": {"target_min_sec": 240, "target_max_sec": 420,
                 "target_median_sec": 330, "target_avg_sec": 335},
    "pacing": {"target_avg_clip_sec": 3.2, "decile_curve": [4, 3, 3, 3, 3, 3, 3, 3, 3, 5]},
    "transitions": {"hard_cut_pct": 92, "dissolve_pct": 7,
                    "avg_dissolves_per_film": 6.4},
    "audio": {"present": True, "speech_over_music_pct_target": 30},
    "color": {"present": True, "mean_warm_cool": 0.2, "mean_saturation": 99,
              "mean_contrast": 60, "mean_luminance": 110},
    "music": {"present": True, "cut_on_beat_pct_target": 64},
    "scenes": {
        "ceremony": {"avg_clip_duration_sec": 4.8, "avg_duration_sec": 90,
                     "pct_of_total_runtime": 30},
        "dance_floor": {"avg_clip_duration_sec": 1.6, "avg_duration_sec": 40,
                        "pct_of_total_runtime": 12},
    },
    "structure": {"closing": {"fade_to_black_ratio": 0.8}},
    "rules": ["Target average clip duration 3.20s.", "End with a fade to black."],
}


def test_plan_maps_profile_to_eddie_arguments():
    plan = build_plan(PROFILE)
    build = plan["create_edit_result"]
    assert build["targetDurationMinutes"] == 5.5
    assert build["minimumDurationMinutes"] == 4.0
    assert "Target average clip duration" in build["brief"]
    assert "ceremony: shots average 4.8s" in build["brief"]
    assert len(build["brief"]) <= BRIEF_MAX_CHARS
    assert plan["transitions"]["fade_out_at_end"] is True
    assert plan["beats"]["snap"] is True
    assert plan["scene_targets"][0]["scene"] == "ceremony"
    g = plan["grade"]["grade_edit"]
    assert g["lookMatch"] is True and g["temperature"] == 8
    assert 0.8 <= g["saturation"] <= 1.2 and 0.85 <= g["contrast"] <= 1.15
    assert plan["apply_style"]["save"]["saveName"] == "Wedding Film - my style"
    json.dumps(plan)  # serialisable


def test_recipe_template_blanks_match_inputs():
    recipe = build_plan(PROFILE)["recipe"]
    for inp in recipe["inputs"]:
        assert "{" + inp["id"] + "}" in recipe["promptTemplate"]
    assert recipe["inputs"][0]["defaultValue"] == 5.5


def test_style_words_fit_eddie_limit():
    words = style_words(PROFILE)
    assert 0 < len(words) <= STYLE_WORDS_MAX_CHARS
    assert words.startswith("Wedding Film, 4-7 min.")
    long = dict(PROFILE, genre_display_name="W" * 290)
    assert len(style_words(long)) <= STYLE_WORDS_MAX_CHARS


def test_plan_without_music_or_color():
    lean = {k: v for k, v in PROFILE.items() if k not in ("music", "color")}
    plan = build_plan(lean)
    assert plan["beats"]["snap"] is False
    assert plan["grade"] is None


def test_plan_requires_films():
    with pytest.raises(ValueError):
        build_plan({"film_count": 0})


def test_selects_filter_and_shape():
    scores = {"clips": [
        {"file": "/p/A001_proxy.mov", "original": "/o/A001.MXF", "score": 88,
         "duration_sec": 20, "scene": "ceremony",
         "trim": {"trim_in_sec": 1.5, "trim_out_sec": 12.0, "reason": "stable"}},
        {"file": "/p/A002_proxy.mov", "original": "/o/A002.MXF", "score": 40,
         "duration_sec": 10},
        {"file": "/p/A003_proxy.mov", "score": 95, "duration_sec": 8,
         "rejection": "no_person"},
        {"file": "/p/A004_proxy.mov", "original": "/o/A004.MXF", "score": 75,
         "duration_sec": 6},
        {"file": "/p/A005_proxy.mov", "score": 90, "duration_sec": 6,
         "trim": {"trim_in_sec": 0, "trim_out_sec": 0, "reason": "no_stable_frames"}},
    ]}
    out = selects_from_scores(scores, min_score=70)
    assert out["kept"] == 2
    assert out["skipped"] == {"rejected": 1, "below_min_score": 1, "no_usable_range": 1}
    first, second = out["soundbites"]
    assert first == {"sourceId": "A001_proxy.mov", "fileName": "A001.MXF",
                     "in": 1.5, "out": 12.0,
                     "reason": "score 88, ceremony, trim: stable"}
    assert (second["in"], second["out"]) == (0.0, 6.0)
    assert out["whole_clips"] == 1
    assert "allowWholeSourceClips" in out["notes"][0]
    assert selects_from_scores(scores, use_original_names=True)["soundbites"][0]["sourceId"] == "A001.MXF"
