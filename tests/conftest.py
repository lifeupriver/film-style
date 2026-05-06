"""pytest plumbing — opt-in real-media tests via --real-media."""

from __future__ import annotations

from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--real-media",
        action="store",
        default=None,
        help="Path to a short real video file. Enables tests marked @needs_real_media.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "needs_real_media: requires --real-media path to run"
    )


@pytest.fixture
def real_media(request) -> Path:
    val = request.config.getoption("--real-media")
    if not val:
        pytest.skip("--real-media not provided")
    p = Path(val)
    if not p.exists():
        pytest.skip(f"--real-media file does not exist: {p}")
    return p
