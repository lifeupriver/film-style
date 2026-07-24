from film_style_analyzer.chapters import group
from film_style_analyzer.schemas import Clip


def _clip(i: int, start: float, end: float, t_out: str = "hard_cut") -> Clip:
    return Clip(
        index=i,
        start_sec=start,
        end_sec=end,
        duration_sec=end - start,
        transition_in="hard_cut" if i > 0 else "fade_in",
        transition_out=t_out,
    )


def test_group_splits_on_dissolve():
    clips = [
        _clip(0, 0, 3),
        _clip(1, 3, 6, "dissolve"),
        _clip(2, 6, 9),
        _clip(3, 9, 12),
    ]
    chapters = group(clips)
    assert len(chapters) == 2
    assert chapters[0].clip_count == 2
    assert chapters[1].clip_count == 2
    assert chapters[0].end_sec == 6
    assert chapters[1].start_sec == 6


def test_group_single_chapter_when_no_dissolves():
    clips = [_clip(i, i * 3, (i + 1) * 3) for i in range(4)]
    chapters = group(clips)
    assert len(chapters) == 1
    assert chapters[0].clip_count == 4


def test_group_handles_empty():
    assert group([]) == []
