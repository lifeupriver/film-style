"""Test that vision_classify and shot_size honor a GenrePack."""

from __future__ import annotations

from film_style_analyzer import genre_pack
from film_style_analyzer.vision_classify import build_chapter_system_prompt
from film_style_analyzer.shot_size import build_shot_system_prompt


def test_chapter_prompt_uses_pack_labels():
    pack = genre_pack.load("wedding")
    prompt = build_chapter_system_prompt(pack)
    assert "ceremony" in prompt
    assert "first_dance" in prompt
    assert "wedding film" in prompt.lower()


def test_shot_prompt_uses_pack_labels_and_insert_def():
    pack = genre_pack.load("wedding")
    prompt = build_shot_system_prompt(pack)
    assert "extreme_wide" in prompt
    assert "rings" in prompt.lower()
