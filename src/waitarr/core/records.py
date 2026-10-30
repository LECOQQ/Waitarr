"""Encode and decode the persisted state document.

The document is versioned: a file written by a newer, incompatible
Waitarr is refused rather than half-read, because a misread `before`
would restore the wrong state. Version 2 adds the `tasks` section; a
version 1 file is read as owning no task.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from waitarr.core.model import Limits, TargetState
from waitarr.core.reconcile import Ownership, TargetRecord
from waitarr.core.tasks import TaskOwnership, TaskRecord, TaskWrite

__all__ = [
    "SCHEMA_VERSION",
    "StateDocument",
    "StateDocumentError",
    "decode_state",
    "encode_state",
]

SCHEMA_VERSION = 2
READABLE_VERSIONS = (1, SCHEMA_VERSION)


class StateDocumentError(ValueError):
    """The stored state cannot be trusted."""


@dataclass(frozen=True)
class StateDocument:
    records: Mapping[str, TargetRecord] = field(default_factory=dict)
    memory: Mapping[str, datetime] = field(default_factory=dict)
    # Per task source, then per task key; the hold memory of a source is
    # kept apart from the targets', whatever the names.
    tasks: Mapping[str, Mapping[str, TaskRecord]] = field(default_factory=dict)
    task_memory: Mapping[str, datetime] = field(default_factory=dict)


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


def _encode_tasks(document: StateDocument) -> dict[str, object]:
    sources: dict[str, object] = {}
    for source in sorted(set(document.tasks) | set(document.task_memory)):
        last = document.task_memory.get(source)
        records = document.tasks.get(source, {})
        sources[source] = {
            "last_activity_at": last.isoformat() if last else None,
            "records": {
                key: {
                    "ownership": record.ownership.value,
                    "cancelled_start": record.cancelled_start,
                    "pending": record.pending.value if record.pending else None,
                    "pending_from": record.pending_from,
                }
                for key, record in sorted(records.items())
                if record.ownership is not TaskOwnership.IDLE
            },
        }
    return sources


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
            "pending_from": _encode_target_state(record.pending_from),
            "last_activity_at": last.isoformat() if last else None,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "targets": targets,
        "tasks": _encode_tasks(document),
    }


def _optional_text(entry: Mapping[str, object], field_name: str, where: str):
    value = entry.get(field_name)
    if value is not None and not isinstance(value, str):
        raise StateDocumentError(f"{where}: {field_name} must be a string")
    return value


def _decode_task_record(key: str, entry: object, where: str) -> TaskRecord:
    if not isinstance(entry, Mapping):
        raise StateDocumentError(f"{where} must be an object")
    try:
        ownership = TaskOwnership(entry.get("ownership", "idle"))
        raw_pending = entry.get("pending")
        pending = None if raw_pending is None else TaskWrite(raw_pending)
    except ValueError as error:
        raise StateDocumentError(f"{where}: {error}") from error
    if pending is not None and ownership is not TaskOwnership.STOPPED:
        raise StateDocumentError(
            f"{where}: a pending {pending.value} needs a stopped task"
        )
    return TaskRecord(
        ownership=ownership,
        cancelled_start=_optional_text(entry, "cancelled_start", where),
        pending=pending,
        pending_from=_optional_text(entry, "pending_from", where),
    )


def _decode_tasks(
    raw: Mapping[str, object], version: object
) -> tuple[dict[str, dict[str, TaskRecord]], dict[str, datetime]]:
    """The `tasks` section; a version 1 file has none."""
    section = raw.get("tasks", {})
    if version == 1:
        if section:
            raise StateDocumentError("a version 1 state file has no 'tasks'")
        return {}, {}
    if not isinstance(section, Mapping):
        raise StateDocumentError("'tasks' must be an object")
    tasks: dict[str, dict[str, TaskRecord]] = {}
    memory: dict[str, datetime] = {}
    for source, entry in section.items():
        where = f"task source {source!r}"
        if not isinstance(entry, Mapping):
            raise StateDocumentError(f"{where} must be an object")
        records = entry.get("records", {})
        if not isinstance(records, Mapping):
            raise StateDocumentError(f"{where}: 'records' must be an object")
        decoded = {
            str(key): _decode_task_record(
                str(key), item, f"{where}, task {key!r}"
            )
            for key, item in records.items()
        }
        tasks[str(source)] = {
            key: record
            for key, record in decoded.items()
            if record.ownership is not TaskOwnership.IDLE
        }
        last = entry.get("last_activity_at")
        if last is not None:
            try:
                memory[str(source)] = datetime.fromisoformat(str(last))
            except ValueError as error:
                raise StateDocumentError(
                    f"{where}: bad last_activity_at {last!r}"
                ) from error
    return tasks, memory


def decode_state(raw: Mapping[str, object]) -> StateDocument:
    if not raw:
        return StateDocument()
    version = raw.get("schema_version")
    if version not in READABLE_VERSIONS or isinstance(version, bool):
        raise StateDocumentError(
            f"unsupported state schema_version {version!r} "
            f"(this Waitarr reads {list(READABLE_VERSIONS)})"
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
            pending_from=_decode_target_state(entry.get("pending_from")),
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
    tasks, task_memory = _decode_tasks(raw, version)
    return StateDocument(
        records=records,
        memory=memory,
        tasks=tasks,
        task_memory=task_memory,
    )
