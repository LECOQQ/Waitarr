from datetime import timedelta
from pathlib import Path

import pytest

from waitarr.config import ConfigError, Mode, load_config
from waitarr.core.model import Limits

EXAMPLE = Path(__file__).parents[2] / "config" / "waitarr.example.toml"

MINIMAL = """
[[sources]]
name = "jellyfin"
type = "jellyfin"
url = "http://jellyfin:8096"

[[targets]]
name = "main"
type = "qbittorrent"
url = "http://qbittorrent:8080"
username = "admin"
"""

SECRETS = {
    "WAITARR_JELLYFIN_API_KEY": "jf-key",
    "WAITARR_MAIN_PASSWORD": "qb-pass",
}


def load(tmp_path, text=MINIMAL, environ=None):
    path = tmp_path / "waitarr.toml"
    path.write_text(text, encoding="utf-8")
    return load_config(path, {**SECRETS, **(environ or {})})


def problems(tmp_path, text=MINIMAL, environ=None, secrets=True):
    path = tmp_path / "waitarr.toml"
    path.write_text(text, encoding="utf-8")
    env = {**(SECRETS if secrets else {}), **(environ or {})}
    with pytest.raises(ConfigError) as caught:
        load_config(path, env)
    return caught.value.problems


def mentions(found, *needles):
    return any(all(n in p for n in needles) for p in found)


def test_minimal_file_loads_with_safe_defaults(tmp_path):
    config = load(tmp_path)
    assert config.mode is Mode.OBSERVE
    assert config.poll_interval == timedelta(seconds=15)
    assert config.policy.release_after == timedelta(minutes=3)
    assert config.restore_on_exit is True
    assert config.targets[0].throttle is None
    assert config.sources[0].url == "http://jellyfin:8096"


def test_secrets_come_from_the_environment(tmp_path):
    config = load(tmp_path)
    assert config.sources[0].api_key == "jf-key"
    assert config.targets[0].password == "qb-pass"


def test_secrets_can_come_from_a_file_named_by_the_environment(tmp_path):
    key = tmp_path / "key"
    key.write_text("from-file\n", encoding="utf-8")
    path = tmp_path / "waitarr.toml"
    path.write_text(MINIMAL, encoding="utf-8")
    config = load_config(
        path,
        {
            "WAITARR_JELLYFIN_API_KEY_FILE": str(key),
            "WAITARR_MAIN_PASSWORD": "qb-pass",
        },
    )
    assert config.sources[0].api_key == "from-file"


