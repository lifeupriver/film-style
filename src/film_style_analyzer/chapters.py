"""Group clips into chapters between dissolve boundaries.

A chapter is a run of clips bounded by dissolves (or fade boundaries at film
ends). The wedding-film convention: dissolves mark scene transitions
(getting-ready → ceremony → speeches → dancing), so chapters approximate scene
groupings without needing visual classification.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .schemas import Clip


@dataclass
class Chapter:
    index: int
    start_clip: int
    end_clip: int  # inclusive
    start_sec: float
    end_sec: float
    duration_sec: float
    clip_count: int
    avg_clip_sec: float
    representative_thumbnail: str | None


def group(clips: list[Clip]) -> list[Chapter]:
    if not clips:
        return []

    # A chapter break occurs when a clip's transition_out is dissolve or fade_out.
    chapters: list[Chapter] = []
    start = 0
    for i, c in enumerate(clips):
        ends_chapter = c.transition_out in ("dissolve", "fade_out") or i == len(clips) - 1
        if ends_chapter:
            run = clips[start : i + 1]
            durations = [r.duration_sec for r in run]
            mid = run[len(run) // 2]
            chapters.append(
                Chapter(
                    index=len(chapters),
                    start_clip=run[0].index,
                    end_clip=run[-1].index,
                    start_sec=run[0].start_sec,
                    end_sec=run[-1].end_sec,
                    duration_sec=round(run[-1].end_sec - run[0].start_sec, 2),
                    clip_count=len(run),
                    avg_clip_sec=round(statistics.fmean(durations), 2) if durations else 0.0,
                    representative_thumbnail=mid.thumbnail,
                )
            )
            start = i + 1
    return chapters
