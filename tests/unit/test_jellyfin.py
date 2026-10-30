import json
import urllib.request

import pytest

from tests.fake_jellyfin import FakeJellyfin, session
from waitarr.adapters.jellyfin import (
    LIBRARY_REFRESH_SECONDS,
    JellyfinSource,
    JellyfinTasks,
)
from waitarr.core.model import TaskState
from waitarr.core.ports import ServiceUnavailable, WriteRefused

KEY = "UNMISTAKABLE-JELLYFIN-KEY"


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
        source(jellyfin, key="UNMISTAKABLE-WRONG-KEY").playbacks()
    assert "UNMISTAKABLE-WRONG-KEY" not in str(caught.value)
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


LIBRARIES = {
    "movies": ["/media/movies"],
    "Animes": ["/media/movies/animes", "/media/extra/animes/"],
    "Musiques": ["/media/music"],
}


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def folder_reads(fake):
    return [p for p, _ in fake.requests if p == "/Library/VirtualFolders"]


def test_an_item_belongs_to_every_library_whose_folder_holds_it(jellyfin):
    jellyfin.libraries = LIBRARIES
    jellyfin.sessions = [
        session("a", path="/media/movies/animes/akira.mkv"),
        session("b", path="/media/extra/animes/x.mkv"),
        session("c", path="/media/music/album/01.flac"),
        session("d", path="/media/movies-old/dune.mkv"),
        session("e"),
    ]
    assert [p.libraries for p in source(jellyfin).playbacks()] == [
        ("movies", "Animes"),
        ("Animes",),
        ("Musiques",),
        (),
        (),
    ]


def test_library_folders_are_read_once_then_refreshed_rarely(jellyfin):
    jellyfin.libraries = LIBRARIES
    jellyfin.sessions = [session(path="/media/music/a.flac")]
    clock = Clock()
    reader = source(jellyfin, monotonic=clock)
    for _ in range(5):
        reader.playbacks()
    assert len(folder_reads(jellyfin)) == 1
    clock.now = LIBRARY_REFRESH_SECONDS
    reader.playbacks()
    assert len(folder_reads(jellyfin)) == 2


def test_library_folders_are_not_read_while_nothing_plays(jellyfin):
    jellyfin.libraries = LIBRARIES
    jellyfin.sessions = [session(title=None)]
    source(jellyfin).playbacks()
    assert folder_reads(jellyfin) == []


def test_a_failed_folder_read_keeps_the_playback_and_retries(jellyfin):
    jellyfin.libraries = LIBRARIES
    jellyfin.sessions = [session(path="/media/music/a.flac")]
    reader = source(jellyfin)
    original = reader._get

    def flaky(path):
        if path == "/Library/VirtualFolders":
            raise ServiceUnavailable("down")
        return original(path)

    reader._get = flaky
    (playback,) = reader.playbacks()
    assert playback.libraries == ()
    reader._get = original
    (playback,) = reader.playbacks()
    assert playback.libraries == ("Musiques",)


def tasks_host(fake, key=KEY, *, read_only=False):
    return JellyfinTasks(
        "jellyfin", fake.url, key, read_only=read_only, timeout=2
    )


def task(host, key="RefreshLibrary"):
    return next(t for t in host.tasks() if t.key == key)


def test_the_scheduled_tasks_are_read_by_key_with_their_last_execution(
    jellyfin,
):
    jellyfin.run_task("RefreshLibrary", progress=42.5)
    host = tasks_host(jellyfin)
    assert [t.key for t in host.tasks()] == list(jellyfin.tasks)
    running = task(host)
    assert running.state is TaskState.RUNNING
    assert running.progress == 42.5
    assert running.name == "Task RefreshLibrary"
    assert running.id == jellyfin.tasks["RefreshLibrary"].id
    assert running.last is not None
    assert running.last.status == "Completed"
    assert running.last.start == jellyfin.tasks["RefreshLibrary"].last[0]
    idle = task(host, "RefreshChapterImages")
    assert (idle.state, idle.progress) == (TaskState.IDLE, None)


def test_a_task_that_never_ran_has_no_last_execution(jellyfin):
    jellyfin.tasks["RefreshLibrary"].last = None
    assert task(tasks_host(jellyfin)).last is None


def test_the_task_routes_send_the_api_key_as_a_media_browser_token(jellyfin):
    tasks_host(jellyfin).tasks()
    assert ("/ScheduledTasks", KEY) in jellyfin.requests


def test_a_stop_cancels_a_running_task_which_is_cancelling_then_idle(
    jellyfin,
):
    jellyfin.run_task("RefreshLibrary")
    started = jellyfin.tasks["RefreshLibrary"].current
    host = tasks_host(jellyfin)
    task_id = task(host).id
    host.stop(task_id)
    assert jellyfin.writes == [("DELETE", f"/ScheduledTasks/Running/{task_id}")]
    cancelling = task(host)
    # Jellyfin keeps the previous execution as the last until the first idle.
    assert cancelling.state is TaskState.CANCELLING
    assert cancelling.last is not None and cancelling.last.start != started
    idle = task(host)
    assert idle.state is TaskState.IDLE
    assert idle.last is not None
    assert (idle.last.start, idle.last.status) == (started, "Cancelled")


def test_a_stop_on_a_task_at_rest_is_not_an_error(jellyfin):
    host = tasks_host(jellyfin)
    host.stop(task(host).id)  # Jellyfin answers 500, the host reads again
    assert [m for m, _ in jellyfin.writes] == ["DELETE"]
    assert task(host).state is TaskState.IDLE


