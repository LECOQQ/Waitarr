"""Waitarr: throttle qBittorrent while something plays on Jellyfin."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("waitarr")
except PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0+unknown"
