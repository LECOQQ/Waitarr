import pytest

from waitarr.bootstrap import build_engine
from waitarr.config import DEFAULT_TASKS, Mode, load_config
from waitarr.core.ports import ServiceUnavailable, WriteRefused

CONFIG = """
mode = "{mode}"

[[sources]]
name = "jellyfin"
type = "jellyfin"
url = "http://127.0.0.1:1"
{extra}

[[targets]]
name = "main"
type = "qbittorrent"
url = "http://127.0.0.1:1"
username = "admin"
"""

SECRETS = {"WAITARR_JELLYFIN_API_KEY": "k", "WAITARR_MAIN_PASSWORD": "p"}


def engine(tmp_path, mode="observe", extra="", **kwargs):
    path = tmp_path / "waitarr.toml"
    path.write_text(CONFIG.format(mode=mode, extra=extra), encoding="utf-8")
    config = load_config(path, SECRETS)
    return build_engine(config, **kwargs)


def test_each_jellyfin_source_hosts_its_tasks(tmp_path):
    (binding,) = engine(
        tmp_path, extra='tasks = ["RefreshLibrary"]\nsuspend_tasks = false'
    ).task_bindings
    assert binding.host.name == "jellyfin"
    assert binding.keys == ("RefreshLibrary",)
    assert binding.suspend is False


def test_the_default_bindings_hold_the_four_default_tasks(tmp_path):
    (binding,) = engine(tmp_path).task_bindings
    assert binding.keys == DEFAULT_TASKS
    assert binding.suspend is True


@pytest.mark.parametrize("mode", [Mode.OBSERVE.value, Mode.ACTIVE.value])
def test_the_task_host_is_read_only_exactly_in_observation(tmp_path, mode):
    (binding,) = engine(tmp_path, mode=mode).task_bindings
    if mode == Mode.OBSERVE:
        with pytest.raises(WriteRefused):
            binding.host.stop("an-id")
        with pytest.raises(WriteRefused):
            binding.host.start("an-id")
    else:
        # Writable: it gets as far as the (closed) port instead of refusing.
        with pytest.raises(ServiceUnavailable):
            binding.host.stop("an-id")


def test_a_simulation_forced_over_an_active_config_is_read_only(tmp_path):
    (binding,) = engine(tmp_path, mode="active", simulate=True).task_bindings
    with pytest.raises(WriteRefused):
        binding.host.start("an-id")