def test_a_password_file_named_in_the_config_is_read(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("  file-pass \n", encoding="utf-8")
    text = MINIMAL.replace(
        'username = "admin"',
        f'username = "admin"\npassword_file = "{secret}"',
    )
    config = load(tmp_path, text, {"WAITARR_MAIN_PASSWORD": ""})
    assert config.targets[0].password == "file-pass"


def test_the_environment_wins_over_a_secrets_file(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("file-pass", encoding="utf-8")
    text = MINIMAL.replace(
        'username = "admin"',
        f'username = "admin"\npassword_file = "{secret}"',
    )
    assert load(tmp_path, text).targets[0].password == "qb-pass"


def test_an_unreadable_secrets_file_is_reported(tmp_path):
    found = problems(
        tmp_path,
        environ={"WAITARR_JELLYFIN_API_KEY_FILE": str(tmp_path / "nope")},
        secrets=False,
    )
    assert mentions(found, "WAITARR_JELLYFIN_API_KEY", "cannot read")


def test_an_empty_secrets_file_is_reported(tmp_path):
    empty = tmp_path / "empty"
    empty.write_text("\n", encoding="utf-8")
    found = problems(
        tmp_path,
        environ={
            "WAITARR_JELLYFIN_API_KEY_FILE": str(empty),
            "WAITARR_MAIN_PASSWORD": "x",
        },
        secrets=False,
    )
    assert mentions(found, "WAITARR_JELLYFIN_API_KEY", "empty")


def test_a_missing_secret_names_the_variable_to_set(tmp_path):
    found = problems(tmp_path, secrets=False)
    assert mentions(found, "WAITARR_JELLYFIN_API_KEY")
    assert mentions(found, "WAITARR_MAIN_PASSWORD")


@pytest.mark.parametrize(
    ("section", "line", "key"),
    [
        ("sources", 'api_key = "hunter2"', "api_key"),
        ("targets", 'password = "hunter2"', "password"),
    ],
)
def test_a_secret_written_in_the_file_is_refused(tmp_path, section, line, key):
    marker = f"[[{section}]]\n"
    text = MINIMAL.replace(marker, marker + line + "\n")
    found = problems(tmp_path, text)
    assert mentions(found, f"'{key}'", "must not be written")


def test_the_refusal_never_echoes_the_secret(tmp_path):
    text = MINIMAL.replace(
        "[[targets]]\n", '[[targets]]\npassword = "hunter2"\n'
    )
    assert not any("hunter2" in p for p in problems(tmp_path, text))


def test_unknown_keys_are_refused(tmp_path):
    found = problems(tmp_path, 'colour = "blue"\n' + MINIMAL)
    assert mentions(found, "unknown key 'colour'")


def test_unknown_keys_in_an_entry_are_refused(tmp_path):
    text = MINIMAL.replace('username = "admin"', 'username = "admin"\nfoo = 1')
    assert mentions(problems(tmp_path, text), "target 'main'", "'foo'")


@pytest.mark.parametrize("name", ["Main", "has space", "", "-lead", "x" * 33])
def test_invalid_names_are_refused(tmp_path, name):
    text = MINIMAL.replace('name = "main"', f'name = "{name}"')
    assert mentions(problems(tmp_path, text), "'name' is required")


def test_a_name_cannot_be_used_twice_across_sources_and_targets(tmp_path):
    text = MINIMAL.replace('name = "main"', 'name = "jellyfin"')
    assert mentions(problems(tmp_path, text), "already used")


def test_a_target_name_with_a_dash_maps_to_an_underscore_variable(tmp_path):
    text = MINIMAL.replace('name = "main"', 'name = "seed-box"')
    config = load(tmp_path, text, {"WAITARR_SEED_BOX_PASSWORD": "dash-pass"})
    assert config.targets[0].password == "dash-pass"


def test_an_unknown_type_is_refused(tmp_path):
    text = MINIMAL.replace('type = "jellyfin"', 'type = "plex"')
    assert mentions(problems(tmp_path, text), "'type' must be one of")


def test_at_least_one_source_and_one_target_are_required(tmp_path):
    found = problems(tmp_path, 'mode = "observe"\n')
    assert mentions(found, "[[sources]]")
    assert mentions(found, "[[targets]]")


@pytest.mark.parametrize("value", ["0", "0KiB", "0B"])
def test_zero_is_refused_as_a_throttle_limit(tmp_path, value):
    text = f'[throttle]\ndownload = "{value}"\nupload = "1KiB"\n' + MINIMAL
    assert mentions(
        problems(tmp_path, text), "[throttle].download", "unlimited"
    )


def test_both_throttle_directions_must_be_set(tmp_path):
    text = '[throttle]\ndownload = "1KiB"\n' + MINIMAL
    assert mentions(problems(tmp_path, text), "both 'download' and 'upload'")


def test_throttle_limits_apply_to_every_target_unless_overridden(tmp_path):
    text = '[throttle]\ndownload = "1KiB"\nupload = "2KiB"\n' + MINIMAL + """
[[targets]]
name = "second"
type = "qbittorrent"
url = "http://qbittorrent-2:8080"
username = "admin"
throttle = { download = "10KiB", upload = "20KiB" }
"""
    config = load(tmp_path, text, {"WAITARR_SECOND_PASSWORD": "p"})
    assert [t.throttle for t in config.targets] == [
        Limits(1024, 2048),
        Limits(10 * 1024, 20 * 1024),
    ]


def test_environment_overrides_mode_and_poll_interval(tmp_path):
    config = load(
        tmp_path,
        environ={"WAITARR_MODE": "active", "WAITARR_POLL_INTERVAL": "30s"},
    )
    assert config.mode is Mode.ACTIVE
    assert config.poll_interval == timedelta(seconds=30)


def test_environment_overrides_beat_the_file(tmp_path):
    text = 'mode = "observe"\npoll_interval = "5s"\n' + MINIMAL
    config = load(
        tmp_path,
        text,
        {"WAITARR_MODE": "active", "WAITARR_POLL_INTERVAL": "1m"},
    )
    assert (config.mode, config.poll_interval) == (
        Mode.ACTIVE,
        timedelta(minutes=1),
    )


def test_environment_throttle_limits_override_the_file(tmp_path):
    text = '[throttle]\ndownload = "1KiB"\nupload = "1KiB"\n' + MINIMAL
    config = load(
        tmp_path,
        text,
        {
            "WAITARR_THROTTLE_DOWNLOAD": "5KiB",
            "WAITARR_THROTTLE_UPLOAD": "6KiB",
        },
    )
    assert config.targets[0].throttle == Limits(5 * 1024, 6 * 1024)


def test_environment_throttle_limits_work_without_a_throttle_table(tmp_path):
    config = load(
        tmp_path,
        environ={
            "WAITARR_THROTTLE_DOWNLOAD": "2KiB",
            "WAITARR_THROTTLE_UPLOAD": "3KiB",
        },
    )
    assert config.targets[0].throttle == Limits(2048, 3072)


def test_http_listen_can_be_overridden_and_disabled(tmp_path):
    config = load(tmp_path, environ={"WAITARR_HTTP_LISTEN": "127.0.0.1:9000"})
    assert (config.http.host, config.http.port) == ("127.0.0.1", 9000)
    text = '[http]\nlisten = ""\n' + MINIMAL
    assert load(tmp_path, text).http.port is None


def test_a_malformed_listen_address_is_refused(tmp_path):
    found = problems(tmp_path, environ={"WAITARR_HTTP_LISTEN": "nope"})
    assert mentions(found, "http.listen")


def test_the_webhook_needs_a_listening_server(tmp_path):
    text = '[http]\nlisten = ""\nwebhook = true\n' + MINIMAL
    assert mentions(problems(tmp_path, text), "webhook needs")


def test_invalid_mode_and_poll_interval_are_refused(tmp_path):
    found = problems(
        tmp_path,
        environ={"WAITARR_MODE": "yolo", "WAITARR_POLL_INTERVAL": "0s"},
    )
    assert mentions(found, "mode")
    assert mentions(found, "poll_interval")


def test_several_problems_are_reported_together(tmp_path):
    text = (
        'colour = "blue"\n'
        '[throttle]\ndownload = "0"\nupload = "1KiB"\n'
        + MINIMAL.replace('url = "http://jellyfin:8096"', 'url = "ftp://x"')
    )
    found = problems(tmp_path, text, secrets=False)
    assert len(found) >= 5
    assert mentions(found, "colour")
    assert mentions(found, "[throttle].download")
    assert mentions(found, "source 'jellyfin'.url")
    assert mentions(found, "WAITARR_JELLYFIN_API_KEY")
    assert mentions(found, "WAITARR_MAIN_PASSWORD")


def test_a_missing_file_says_where_to_find_the_example(tmp_path):
    with pytest.raises(ConfigError) as caught:
        load_config(tmp_path / "absent.toml", {})
    assert "waitarr.example.toml" in caught.value.problems[0]


def test_invalid_toml_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load(tmp_path, "this is = = not toml")


def test_the_config_path_can_come_from_the_environment(tmp_path):
    path = tmp_path / "elsewhere.toml"
    path.write_text(MINIMAL, encoding="utf-8")
    config = load_config(None, {**SECRETS, "WAITARR_CONFIG": str(path)})
    assert config.path == path


def test_the_example_file_loads_with_secrets_from_the_environment():
    config = load_config(EXAMPLE, SECRETS)
    assert config.mode is Mode.OBSERVE
    assert [s.name for s in config.sources] == ["jellyfin"]
    assert [t.name for t in config.targets] == ["main"]
    assert config.targets[0].throttle == Limits(1024, 1024)


def test_the_example_file_does_not_load_without_its_secrets():
    with pytest.raises(ConfigError):
        load_config(EXAMPLE, {})


def test_secrets_stay_out_of_the_repr(tmp_path):
    config = load(tmp_path)
    shown = repr(config)
    assert "jf-key" not in shown
    assert "qb-pass" not in shown
