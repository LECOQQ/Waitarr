import logging

import pytest

from waitarr.cli import _setup_logging

LIBRARIES = ["urllib3", "urllib3.connectionpool", "requests"]


@pytest.mark.parametrize("name", LIBRARIES)
def test_library_loggers_only_report_errors(name):
    _setup_logging("INFO")
    logger = logging.getLogger(name)
    assert not logger.isEnabledFor(logging.WARNING)
    assert logger.isEnabledFor(logging.ERROR)


def test_the_https_to_http_fallback_warning_is_not_silenced():
    # qbittorrent-api warns on this logger when it talks plain http to a
    # host configured as https: the warning that the connection left https.
    _setup_logging("INFO")
    logger = logging.getLogger("qbittorrentapi.request")
    assert logger.isEnabledFor(logging.WARNING)


def test_waitarr_messages_still_pass():
    _setup_logging("INFO")
    assert logging.getLogger("waitarr").isEnabledFor(logging.INFO)
