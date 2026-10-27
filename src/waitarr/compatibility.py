"""The compatibility matrix, checked against each service at startup.

Mirrors docs/COMPATIBILITY.md: a version is *tested* only when it was
exercised for real; anything newer than the minimum is *assumed*.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from packaging.version import InvalidVersion, Version

from waitarr.core.model import ServiceVersion

__all__ = ["MATRIX", "Assessment", "Verdict", "assess"]


class Verdict(StrEnum):
    TESTED = "tested"
    ASSUMED = "assumed"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Support:
    product: str
    minimum: str
    tested: tuple[str, ...]


MATRIX: dict[str, Support] = {
    "jellyfin": Support("Jellyfin", "12.2.0", ("12.2.0",)),
    "qbittorrent": Support("qBittorrent", "5.1.0", ("5.1.0", "5.1.4")),
}


@dataclass(frozen=True)
class Assessment:
    verdict: Verdict
    message: str


def _parse(text: str) -> Version:
    return Version(text.strip().removeprefix("v"))


def assess(kind: str, reported: ServiceVersion | None) -> Assessment:
    support = MATRIX[kind]
    if reported is None or not reported.version:
        return Assessment(
            Verdict.UNKNOWN,
            f"{support.product} version unknown; the compatibility matrix "
            "cannot be checked",
        )
    try:
        version = _parse(reported.version)
    except InvalidVersion:
        return Assessment(
            Verdict.UNKNOWN,
            f"{support.product} reported an unreadable version "
            f"{reported.version!r}",
        )
    api = f" (Web API {reported.api_version})" if reported.api_version else ""
    shown = f"{support.product} {version}{api}"
    if version < _parse(support.minimum):
        return Assessment(
            Verdict.UNSUPPORTED,
            f"{shown} is OUTSIDE the compatibility matrix (minimum "
            f"{support.minimum}); Waitarr runs, but its behaviour there "
            "is unverified -- see docs/COMPATIBILITY.md",
        )
    if any(version == _parse(t) for t in support.tested):
        return Assessment(Verdict.TESTED, f"{shown}: tested")
    return Assessment(
        Verdict.ASSUMED,
        f"{shown}: newer than every tested version, assumed compatible "
        "-- see docs/COMPATIBILITY.md",
    )
