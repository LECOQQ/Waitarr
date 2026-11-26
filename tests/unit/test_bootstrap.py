from dataclasses import replace

import pytest

from waitarr.bootstrap import (
    POLICY_FACTORIES,
    SOURCE_FACTORIES,
    TARGET_FACTORIES,
    TASK_HOST_FACTORIES,
    build_engine,
    build_policy,
)
from waitarr.compatibility import MATRIX
from waitarr.config import (
    DEFAULT_TASKS,
    POLICY_STRATEGIES,
    SOURCE_TYPES,
    TARGET_TYPES,
    Mode,
    load_config,
)
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


def test_the_four_type_catalogues_name_the_same_types():
    # Adding a type to one catalogue and forgetting another is otherwise a
    # KeyError at startup, or a service with no compatibility row.
    assert set(SOURCE_TYPES) == set(SOURCE_FACTORIES)
    assert set(TARGET_TYPES) == set(TARGET_FACTORIES)
    assert set(TASK_HOST_FACTORIES) <= set(SOURCE_FACTORIES)
    assert set(MATRIX) == set(SOURCE_FACTORIES) | set(TARGET_FACTORIES)
    assert set(POLICY_STRATEGIES) == set(POLICY_FACTORIES)


def test_the_configured_strategy_picks_the_policy(tmp_path, monkeypatch):
    chosen = object()
    monkeypatch.setitem(POLICY_FACTORIES, "other", lambda config: chosen)
    path = tmp_path / "waitarr.toml"
    path.write_text(CONFIG.format(mode="observe", extra=""), encoding="utf-8")
    config = load_config(path, SECRETS)
    assert build_policy(config) is not chosen
    other = replace(config, policy=replace(config.policy, strategy="other"))
    assert build_policy(other) is chosen


def test_a_simulation_forced_over_an_active_config_is_read_only(tmp_path):
    (binding,) = engine(tmp_path, mode="active", simulate=True).task_bindings
    with pytest.raises(WriteRefused):
        binding.host.start("an-id")
