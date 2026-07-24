"""Shot-size: pure-function tests (no API calls)."""

from film_style_analyzer.schemas import Clip
from film_style_analyzer.shot_size import SHOT_LABELS, summarize_shot_mix


def _clip(i, size=None):
    c = Clip(
        index=i,
        start_sec=i,
        end_sec=i + 1,
        duration_sec=1.0,
        transition_in="hard_cut",
        transition_out="hard_cut",
    )
    c.shot_size = size
    return c


def test_summarize_empty():
    assert summarize_shot_mix([])["labeled_clips"] == 0


def test_summarize_distribution_and_dominant():
    clips = [_clip(0, "wide"), _clip(1, "wide"), _clip(2, "close_up"), _clip(3, None)]
    s = summarize_shot_mix(clips)
    assert s["labeled_clips"] == 3
    assert s["dominant"] == "wide"
    assert s["distribution"]["wide"] == 66.7
    assert s["distribution"]["close_up"] == 33.3


def test_label_set_includes_expected_categories():
    expected = {"wide", "close_up", "extreme_close", "insert", "over_shoulder"}
    assert expected.issubset(set(SHOT_LABELS))
