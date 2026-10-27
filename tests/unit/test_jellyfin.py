import json
import urllib.request

import pytest

from tests.fake_jellyfin import FakeJellyfin, session
from waitarr.adapters.jellyfin import JellyfinSource
from waitarr.core.ports import ServiceUnavailable

KEY = "super-secret-key-123"


@pytest.fixture
def jellyfin():
    with FakeJellyfin(KEY) as fake:
        yield fake


def source(fake, key=KEY, **kwargs):
    return JellyfinSource("jellyfin", fake.url, key, timeout=2, **kwargs)


def test_a_reading_session_is_a_playback(jellyfin):
    jellyfin.sessions = [
        session("a", user="alice", device="TV", client="Android TV")
    ]
    (playback,) = source(jellyfin).playbacks()
    assert (playback.source, playback.session_id) == ("jellyfin", "a")
    assert (playback.user, playback.device, playback.client) == (
        "alice",
        "TV",
        "Android TV",
    )
    assert (playback.title, playback.media_type) == ("Dune", "Movie")
    assert playback.paused is False


def test_a_paused_session_is_reported_as_paused(jellyfin):
    jellyfin.sessions = [session(paused=True)]
    (playback,) = source(jellyfin).playbacks()
    assert playback.paused is True


def test_sessions_without_a_now_playing_item_are_ignored(jellyfin):
    jellyfin.sessions = [session("idle", title=None), session("busy")]
    assert [p.session_id for p in source(jellyfin).playbacks()] == ["busy"]


def test_an_episode_title_names_series_season_and_episode(jellyfin):
    jellyfin.sessions = [
        session(
            title="Pilot",
            item_type="Episode",
            series="Severance",
            season=1,
            episode=2,
        )
    ]
    (playback,) = source(jellyfin).playbacks()
    assert playback.title == "Severance S01E02 Pilot"
    assert playback.media_type == "Episode"


def test_an_episode_without_numbers_falls_back_to_series_and_name(jellyfin):
    jellyfin.sessions = [
        session(title="Special", item_type="Episode", series="Severance")
    ]
    (playback,) = source(jellyfin).playbacks()
    assert playback.title == "Severance - Special"


def test_the_media_path_is_kept_when_the_server_exposes_it(jellyfin):
    jellyfin.sessions = [session(path="/media/movies/dune.mkv")]
    (playback,) = source(jellyfin).playbacks()
    assert playback.media_path == "/media/movies/dune.mkv"


def test_no_session_at_all_is_no_playback(jellyfin):
    assert list(source(jellyfin).playbacks()) == []


def test_the_version_is_read_without_authentication(jellyfin):
    version = source(jellyfin, key="wrong").version()
    assert version.version == "12.2.0"
    assert version.product == "Jellyfin Server"


def test_the_api_key_is_sent_as_a_media_browser_token(jellyfin):
    source(jellyfin).playbacks()
    assert ("/Sessions", KEY) in jellyfin.requests


def test_a_refused_key_is_service_unavailable_and_never_echoed(jellyfin):
    with pytest.raises(ServiceUnavailable) as caught:
        source(jellyfin, key="wrong-key-456").playbacks()
    assert "wrong-key-456" not in str(caught.value)
    assert KEY not in str(caught.value)
    assert "401" in str(caught.value)


def test_an_error_page_is_service_unavailable_without_the_key(jellyfin):
    jellyfin.failing = True
    with pytest.raises(ServiceUnavailable) as caught:
        source(jellyfin).playbacks()
    assert KEY not in str(caught.value)
    assert "500" in str(caught.value)


def test_a_stopped_server_is_service_unavailable_without_the_key():
    fake = FakeJellyfin(KEY).start()
    reader = source(fake)
    fake.stop()
    with pytest.raises(ServiceUnavailable) as caught:
        reader.playbacks()
    assert KEY not in str(caught.value)


def test_a_non_json_answer_is_service_unavailable(jellyfin):
    jellyfin.sessions = []
    original = jellyfin._reply

    def html(handler, code, body):
        payload = b"<html>proxy login</html>"
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)

    jellyfin._reply = html
    try:
        with pytest.raises(ServiceUnavailable):
            source(jellyfin).playbacks()
    finally:
        jellyfin._reply = original


def test_the_standalone_control_route_programs_the_sessions(jellyfin):
    body = json.dumps([session("remote")]).encode()
    request = urllib.request.Request(
        jellyfin.url + "/__test__/sessions", data=body, method="POST"
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        assert response.status == 204
    assert [p.session_id for p in source(jellyfin).playbacks()] == ["remote"]
