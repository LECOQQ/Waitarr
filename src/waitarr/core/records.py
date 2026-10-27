"""Encode and decode the persisted state document.

The document is versioned: a file written by a newer, incompatible
Waitarr is refused rather than half-read, because a misread `before`
would restore the wrong state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from waitarr.core.model import Limits, TargetState
from waitarr.core.reconcile import Ownership, TargetRecord

__all__ = [
    "SCHEMA_VERSION",
    "StateDocument",
    "StateDocumentError",
    "decode_state",
    "encode_state",
]

SCHEMA_VERSION = 1


class StateDocumentError(ValueError):
    """The stored state cannot be trusted."""


@dataclass(frozen=True)
class StateDocument:
    records: Mapping[str, TargetRecord] = field(default_factory=dict)
    memory: Mapping[str, datetime] = field(default_factory=dict)


def _encode_target_state(state: TargetState | None) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        "throttled": state.throttled,
        "download_limit": state.limits.download,
        "upload_limit": state.limits.upload,
    }


def _decode_target_state(raw: object) -> TargetState | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise StateDocumentError(f"expected an object, got {raw!r}")
    try:
        throttled = raw["throttled"]
        download = raw["download_limit"]
        upload = raw["upload_limit"]
    except KeyError as error:
        raise StateDocumentError(f"missing field {error}") from error
    if not isinstance(throttled, bool) or not all(
        isinstance(v, int) and not isinstance(v, bool) and v >= 0
        for v in (download, upload)
    ):
        raise StateDocumentError(f"malformed target state {dict(raw)!r}")
    return TargetState(throttled, Limits(download, upload))


def encode_state(document: StateDocument) -> dict[str, object]:
    targets: dict[str, object] = {}
    for name in sorted(set(document.records) | set(document.memory)):
        record = document.records.get(name, TargetRecord())
        last = document.memory.get(name)
        targets[name] = {
            "ownership": record.ownership.value,
            "before": _encode_target_state(record.before),
            "applied": _encode_target_state(record.applied),
            "pending": _encode_target_state(record.pending),
            "last_activity_at": last.isoformat() if last else None,
        }
    return {"schema_version": SCHEMA_VERSION, "targets": targets}


def decode_state(raw: Mapping[str, object]) -> StateDocument:
    if not raw:
        return StateDocument()
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise StateDocumentError(
            f"unsupported state schema_version {version!r} "
            f"(this Waitarr reads {SCHEMA_VERSION})"
        )
    targets = raw.get("targets", {})
    if not isinstance(targets, Mapping):
        raise StateDocumentError("'targets' must be an object")
    records: dict[str, TargetRecord] = {}
    memory: dict[str, datetime] = {}
    for name, entry in targets.items():
        if not isinstance(entry, Mapping):
            raise StateDocumentError(f"target {name!r} must be an object")
        try:
            ownership = Ownership(entry.get("ownership", "idle"))
        except ValueError as error:
            raise StateDocumentError(f"target {name!r}: {error}") from error
        record = TargetRecord(
            ownership=ownership,
            before=_decode_target_state(entry.get("before")),
            applied=_decode_target_state(entry.get("applied")),
            pending=_decode_target_state(entry.get("pending")),
        )
        if ownership is Ownership.ENGAGED and (
            record.before is None or record.applied is None
        ):
            raise StateDocumentError(
                f"target {name!r} is engaged without a recorded state"
            )
        records[str(name)] = record
        last = entry.get("last_activity_at")
        if last is not None:
            try:
                memory[str(name)] = datetime.fromisoformat(str(last))
            except ValueError as error:
                raise StateDocumentError(
                    f"target {name!r}: bad last_activity_at {last!r}"
                ) from error
    return StateDocument(records=records, memory=memory)
