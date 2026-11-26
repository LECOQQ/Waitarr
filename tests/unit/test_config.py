import re
from datetime import timedelta
from pathlib import Path

import pytest

from waitarr.config import DEFAULT_TASKS, ConfigError, Mode, load_config
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
    "WAITARR_JELLYFIN_API_KEY": "UNMISTAKABLE-JF-KEY",
    "WAITARR_MAIN_PASSWORD": "UNMISTAKABLE-QB-PASS",
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
    assert config.mode is Mode.ACTIVE
    assert config.poll_interval == timedelta(seconds=15)
    assert config.policy.release_after == timedelta(minutes=3)
    assert config.restore_on_exit is True
    assert config.targets[0].throttle is None
    assert config.sources[0].url == "http://jellyfin:8096"


def test_secrets_come_from_the_environment(tmp_path):
    config = load(tmp_path)
    assert config.sources[0].api_key == "UNMISTAKABLE-JF-KEY"
    assert config.targets[0].password == "UNMISTAKABLE-QB-PASS"


def test_secrets_can_come_from_a_file_named_by_the_environment(tmp_path):
    key = tmp_path / "key"
    key.write_text("from-file\n", encoding="utf-8")
    path = tmp_path / "waitarr.toml"
    path.write_text(MINIMAL, encoding="utf-8")
    config = load_config(
        path,
        {
            "WAITARR_JELLYFIN_API_KEY_FILE": str(key),
            "WAITARR_MAIN_PASSWORD": "UNMISTAKABLE-QB-PASS",
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
    assert load(tmp_path, text).targets[0].password == "UNMISTAKABLE-QB-PASS"


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
    assert config.mode is Mode.ACTIVE
    assert [s.name for s in config.sources] == ["jellyfin"]
    assert [t.name for t in config.targets] == ["main"]
    assert config.targets[0].throttle == Limits(1024, 1024)


def test_the_example_file_does_not_load_without_its_secrets():
    with pytest.raises(ConfigError):
        load_config(EXAMPLE, {})


def test_secrets_stay_out_of_the_repr(tmp_path):
    config = load(tmp_path)
    shown = repr(config)
    assert "UNMISTAKABLE-JF-KEY" not in shown
    assert "UNMISTAKABLE-QB-PASS" not in shown


def test_credentials_in_a_url_are_refused_without_being_echoed(tmp_path):
    text = MINIMAL.replace(
        'url = "http://qbittorrent:8080"',
        'url = "http://admin:UNMISTAKABLE-PASS@qbittorrent:8080"',
    )
    found = problems(tmp_path, text)
    assert mentions(found, "credentials")
    assert not any("UNMISTAKABLE" in p for p in found)


@pytest.mark.parametrize("value", ["inf", "nan"])
def test_a_non_finite_duration_is_a_configuration_error(tmp_path, value):
    found = problems(tmp_path, f"poll_interval = {value}\n" + MINIMAL)
    assert mentions(found, "poll_interval")


@pytest.mark.parametrize(
    ("file_line", "variable", "expected"),
    [
        ("", None, Mode.ACTIVE),  # default
        ('mode = "observe"\n', None, Mode.OBSERVE),  # file beats default
        ('mode = "observe"\n', "active", Mode.ACTIVE),  # variable beats file
        ("", "observe", Mode.OBSERVE),  # variable beats default
    ],
)
def test_mode_comes_from_variable_then_file_then_default(
    tmp_path, file_line, variable, expected
):
    environ = {"WAITARR_MODE": variable} if variable else {}
    assert load(tmp_path, file_line + MINIMAL, environ).mode is expected


def test_empty_variables_count_as_absent(tmp_path):
    text = (
        'mode = "observe"\npoll_interval = "5s"\nlog_level = "DEBUG"\n'
        '[http]\nlisten = "127.0.0.1:9999"\n' + MINIMAL
    )
    config = load(
        tmp_path,
        text,
        {
            "WAITARR_MODE": "",
            "WAITARR_POLL_INTERVAL": "  ",
            "WAITARR_LOG_LEVEL": "",
            "WAITARR_HTTP_LISTEN": "",
            "WAITARR_RELEASE_AFTER": "",
            "WAITARR_THROTTLE_DOWNLOAD": "",
        },
    )
    assert config.mode is Mode.OBSERVE
    assert config.poll_interval == timedelta(seconds=5)
    assert config.log_level == "DEBUG"
    assert (config.http.host, config.http.port) == ("127.0.0.1", 9999)
    assert config.policy.release_after == timedelta(minutes=3)


def test_an_empty_secret_variable_falls_back_to_its_file(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("UNMISTAKABLE-FROM-FILE\n", encoding="utf-8")
    config = load(
        tmp_path,
        environ={
            "WAITARR_MAIN_PASSWORD": "",
            "WAITARR_MAIN_PASSWORD_FILE": str(secret),
        },
    )
    assert config.targets[0].password == "UNMISTAKABLE-FROM-FILE"


COMPOSE_ONLY = {
    "WAITARR_JELLYFIN_URL": "http://jellyfin:8096",
    "WAITARR_QBIT_INSTANCES": "main, second",
    "WAITARR_MAIN_URL": "http://qbit:8080",
    "WAITARR_SECOND_URL": "http://qbit2:8080",
    "WAITARR_SECOND_USERNAME": "bob",
    "WAITARR_SECOND_PASSWORD": "UNMISTAKABLE-2",
}


def test_compose_variables_alone_define_every_service(tmp_path):
    config = load_config(tmp_path / "absent.toml", {**SECRETS, **COMPOSE_ONLY})
    assert [s.url for s in config.sources] == ["http://jellyfin:8096"]
    assert [(t.name, t.url, t.username) for t in config.targets] == [
        ("main", "http://qbit:8080", "admin"),
        ("second", "http://qbit2:8080", "bob"),
    ]


def test_a_missing_file_still_fails_without_the_variables(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "absent.toml", SECRETS)


def test_the_instance_list_replaces_the_files_targets_and_keeps_their_keys(
    tmp_path,
):
    config = load(
        tmp_path,
        MINIMAL.replace('username = "admin"', 'username = "root"'),
        {**COMPOSE_ONLY, "WAITARR_JELLYFIN_URL": "http://other:8096"},
    )
    assert config.sources[0].url == "http://other:8096"
    assert [(t.name, t.username) for t in config.targets] == [
        ("main", "root"),
        ("second", "bob"),
    ]
    assert config.targets[0].url == "http://qbit:8080"


def test_blank_compose_variables_count_as_absent(tmp_path):
    config = load(
        tmp_path,
        environ={"WAITARR_JELLYFIN_URL": " ", "WAITARR_QBIT_INSTANCES": ""},
    )
    assert [t.name for t in config.targets] == ["main"]
    assert config.sources[0].url == "http://jellyfin:8096"


def test_per_instance_throttle_comes_from_variables(tmp_path):
    config = load(
        tmp_path,
        environ={
            **COMPOSE_ONLY,
            "WAITARR_SECOND_THROTTLE_DOWNLOAD": "2KiB",
            "WAITARR_SECOND_THROTTLE_UPLOAD": "4KiB",
        },
    )
    assert config.targets[0].throttle is None
    assert config.targets[1].throttle == Limits(2048, 4096)


def test_an_invalid_instance_name_is_reported(tmp_path):
    found = problems(
        tmp_path, environ={**COMPOSE_ONLY, "WAITARR_QBIT_INSTANCES": "Bad Name"}
    )
    assert mentions(found, "WAITARR_QBIT_INSTANCES", "Bad")


def test_playback_filters_come_from_comma_separated_variables(tmp_path):
    text = MINIMAL + '\n[policy]\nignore_clients = ["Jellyfin Web"]\n'
    config = load(
        tmp_path,
        text,
        {
            "WAITARR_IGNORE_CLIENTS": "Finamp, Jellyfin Media Player",
            "WAITARR_IGNORE_LIBRARIES": "Library-3",
            "WAITARR_USERS": "alice,bob",
            "WAITARR_COUNT_PAUSED": "true",
        },
    )
    f = config.policy.playback_filter
    assert f.ignore_clients == {"finamp", "jellyfin media player"}
    assert f.ignore_libraries == {"library-3"}
    assert f.users == {"alice", "bob"}
    assert f.count_paused is True


def test_filters_fall_back_to_the_file_when_the_variable_is_blank(tmp_path):
    text = MINIMAL.replace(
        "[[sources]]", '[policy]\nlibraries = ["Library-1"]\n\n[[sources]]'
    )
    config = load(tmp_path, text, {"WAITARR_LIBRARIES": " "})
    assert config.policy.playback_filter.libraries == {"library-1"}


def test_an_invalid_count_paused_variable_is_refused(tmp_path):
    found = problems(tmp_path, environ={"WAITARR_COUNT_PAUSED": "maybe"})
    assert mentions(found, "count_paused", "WAITARR_COUNT_PAUSED")


def test_a_source_suspends_the_four_default_tasks_unless_told_otherwise(
    tmp_path,
):
    source = load(tmp_path).sources[0]
    assert source.suspend_tasks is True
    assert source.tasks == (
        "RefreshLibrary",
        "TaskExtractMediaSegments",
        "RefreshChapterImages",
        "RefreshTrickplayImages",
    )
    assert source.tasks == DEFAULT_TASKS


SOURCE_WITH_TASKS = MINIMAL.replace(
    'url = "http://jellyfin:8096"\n',
    'url = "http://jellyfin:8096"\n'
    "suspend_tasks = false\n"
    'tasks = ["RefreshLibrary", "PluginTask"]\n',
    1,
)


def test_the_file_sets_suspend_tasks_and_the_task_keys(tmp_path):
    source = load(tmp_path, SOURCE_WITH_TASKS).sources[0]
    assert source.suspend_tasks is False
    assert source.tasks == ("RefreshLibrary", "PluginTask")


def test_the_environment_wins_over_the_file_for_the_task_options(tmp_path):
    source = load(
        tmp_path,
        SOURCE_WITH_TASKS,
        {
            "WAITARR_JELLYFIN_SUSPEND_TASKS": "true",
            "WAITARR_JELLYFIN_TASKS": " RefreshChapterImages, ,Other ",
        },
    ).sources[0]
    assert source.suspend_tasks is True
    assert source.tasks == ("RefreshChapterImages", "Other")


def test_an_empty_task_list_in_the_file_tracks_nothing(tmp_path):
    text = MINIMAL.replace(
        'url = "http://jellyfin:8096"\n',
        'url = "http://jellyfin:8096"\ntasks = []\n',
        1,
    )
    assert load(tmp_path, text).sources[0].tasks == ()


def test_the_task_options_of_a_source_use_its_own_name(tmp_path):
    text = MINIMAL.replace('name = "jellyfin"', 'name = "jelly-fin"')
    source = load(
        tmp_path,
        text,
        {
            "WAITARR_JELLY_FIN_API_KEY": "k",
            "WAITARR_JELLY_FIN_SUSPEND_TASKS": "no",
            "WAITARR_JELLY_FIN_TASKS": "RefreshLibrary",
        },
    ).sources[0]
    assert (source.suspend_tasks, source.tasks) == (False, ("RefreshLibrary",))


def test_the_task_variables_of_another_source_are_ignored(tmp_path):
    source = load(tmp_path, environ={"WAITARR_OTHER_TASKS": "X"}).sources[0]
    assert source.tasks == DEFAULT_TASKS


@pytest.mark.parametrize("value", ["maybe", "2"])
def test_a_suspend_tasks_that_is_not_a_boolean_is_refused(tmp_path, value):
    found = problems(
        tmp_path, environ={"WAITARR_JELLYFIN_SUSPEND_TASKS": value}
    )
    assert mentions(found, "suspend_tasks", "WAITARR_JELLYFIN_SUSPEND_TASKS")


def test_a_suspend_tasks_of_the_wrong_type_in_the_file_is_refused(tmp_path):
    text = MINIMAL.replace(
        'url = "http://jellyfin:8096"\n',
        'url = "http://jellyfin:8096"\nsuspend_tasks = "no"\n',
        1,
    )
    assert mentions(problems(tmp_path, text), "suspend_tasks")


@pytest.mark.parametrize(
    "value", ['"RefreshLibrary"', "[1]", '[""]', '["a", " "]']
)
def test_task_keys_that_are_not_a_list_of_names_are_refused(tmp_path, value):
    text = MINIMAL.replace(
        'url = "http://jellyfin:8096"\n',
        f'url = "http://jellyfin:8096"\ntasks = {value}\n',
        1,
    )
    assert mentions(problems(tmp_path, text), "tasks")


def test_a_repeated_task_key_counts_once(tmp_path):
    source = load(
        tmp_path, environ={"WAITARR_JELLYFIN_TASKS": "A,B,A"}
    ).sources[0]
    assert source.tasks == ("A", "B")


def test_a_misspelt_task_option_is_still_an_unknown_key(tmp_path):
    text = MINIMAL.replace(
        'url = "http://jellyfin:8096"\n',
        'url = "http://jellyfin:8096"\nsuspend_task = false\n',
        1,
    )
    assert mentions(problems(tmp_path, text), "suspend_task", "unknown key")


# --- One contract per setting: the variable wins over the file, everywhere.

DOC = (Path(__file__).parents[2] / "docs" / "CONFIGURATION.md").read_text(
    encoding="utf-8"
)
THROTTLED = MINIMAL.replace(
    'username = "admin"',
    'username = "admin"\nthrottle = { download = "1KiB", upload = "1KiB" }',
)
GLOBAL_THROTTLE = '[throttle]\ndownload = "1KiB"\nupload = "1KiB"\n'


def _filter(name):
    return lambda c: getattr(c.policy.playback_filter, name)


def _filter_case(name):
    variable = f"WAITARR_{name.upper()}"
    text = f'[policy]\n{name} = ["a"]\n' + MINIMAL
    return (variable, variable, text, "b", _filter(name), {"b"})


# (documented spelling, variable set, file text, value, what to read, expected)
PRECEDENCE = [
    (
        "WAITARR_MODE",
        "WAITARR_MODE",
        'mode = "observe"\n' + MINIMAL,
        "active",
        lambda c: c.mode,
        Mode.ACTIVE,
    ),
    (
        "WAITARR_POLL_INTERVAL",
        "WAITARR_POLL_INTERVAL",
        'poll_interval = "5s"\n' + MINIMAL,
        "1m",
        lambda c: c.poll_interval,
        timedelta(minutes=1),
    ),
    (
        "WAITARR_STATE_FILE",
        "WAITARR_STATE_FILE",
        'state_file = "a.json"\n' + MINIMAL,
        "b.json",
        lambda c: c.state_file,
        Path("b.json"),
    ),
    (
        "WAITARR_LOG_LEVEL",
        "WAITARR_LOG_LEVEL",
        'log_level = "INFO"\n' + MINIMAL,
        "debug",
        lambda c: c.log_level,
        "DEBUG",
    ),
    (
        "WAITARR_RELEASE_AFTER",
        "WAITARR_RELEASE_AFTER",
        '[policy]\nrelease_after = "5m"\n' + MINIMAL,
        "1m",
        lambda c: c.policy.release_after,
        timedelta(minutes=1),
    ),
    (
        "WAITARR_COUNT_PAUSED",
        "WAITARR_COUNT_PAUSED",
        "[policy]\ncount_paused = false\n" + MINIMAL,
        "true",
        lambda c: c.policy.playback_filter.count_paused,
        True,
    ),
    _filter_case("users"),
    _filter_case("ignore_users"),
    _filter_case("ignore_devices"),
    _filter_case("ignore_clients"),
    _filter_case("media_types"),
    _filter_case("libraries"),
    _filter_case("ignore_libraries"),
    (
        "WAITARR_THROTTLE_DOWNLOAD",
        "WAITARR_THROTTLE_DOWNLOAD",
        GLOBAL_THROTTLE + MINIMAL,
        "5KiB",
        lambda c: c.targets[0].throttle,
        Limits(5 * 1024, 1024),
    ),
    (
        "WAITARR_THROTTLE_UPLOAD",
        "WAITARR_THROTTLE_UPLOAD",
        GLOBAL_THROTTLE + MINIMAL,
        "6KiB",
        lambda c: c.targets[0].throttle,
        Limits(1024, 6 * 1024),
    ),
    (
        "WAITARR_HTTP_LISTEN",
        "WAITARR_HTTP_LISTEN",
        '[http]\nlisten = "0.0.0.0:1"\n' + MINIMAL,
        "127.0.0.1:2",
        lambda c: (c.http.host, c.http.port),
        ("127.0.0.1", 2),
    ),
    (
        "WAITARR_<NAME>_URL",
        "WAITARR_MAIN_URL",
        MINIMAL,
        "http://other:1",
        lambda c: c.targets[0].url,
        "http://other:1",
    ),
    (
        "WAITARR_<NAME>_USERNAME",
        "WAITARR_MAIN_USERNAME",
        MINIMAL,
        "bob",
        lambda c: c.targets[0].username,
        "bob",
    ),
    (
        "WAITARR_<NAME>_THROTTLE_DOWNLOAD",
        "WAITARR_MAIN_THROTTLE_DOWNLOAD",
        THROTTLED,
        "9KiB",
        lambda c: c.targets[0].throttle,
        Limits(9 * 1024, 1024),
    ),
    (
        "WAITARR_<NAME>_SUSPEND_TASKS",
        "WAITARR_JELLYFIN_SUSPEND_TASKS",
        SOURCE_WITH_TASKS,
        "true",
        lambda c: c.sources[0].suspend_tasks,
        True,
    ),
    (
        "WAITARR_<NAME>_TASKS",
        "WAITARR_JELLYFIN_TASKS",
        SOURCE_WITH_TASKS,
        "RefreshLibrary",
        lambda c: c.sources[0].tasks,
        ("RefreshLibrary",),
    ),
]

# Documented, but not a setting the file also holds: secrets and
# destinations come from the environment only, the Compose-only variables
# have their own tests, and the last is an example of a name.
NOT_IN_THE_FILE = {
    "WAITARR_CONFIG",
    "WAITARR_JELLYFIN_URL",
    "WAITARR_QBIT_INSTANCES",
    "WAITARR_<NAME>_PASSWORD",
    "WAITARR_<NAME>_API_KEY",
    "WAITARR_<NAME>_PASSWORD_FILE",
    "WAITARR_<NAME>_API_KEY_FILE",
    "WAITARR_WEBHOOK_TOKEN",
    "WAITARR_NOTIFY_WEBHOOK_URL",
    "WAITARR_NOTIFY_NTFY_URL",
    "WAITARR_NOTIFY_NTFY_TOKEN",
    "WAITARR_HEALTHCHECKS_URL",
    "WAITARR_JELLYFIN_API_KEY",
    "WAITARR_SEEDBOX_2_PASSWORD",
}


@pytest.mark.parametrize(
    ("documented", "variable", "text", "value", "read", "expected"),
    PRECEDENCE,
    ids=[case[1] for case in PRECEDENCE],
)
def test_every_documented_variable_wins_over_the_file(
    tmp_path, documented, variable, text, value, read, expected
):
    assert read(load(tmp_path, text, {variable: value})) == expected


def test_every_variable_of_the_documentation_has_a_precedence_case():
    documented = set(re.findall(r"`(WAITARR_[A-Z0-9_<>]+)`", DOC))
    covered = {case[0] for case in PRECEDENCE} | NOT_IN_THE_FILE
    assert documented <= covered, sorted(documented - covered)


# --- Whatever is written, the loader answers with a ConfigError only.

HOSTILE_ENVIRONMENT = [
    {"WAITARR_POLL_INTERVAL": "9" * 400},
    {"WAITARR_POLL_INTERVAL": "99999999999999999999h"},
    {"WAITARR_POLL_INTERVAL": "9" * 5000},
    {"WAITARR_RELEASE_AFTER": "1" + "0" * 30 + "s"},
    {"WAITARR_THROTTLE_DOWNLOAD": "9" * 400, "WAITARR_THROTTLE_UPLOAD": "1KiB"},
    {"WAITARR_HTTP_LISTEN": "host:²"},
    {"WAITARR_HTTP_LISTEN": "host:" + "9" * 5000},
    {"WAITARR_MAIN_THROTTLE_DOWNLOAD": "9" * 400},
]
HOSTILE_FILES = [
    "poll_interval = [1]\n",
    "poll_interval = 9223372036854775807\n",
    "poll_interval = 1e300\n",
    'poll_interval = "99999999999999999999h"\n',
    'state_file = ["a"]\n',
    "[policy]\nrelease_after = {}\n",
    '[policy]\nusers = [""]\n',
    '[policy]\nignore_libraries = ["Music", " "]\n',
    '[http]\nlisten = "host:²"\n',
]
HOSTILE_ENTRIES = [
    ('name = "main"', 'name = ["main"]'),
    ('type = "qbittorrent"', 'type = ["qbittorrent"]'),
    ('url = "http://qbittorrent:8080"', 'url = "http://[::1"'),
    ('url = "http://qbittorrent:8080"', "url = 3"),
    (
        'username = "admin"',
        'username = "admin"\nthrottle = "fast"\npassword_file = "a\\u0000b"',
    ),
    ('username = "admin"', 'username = "admin"\ntimeout = "9999999999999h"'),
]


@pytest.mark.parametrize("environ", HOSTILE_ENVIRONMENT)
def test_a_hostile_variable_is_a_config_error(tmp_path, environ):
    problems(tmp_path, environ=environ)


@pytest.mark.parametrize("text", HOSTILE_FILES)
def test_a_hostile_file_is_a_config_error(tmp_path, text):
    problems(tmp_path, text + MINIMAL)


@pytest.mark.parametrize(("good", "bad"), HOSTILE_ENTRIES)
def test_a_hostile_entry_is_a_config_error(tmp_path, good, bad):
    problems(tmp_path, MINIMAL.replace(good, bad), secrets=False)


@pytest.mark.parametrize(
    "environ", [{"WAITARR_QBIT_INSTANCES": "main"}, {}], ids=["listed", "file"]
)
def test_a_throttle_that_is_not_a_table_is_a_config_error(tmp_path, environ):
    text = MINIMAL.replace(
        'username = "admin"', 'username = "admin"\nthrottle = "fast"'
    )
    found = problems(
        tmp_path,
        text,
        {**environ, "WAITARR_MAIN_THROTTLE_DOWNLOAD": "1KiB"},
    )
    assert mentions(found, "throttle", "table")


def test_a_config_file_that_is_not_text_is_a_config_error(tmp_path):
    path = tmp_path / "waitarr.toml"
    path.write_bytes(b"mode = '\xff\xfe'\n")
    with pytest.raises(ConfigError):
        load_config(path, SECRETS)


def test_a_secrets_file_that_is_not_text_is_a_config_error(tmp_path):
    secret = tmp_path / "secret"
    secret.write_bytes(b"\xff\xfe")
    found = problems(
        tmp_path,
        secrets=False,
        environ={
            "WAITARR_JELLYFIN_API_KEY": "k",
            "WAITARR_MAIN_PASSWORD_FILE": str(secret),
        },
    )
    assert mentions(found, "WAITARR_MAIN_PASSWORD", "cannot read")


# --- Every other silent reading of an empty value.


@pytest.mark.parametrize(
    "variable", ["WAITARR_JELLYFIN_TASKS", "WAITARR_USERS"]
)
@pytest.mark.parametrize("value", [",", " , ,"])
def test_a_list_variable_that_lists_nothing_is_refused(
    tmp_path, variable, value
):
    assert mentions(
        problems(tmp_path, environ={variable: value}), variable, "no value"
    )


def test_a_file_target_reads_its_url_and_limits_from_the_environment(tmp_path):
    # Without WAITARR_QBIT_INSTANCES the file's target used to ignore both.
    target = load(
        tmp_path,
        THROTTLED,
        {
            "WAITARR_MAIN_URL": "http://env:1",
            "WAITARR_MAIN_THROTTLE_UPLOAD": "3KiB",
        },
    ).targets[0]
    assert (target.url, target.throttle) == (
        "http://env:1",
        Limits(1024, 3 * 1024),
    )


@pytest.mark.parametrize(
    "name", ["healthchecks", "notify-webhook", "notify_ntfy"]
)
def test_a_name_that_collides_with_a_global_variable_is_refused(tmp_path, name):
    text = MINIMAL.replace('name = "main"', f'name = "{name}"')
    assert mentions(problems(tmp_path, text), name, "not available as a name")
    assert mentions(
        problems(tmp_path, MINIMAL, {"WAITARR_QBIT_INSTANCES": name}),
        name,
        "not available as a name",
    )


def test_an_unknown_strategy_is_refused_and_lists_the_known_ones(tmp_path):
    text = '[policy]\nstrategy = "nope"\n' + MINIMAL
    assert mentions(problems(tmp_path, text), "strategy", "global")


def test_the_example_file_keeps_the_default_state_file_name(tmp_path):
    # Copied over an installation, another name loses the trace of what
    # Waitarr must give back.
    default = load(tmp_path).state_file.name
    assert load_config(EXAMPLE, SECRETS).state_file.name == default
