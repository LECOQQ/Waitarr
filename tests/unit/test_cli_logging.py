import logging

import pytest

from waitarr.cli import _setup_logging


@pytest.fixture(autouse=True)
def _restore_logging():
    names = ("urllib3", "requests", "qbittorrentapi")
    saved = {n: logging.getLogger(n).level for n in names}
    root = logging.getLogger()
    root_level, root_handlers = root.level, root.handlers[:]
    yield
    for n, level in saved.items():
        logging.getLogger(n).setLevel(level)
    root.handlers[:] = root_handlers
    root.setLevel(root_level)


LIBRARIES = ["urllib3", "urllib3.connectionpool", "requests"]


@pytest.mark.parametrize("name", LIBRARIES)
def test_library_loggers_only_report_errors(name):
    _setup_logging("INFO")
    logger = logging.getLogger(name)
    assert not logger.isEnabledFor(logging.WARNING)
    assert logger.isEnabledFor(logging.ERROR)


def test_waitarr_messages_still_pass():
    _setup_logging("INFO")
    assert logging.getLogger("waitarr").isEnabledFor(logging.INFO)
