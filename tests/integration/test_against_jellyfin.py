"""Read-only checks against a real Jellyfin, never run in CI.

Point them at a server with an administrator API key:

    WAITARR_LIVE_JELLYFIN_URL=http://jellyfin:8096 \\
    WAITARR_LIVE_JELLYFIN_API_KEY_FILE=/path/to/key make test-live

Only GET requests are sent. Every test is skipped without the URL.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from waitarr.adapters.jellyfin import JellyfinSource

pytestmark = pytest.mark.live

URL = os.environ.get("WAITARR_LIVE_JELLYFIN_URL", "")


def _key() -> str:
    if os.environ.get("WAITARR_LIVE_JELLYFIN_API_KEY"):
        return os.environ["WAITARR_LIVE_JELLYFIN_API_KEY"]
    path = os.environ.get("WAITARR_LIVE_JELLYFIN_API_KEY_FILE")
    return Path(path).read_text(encoding="utf-8").strip() if path else ""


@pytest.fixture
def jellyfin() -> JellyfinSource:
    if not URL:
        pytest.skip("WAITARR_LIVE_JELLYFIN_URL is not set")
    return JellyfinSource("live", URL, _key(), timeout=10)


def test_the_server_answers_and_sessions_read(jellyfin):
    assert jellyfin.version().version
    jellyfin.playbacks()


def test_every_library_folder_maps_a_file_inside_it_to_that_library(
    jellyfin,
):
    jellyfin._refresh_folders()
    folders = jellyfin._folders
    assert folders, "no library read from /Library/VirtualFolders"
    for name, locations in folders:
        for location in locations:
            libraries = jellyfin._libraries_of(f"{location}/probe.mkv")
            assert name in libraries, (name, location, libraries)
