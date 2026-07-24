"""Tests for the genre_pack module."""

from __future__ import annotations

import pytest

from film_style_analyzer import genre_pack
from film_style_analyzer.genre_pack import GenrePack


def test_load_wedding_pack():
    pack = genre_pack.load("wedding")
    assert isinstance(pack, GenrePack)
    assert pack.name == "wedding"
    assert pack.display_name == "wedding film"
    assert pack.scene_detect_threshold == 8.0
    assert pack.min_scene_length_sec == 0.5
    assert pack.audio_emphasis == "music_first"
    assert pack.still_hold_relevant is True
    assert "ceremony" in pack.scene_labels
    assert "first_dance" in pack.scene_labels
    assert "insert" in pack.shot_labels
    assert "rings" in pack.insert_definition.lower()


def test_pack_required_prompts_present():
    pack = genre_pack.load("wedding")
    required = {
        "guide_writer_system",
        "chapter_classify_system",
        "shot_classify_system",
        "gemini_film_prompt",
        "gemini_youtube_prompt",
        "mcp_edit_in_style",
        "notebooklm_brief_intro",
    }
    assert required.issubset(pack.prompts.keys())


def test_pack_metadata_keys_structure():
    pack = genre_pack.load("wedding")
    assert "venue" in pack.metadata_keys
    assert isinstance(pack.metadata_keys["venue"], list)
    assert "indoor" in pack.metadata_keys["venue"]


def test_load_unknown_pack_raises():
    with pytest.raises(genre_pack.GenrePackError):
        genre_pack.load("nonexistent_genre_xyz")


def test_list_available_includes_wedding():
    names = genre_pack.list_available()
    assert "wedding" in names


def test_pack_is_frozen():
    pack = genre_pack.load("wedding")
    with pytest.raises((AttributeError, Exception)):
        pack.name = "changed"


def test_scene_labels_no_duplicates():
    pack = genre_pack.load("wedding")
    assert len(pack.scene_labels) == len(set(pack.scene_labels))


def test_scene_and_shot_labels_have_minimal_overlap():
    """Scene and shot labels live in different namespaces, but 'other' as a
    shared fallback is fine — that's the only acceptable overlap."""
    pack = genre_pack.load("wedding")
    overlap = set(pack.scene_labels) & set(pack.shot_labels)
    assert overlap <= {"other"}, f"unexpected scene/shot overlap: {overlap - {'other'}}"


def test_wedding_emotion_scene_weights():
    pack = genre_pack.load("wedding")
    assert pack.emotion_scene_weights["ceremony"] == 1.5
    assert pack.emotion_scene_weights["b_roll"] == 0.0


def test_commercial_emotion_scene_weights_differ():
    wedding = genre_pack.load("wedding")
    commercial = genre_pack.load("commercial")
    assert commercial.emotion_scene_weights.get("hook", 1.0) == 1.0
    assert "ceremony" not in commercial.emotion_scene_weights
    assert wedding.emotion_scene_weights["ceremony"] == 1.5


@pytest.mark.parametrize(
    "name",
    [
        "wedding",
        "commercial",
        "brand_content",
        "social_short",
        "music_video",
        "documentary",
    ],
)
def test_all_shipped_packs_load(name):
    pack = genre_pack.load(name)
    assert pack.name == name
    assert pack.display_name
    assert pack.scene_labels
    assert pack.shot_labels
    assert pack.audio_emphasis in {
        "music_first",
        "voiceover_first",
        "beat_locked",
        "interview",
        "hook_driven",
    }
    assert len(pack.scene_labels) == len(set(pack.scene_labels))
    assert len(pack.shot_labels) == len(set(pack.shot_labels))
    for key in (
        "guide_writer_system",
        "chapter_classify_system",
        "shot_classify_system",
        "gemini_film_prompt",
        "gemini_youtube_prompt",
        "mcp_edit_in_style",
        "notebooklm_brief_intro",
    ):
        assert key in pack.prompts
