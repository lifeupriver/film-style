"""Per-film metadata tagging."""

import pytest

from film_style_analyzer import genre_pack
from film_style_analyzer.metadata import curated_keys, group_by, merge, parse_set_arg


def test_parse_set_arg_basic():
    assert parse_set_arg("venue=indoor") == ("venue", "indoor")
    assert parse_set_arg("  Season = Summer  ") == ("season", "Summer")


def test_parse_set_arg_invalid():
    with pytest.raises(ValueError):
        parse_set_arg("no-equals-sign")


def test_merge_adds_and_removes():
    base = {"venue": "indoor", "season": "summer"}
    out = merge(base, {"weather": "sunny", "venue": None})
    assert out == {"season": "summer", "weather": "sunny"}


def test_merge_treats_empty_string_as_unset():
    assert merge({"a": "x"}, {"a": ""}) == {}


def test_curated_keys_have_expected_dimensions():
    expected = {"venue", "season", "music_genre", "ceremony", "guest_count"}
    pack = genre_pack.load("wedding")
    assert expected.issubset(curated_keys(pack).keys())


def test_curated_keys_returns_pack_metadata():
    pack = genre_pack.load("wedding")
    keys = curated_keys(pack)
    assert keys == pack.metadata_keys
    assert "indoor" in keys["venue"]


class _F:
    def __init__(self, md):
        self.metadata = md


def test_group_by_buckets_unset():
    a, b, c = _F({"venue": "indoor"}), _F({"venue": "indoor"}), _F({})
    out = group_by([a, b, c], "venue")
    assert len(out["indoor"]) == 2
    assert len(out["_unset"]) == 1
