"""Smoke tests: prompts in network-calling modules are sourced from the pack."""

from __future__ import annotations

from film_style_analyzer import genre_pack
from film_style_analyzer.guide_writer import build_system_prompt
from film_style_analyzer.gemini_analyzer import build_film_prompt, build_youtube_prompt
from film_style_analyzer.notebooklm_export import build_brief_intro


def test_guide_system_prompt_from_pack():
    pack = genre_pack.load("wedding")
    s = build_system_prompt(pack)
    assert "wedding filmmaker" in s.lower()


def test_gemini_film_prompt_uses_pack_and_substitutes_runtime_vars():
    pack = genre_pack.load("wedding")
    p = build_film_prompt(pack, duration="5:00", cuts=120)
    assert "5:00" in p
    assert "120" in p
    assert "wedding film" in p.lower()


def test_gemini_youtube_prompt_from_pack():
    pack = genre_pack.load("wedding")
    p = build_youtube_prompt(pack)
    assert "wedding" in p.lower()


def test_notebooklm_intro_substitutes_brand_and_count():
    pack = genre_pack.load("wedding")
    text = build_brief_intro(pack, brand_name="Test Studio", n=42)
    assert "Test Studio" in text
    assert "42" in text
    assert "wedding" in text.lower()
