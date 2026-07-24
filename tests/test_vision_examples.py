"""Few-shot example selection for the vision classifier."""

from pathlib import Path

from film_style_analyzer.vision_classify import _pick_diverse_examples, gather_existing_examples


def test_pick_diverse_examples_round_robin():
    examples = (
        [(Path(f"/a{i}.jpg"), "ceremony") for i in range(5)]
        + [(Path(f"/b{i}.jpg"), "dancing") for i in range(5)]
        + [
            (Path("/c.jpg"), "first_dance"),
        ]
    )
    chosen = _pick_diverse_examples(examples, max_examples=4)
    labels = {label for _, label in chosen}
    # Round-robin should hit all 3 labels before doubling up on any.
    assert len(labels) == 3
    assert len(chosen) == 4


def test_pick_diverse_examples_caps_at_max():
    examples = [(Path(f"/{i}.jpg"), "ceremony") for i in range(20)]
    chosen = _pick_diverse_examples(examples, max_examples=3)
    assert len(chosen) == 3


def test_gather_examples_walks_analyses(tmp_path: Path):
    analyses = tmp_path / "analyses"
    analyses.mkdir()
    data_root = tmp_path

    import json as _json

    (analyses / "a.json").write_text(
        _json.dumps(
            {
                "chapters": [
                    {"label": "ceremony", "representative_thumbnail": "thumbs/a/clip_001.jpg"},
                    {"label": None, "representative_thumbnail": "thumbs/a/clip_002.jpg"},
                    {"label": "dancing", "representative_thumbnail": "thumbs/a/clip_003.jpg"},
                ],
            }
        )
    )

    out = gather_existing_examples(analyses, data_root)
    # Two labeled chapters, one with no label, one with no thumb. → 2 results.
    assert len(out) == 2
    assert {label for _, label in out} == {"ceremony", "dancing"}
    # Paths resolve through data_root.
    for p, _ in out:
        assert str(p).startswith(str(data_root))


def test_gather_examples_handles_missing_dir(tmp_path: Path):
    out = gather_existing_examples(tmp_path / "nonexistent", tmp_path)
    assert out == []
