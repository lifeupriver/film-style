"""Scene detection tests. Most paths require real media — opt in via --real-media."""

import pytest

from film_style_analyzer.scene_detect import detect_clips


@pytest.mark.needs_real_media
def test_detect_clips_real(real_media):
    clips = detect_clips(real_media, min_scene_length_sec=0.5)
    assert clips, "expected at least one clip from real media"
    for c in clips:
        assert c.end_sec > c.start_sec
        assert c.duration_sec > 0
        assert c.transition_in in ("hard_cut", "dissolve", "fade_in", "fade_out")
        assert c.transition_out in ("hard_cut", "dissolve", "fade_in", "fade_out")
    assert clips[0].transition_in == "fade_in"
    assert clips[-1].transition_out == "fade_out"