def test_a_stop_refused_by_a_task_still_running_is_service_unavailable(
    jellyfin,
):
    jellyfin.run_task("RefreshLibrary")
    jellyfin.stop_fails = True
    host = tasks_host(jellyfin)
    with pytest.raises(ServiceUnavailable) as caught:
        host.stop(task(host).id)
    assert "500" in str(caught.value)
    assert KEY not in str(caught.value)


def test_a_stop_on_an_unknown_task_is_service_unavailable(jellyfin):
    with pytest.raises(ServiceUnavailable) as caught:
        tasks_host(jellyfin).stop("0" * 32)
    assert "404" in str(caught.value)
    assert KEY not in str(caught.value)


def test_a_start_on_an_unknown_task_is_service_unavailable(jellyfin):
    with pytest.raises(ServiceUnavailable) as caught:
        tasks_host(jellyfin).start("0" * 32)
    assert "404" in str(caught.value)


def test_a_start_runs_a_task_from_zero_keeping_the_old_last_execution(
    jellyfin,
):
    host = tasks_host(jellyfin)
    before = task(host)
    host.start(before.id)
    after = task(host)
    assert after.state is TaskState.RUNNING
    assert after.progress == 0.0
    assert after.last == before.last  # until it ends


def test_a_start_on_a_running_task_is_ignored(jellyfin):
    jellyfin.run_task("RefreshLibrary", progress=60.0)
    current = jellyfin.tasks["RefreshLibrary"].current
    host = tasks_host(jellyfin)
    host.start(task(host).id)
    assert jellyfin.tasks["RefreshLibrary"].progress == 60.0
    assert jellyfin.tasks["RefreshLibrary"].current == current


def test_a_refused_key_on_a_task_route_is_never_echoed(jellyfin):
    host = tasks_host(jellyfin, key="UNMISTAKABLE-WRONG-KEY")
    for call in (host.tasks, lambda: host.stop("x"), lambda: host.start("x")):
        with pytest.raises(ServiceUnavailable) as caught:
            call()
        assert "UNMISTAKABLE-WRONG-KEY" not in str(caught.value)
        assert KEY not in str(caught.value)
        assert "401" in str(caught.value)


def test_a_forbidden_task_list_is_service_unavailable_without_the_key(
    jellyfin,
):
    jellyfin.tasks_forbidden = True
    with pytest.raises(ServiceUnavailable) as caught:
        tasks_host(jellyfin).tasks()
    assert "403" in str(caught.value)
    assert KEY not in str(caught.value)


@pytest.mark.parametrize(
    "raw",
    [
        {"not": "a list"},
        ["not a mapping"],
        [{"Id": "a", "State": "Idle"}],
        [{"Key": "K", "State": "Idle"}],
        [{"Key": "K", "Id": "a", "State": "Aborting"}],
        [{"Key": "K", "Id": "a", "State": "Idle", "LastExecutionResult": {}}],
    ],
)
def test_an_unreadable_task_list_is_service_unavailable(jellyfin, raw):
    jellyfin.raw_tasks = raw
    with pytest.raises(ServiceUnavailable):
        tasks_host(jellyfin).tasks()


def test_a_stopped_server_is_service_unavailable_for_the_tasks_too():
    fake = FakeJellyfin(KEY).start()
    host = tasks_host(fake)
    fake.stop()
    with pytest.raises(ServiceUnavailable) as caught:
        host.tasks()
    assert KEY not in str(caught.value)


def no_request(*args, **kwargs):
    raise AssertionError("a read-only host sent a request")


def test_a_read_only_host_refuses_to_stop_before_sending_anything(jellyfin):
    jellyfin.run_task("RefreshLibrary")
    host = tasks_host(jellyfin, read_only=True)
    task_id = task(host).id
    seen = len(jellyfin.requests)
    host._request = no_request  # the refusal comes first, not the wire's
    with pytest.raises(WriteRefused):
        host.stop(task_id)
    assert len(jellyfin.requests) == seen
    assert jellyfin.writes == []
    assert jellyfin.tasks["RefreshLibrary"].state == "Running"


def test_a_read_only_host_refuses_to_start_before_sending_anything(jellyfin):
    host = tasks_host(jellyfin, read_only=True)
    task_id = task(host).id
    seen = len(jellyfin.requests)
    host._request = no_request
    with pytest.raises(WriteRefused):
        host.start(task_id)
    assert len(jellyfin.requests) == seen
    assert jellyfin.writes == []
    assert jellyfin.tasks["RefreshLibrary"].state == "Idle"


@pytest.mark.parametrize("method", ["DELETE", "POST", "PUT", "PATCH"])
def test_a_read_only_client_refuses_every_method_but_get_at_the_wire(
    jellyfin, method
):
    for client in (
        tasks_host(jellyfin, read_only=True),
        source(jellyfin),  # a source never writes either
    ):
        seen = len(jellyfin.requests)
        with pytest.raises(WriteRefused):
            client._request(method, "/ScheduledTasks/Running/anything")
        assert len(jellyfin.requests) == seen
    assert jellyfin.writes == []


def test_a_read_only_host_still_reads(jellyfin):
    assert [t.key for t in tasks_host(jellyfin, read_only=True).tasks()] == [
        "RefreshLibrary",
        "TaskExtractMediaSegments",
        "RefreshChapterImages",
        "RefreshTrickplayImages",
    ]
