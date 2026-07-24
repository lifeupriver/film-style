"""Regression tests for gemini_analyzer._extract_json."""

import json

import pytest

from film_style_analyzer.gemini_analyzer import _extract_json


def test_extract_plain_json():
    assert _extract_json('{"a": 1, "b": 2}') == {"a": 1, "b": 2}


def test_extract_fenced_json_with_nested_braces():
    raw = """```json
{"opening": {"first_shot": "wide", "duration": 5}, "closing": {"fade": true}}
```"""
    out = _extract_json(raw)
    assert out["opening"]["first_shot"] == "wide"
    assert out["closing"]["fade"] is True


def test_extract_strips_surrounding_prose():
    raw = 'Sure, here\'s the JSON: {"foo": "bar"}\nLet me know if that helps.'
    assert _extract_json(raw) == {"foo": "bar"}


def test_extract_invalid_json_raises():
    with pytest.raises(json.JSONDecodeError):
        _extract_json("no json at all")
