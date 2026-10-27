import pytest

from waitarr.compatibility import MATRIX, Verdict, assess
from waitarr.core.model import ServiceVersion


def verdict(kind, version, api=None):
    return assess(kind, ServiceVersion("x", version, api)).verdict


def test_a_tested_version_is_tested():
    assert verdict("qbittorrent", "5.1.4") is Verdict.TESTED
    assert verdict("qbittorrent", "5.1.0") is Verdict.TESTED
    assert verdict("jellyfin", "12.2.0") is Verdict.TESTED


def test_a_version_newer_than_the_minimum_but_untested_is_assumed():
    assert verdict("qbittorrent", "5.2.0") is Verdict.ASSUMED
    assert verdict("qbittorrent", "5.1.2") is Verdict.ASSUMED
    assert verdict("jellyfin", "12.3.1") is Verdict.ASSUMED


def test_a_version_below_the_minimum_is_unsupported():
    assert verdict("qbittorrent", "4.6.7") is Verdict.UNSUPPORTED
    assert verdict("jellyfin", "10.9.0") is Verdict.UNSUPPORTED


def test_a_leading_v_is_ignored():
    assert verdict("qbittorrent", "v5.1.4") is Verdict.TESTED
    assert verdict("qbittorrent", "v4.6.0") is Verdict.UNSUPPORTED


@pytest.mark.parametrize("version", [None, "", "banana"])
def test_a_missing_or_unreadable_version_is_unknown(version):
    assert verdict("jellyfin", version) is Verdict.UNKNOWN


def test_no_reported_version_at_all_is_unknown():
    assert assess("jellyfin", None).verdict is Verdict.UNKNOWN


def test_the_api_version_is_shown_when_known():
    assert (
        "2.11.4"
        in assess(
            "qbittorrent", ServiceVersion("qBittorrent", "5.1.4", "2.11.4")
        ).message
    )


def test_every_tested_version_is_at_or_above_the_minimum():
    for kind in MATRIX:
        assert verdict(kind, MATRIX[kind].minimum) is not Verdict.UNSUPPORTED
        for tested in MATRIX[kind].tested:
            assert verdict(kind, tested) is Verdict.TESTED
