import logging

import pytest

from waitarr.cli import LIBRARY_LEVELS


@pytest.fixture(autouse=True)
def _restore_logging():
    """The commands call `_setup_logging`, which reconfigures the root
    logger and the library loggers: give every test the ones it found."""
    saved = {n: logging.getLogger(n).level for n in LIBRARY_LEVELS}
    root = logging.getLogger()
    root_level, root_handlers = root.level, root.handlers[:]
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)
    root.handlers[:] = root_handlers
    root.setLevel(root_level)
