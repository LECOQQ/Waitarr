import pytest
import qbittorrentapi
from qbit_core import QbitConfig, QbitConnectionError

from waitarr.adapters import qbittorrent as adapter
from waitarr.adapters.qbittorrent import (
    READ_METHODS,
    QbittorrentTarget,
    ReadOnlyClient,
    WriteForbidden,
)
from waitarr.core.model import Limits, TargetState
from waitarr.core.ports import ServiceUnavailable

CONFIG = QbitConfig(host="http://qbit:8080", username="admin", password="pw")

# Every client method that changes qBittorrent. A read-only Waitarr must
# refuse each of them; none may ever appear in READ_METHODS.
WRITE_METHODS = (
    "app_set_preferences",
    "transfer_set_speed_limits_mode",
    "transfer_toggle_speed_limits_mode",
    "transfer_set_download_limit",
    "transfer_set_upload_limit",
    "torrents_pause",
    "torrents_stop",
    "torrents_resume",
    "torrents_start",
    "torrents_delete",
    "torrents_add",
    "torrents_set_download_limit",
    "torrents_set_upload_limit",
    "torrents_recheck",
    "app_shutdown",
    "auth_log_out",
)


class FakeQbit:
    """Stands in for a qbittorrent-api client; records every call."""

    def __init__(self, *, mode=False, alt_dl=0, alt_up=0, scheduler=False):
        self.mode = mode
        self.preferences = {
            "dl_limit": 0,
            "up_limit": 0,
            "alt_dl_limit": alt_dl,
            "alt_up_limit": alt_up,
            "scheduler_enabled": scheduler,
        }
        self.calls: list[str] = []
        self.error: Exception | None = None

    def _enter(self, name):
        self.calls.append(name)
        if self.error is not None:
            raise self.error

    def app_version(self):
        self._enter("app_version")
        return "v5.1.4"

    def app_web_api_version(self):
        self._enter("app_web_api_version")
        return "2.11.4"

    def app_preferences(self):
        self._enter("app_preferences")
        return dict(self.preferences)

    def transfer_speed_limits_mode(self):
        self._enter("transfer_speed_limits_mode")
        return "1" if self.mode else "0"

    def transfer_set_speed_limits_mode(self, intended_state=None):
        self._enter("transfer_set_speed_limits_mode")
        self.mode = bool(intended_state)

    def app_set_preferences(self, prefs=None):
        self._enter("app_set_preferences")
        self.preferences.update(prefs or {})

    @property
    def writes(self):
        return [c for c in self.calls if c in WRITE_METHODS]


def target(fake, *, read_only=False):
    return QbittorrentTarget(
        "main", CONFIG, read_only=read_only, connect=lambda c, t: fake
    )


HELD = TargetState(True, Limits(1024, 2048))


def test_read_only_client_forwards_every_read_method():
    fake = FakeQbit()
    client = ReadOnlyClient(fake)
    for name in sorted(READ_METHODS):
        if hasattr(fake, name):
            assert getattr(client, name) == getattr(fake, name)


def test_every_read_method_exists_on_the_real_client():
    for name in READ_METHODS:
        assert callable(getattr(qbittorrentapi.Client, name)), name


def test_no_known_write_method_is_in_the_read_list():
    assert READ_METHODS.isdisjoint(WRITE_METHODS)


@pytest.mark.parametrize("method", WRITE_METHODS)
def test_read_only_client_refuses_every_write_method(method):
    fake = FakeQbit()
    client = ReadOnlyClient(fake)
    with pytest.raises(WriteForbidden):
        getattr(client, method)
    assert fake.calls == []


def test_read_only_client_refuses_a_method_it_has_never_heard_of():
    with pytest.raises(WriteForbidden):
        _ = ReadOnlyClient(FakeQbit()).brand_new_write_method


def test_read_only_client_refuses_every_real_method_outside_the_read_list():
    # A method qbittorrent-api adds tomorrow is refused until listed.
    real = [
        name
        for name in dir(qbittorrentapi.Client)
        if not name.startswith("_")
        and callable(getattr(qbittorrentapi.Client, name, None))
        and name not in READ_METHODS
    ]
    assert real
    client = ReadOnlyClient(object())
    for name in real:
        with pytest.raises(WriteForbidden):
            getattr(client, name)


