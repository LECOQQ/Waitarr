from datetime import timedelta

import pytest

from waitarr.core.units import (
    format_duration,
    format_rate,
    parse_duration,
    parse_rate,
)


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("15s", 15),
        ("3m", 180),
        ("1h30m", 5400),
        ("1h 30m 5s", 5405),
        ("250ms", 0.25),
        ("90", 90),
        (" 2M ", 120),
    ],
)
def test_parse_duration_reads_human_spellings(text, seconds):
    assert parse_duration(text) == timedelta(seconds=seconds)


def test_parse_duration_accepts_plain_numbers_as_seconds():
    assert parse_duration(45) == timedelta(seconds=45)
    assert parse_duration(1.5) == timedelta(seconds=1.5)


@pytest.mark.parametrize("value", ["", "soon", "3x", "m3", "3m junk", "-5s"])
def test_parse_duration_rejects_garbage(value):
    with pytest.raises(ValueError):
        parse_duration(value)


@pytest.mark.parametrize("value", [-1, -0.5, True])
def test_parse_duration_rejects_negative_numbers_and_booleans(value):
    with pytest.raises(ValueError):
        parse_duration(value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1KiB", 1024),
        ("512 KiB/s", 512 * 1024),
        ("2MiB", 2 * 1024**2),
        ("1GiB", 1024**3),
        ("1kb", 1000),
        ("1.5MiB", 1_572_864),
        ("100", 100),
        ("512 B/s", 512),
        ("0", 0),
    ],
)
def test_parse_rate_reads_binary_and_decimal_units(text, expected):
    assert parse_rate(text) == expected


def test_parse_rate_accepts_an_integer_as_bytes():
    assert parse_rate(4096) == 4096


@pytest.mark.parametrize("value", ["fast", "1TiB", "KiB", "", "-1KiB"])
def test_parse_rate_rejects_garbage(value):
    with pytest.raises(ValueError):
        parse_rate(value)


@pytest.mark.parametrize("value", [-1, True])
def test_parse_rate_rejects_negative_numbers_and_booleans(value):
    with pytest.raises(ValueError):
        parse_rate(value)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0, "unlimited"),
        (512, "512 B/s"),
        (1024, "1 KiB/s"),
        (1536, "1.5 KiB/s"),
        (5 * 1024**2, "5 MiB/s"),
        (2 * 1024**3, "2 GiB/s"),
    ],
)
def test_format_rate(value, text):
    assert format_rate(value) == text


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0s"), (15, "15s"), (180, "3m"), (5400, "1h30m"), (3661, "1h1m1s")],
)
def test_format_duration(seconds, text):
    assert format_duration(timedelta(seconds=seconds)) == text


@pytest.mark.parametrize("text", ["15s", "3m", "1h30m", "1h1m1s"])
def test_format_duration_round_trips_through_parse_duration(text):
    assert format_duration(parse_duration(text)) == text


@pytest.mark.parametrize("value", [512, 1024, 1536, 5 * 1024**2])
def test_format_rate_output_parses_back(value):
    assert parse_rate(format_rate(value)) == value