def test_a_read_only_target_reads_without_any_write():
    fake = FakeQbit(mode=True, alt_dl=500 * 1024, alt_up=600 * 1024)
    state = target(fake, read_only=True).read()
    assert state == TargetState(True, Limits(500 * 1024, 600 * 1024))
    assert set(fake.calls) <= READ_METHODS


def test_a_read_only_target_reports_its_version_and_diagnostics():
    fake = FakeQbit(scheduler=True)
    qbit = target(fake, read_only=True)
    version = qbit.version()
    assert (version.version, version.api_version) == ("v5.1.4", "2.11.4")
    assert any("scheduler" in w for w in qbit.diagnose())
    assert set(fake.calls) <= READ_METHODS


def test_apply_in_read_only_mode_raises_write_forbidden_before_any_call():
    fake = FakeQbit()
    with pytest.raises(WriteForbidden):
        target(fake, read_only=True).apply(HELD)
    assert fake.calls == []


def test_apply_writes_limits_and_mode_when_both_differ():
    fake = FakeQbit()
    target(fake).apply(HELD)
    assert fake.mode is True
    assert (
        fake.preferences["alt_dl_limit"],
        fake.preferences["alt_up_limit"],
    ) == (
        1024,
        2048,
    )


def test_apply_leaves_the_limits_alone_when_they_already_match():
    fake = FakeQbit(alt_dl=1024, alt_up=2048)
    target(fake).apply(HELD)
    assert fake.mode is True
    assert "app_set_preferences" not in fake.calls


def test_apply_writes_nothing_when_the_target_is_already_in_that_state():
    fake = FakeQbit(mode=True, alt_dl=1024, alt_up=2048)
    target(fake).apply(HELD)
    assert fake.writes == []


def test_apply_changes_only_the_mode_to_restore_the_state_found_before():
    fake = FakeQbit(mode=True, alt_dl=500 * 1024, alt_up=500 * 1024)
    target(fake).apply(TargetState(False, Limits(500 * 1024, 500 * 1024)))
    assert fake.mode is False
    assert fake.writes == ["transfer_set_speed_limits_mode"]


def test_a_qbittorrent_api_error_becomes_service_unavailable():
    fake = FakeQbit()
    fake.error = qbittorrentapi.APIConnectionError("connection refused")
    with pytest.raises(ServiceUnavailable) as caught:
        target(fake).read()
    assert "APIConnectionError" in str(caught.value)


def test_an_api_error_forces_a_reconnect_on_the_next_call():
    connections = []

    def connect(config, timeout):
        connections.append(1)
        return fake

    fake = FakeQbit()
    qbit = QbittorrentTarget("main", CONFIG, read_only=False, connect=connect)
    qbit.read()
    fake.error = qbittorrentapi.Forbidden403Error("session expired")
    with pytest.raises(ServiceUnavailable):
        qbit.read()
    fake.error = None
    qbit.read()
    assert len(connections) == 2


def test_a_failed_connection_is_service_unavailable():
    def connect(config, timeout):
        raise QbitConnectionError("Unable to connect to qBittorrent")

    qbit = QbittorrentTarget("main", CONFIG, read_only=False, connect=connect)
    with pytest.raises(ServiceUnavailable):
        qbit.read()


def test_an_unrelated_bug_is_not_swallowed():
    fake = FakeQbit()
    fake.error = KeyError("bug")
    with pytest.raises(KeyError):
        target(fake).read()


def test_the_default_connection_uses_qbit_core(monkeypatch):
    seen = {}

    def create(config, *, request_timeout):
        seen["args"] = (config, request_timeout)
        return FakeQbit()

    monkeypatch.setattr(adapter, "create_qbit_client", create)
    QbittorrentTarget("main", CONFIG, read_only=True, timeout=3.0).read()
    assert seen["args"] == (CONFIG, 3.0)
