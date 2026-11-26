from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from itertools import product

import pytest

from waitarr.core.model import Limits, TargetState
from waitarr.core.reconcile import Ownership, TargetRecord, reconcile, restore
from waitarr.core.records import (
    SCHEMA_VERSION,
    StateDocument,
    StateDocumentError,
    decode_state,
    encode_state,
)
from waitarr.core.tasks import TaskOwnership, TaskRecord, TaskWrite

OFF = TargetState(False, Limits(0, 512 * 1024))
HELD = TargetState(True, Limits(1024, 1024))
SEEN = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)


def test_an_engaged_record_survives_an_encode_decode_round_trip():
    document = StateDocument(
        records={
            "main": TargetRecord(
                Ownership.ENGAGED, before=OFF, applied=HELD, pending=HELD
            ),
            "second": TargetRecord(),
        },
        memory={"main": SEEN},
    )
    assert decode_state(encode_state(document)) == StateDocument(
        records=document.records,
        memory=document.memory,
    )


def test_a_yielded_record_with_a_pending_write_round_trips():
    record = TargetRecord(
        Ownership.YIELDED, before=OFF, applied=HELD, pending=OFF
    )
    decoded = decode_state(encode_state(StateDocument({"main": record})))
    assert decoded.records["main"] == record


SLOW = Limits(1024, 2048)
_OBSERVED = (
    OFF,
    HELD,
    TargetState(True, SLOW),
    TargetState(True, Limits(7, 7)),
    TargetState(False, SLOW),
)


def _shape(record: TargetRecord) -> tuple[str, ...]:
    fields = ("before", "applied", "pending", "pending_from")
    return (
        record.ownership.value,
        *(f if getattr(record, f) is not None else "-" for f in fields),
    )


def _reached(
    *, simulate: bool, confirm: Callable[[TargetRecord], TargetRecord]
) -> set[tuple[str, ...]]:
    """Every record shape `reconcile` leads to from a blank record, over
    every observed state and demand; `confirm` is what the engine does to
    the record once a write landed."""
    seen = {TargetRecord()}
    todo = [TargetRecord()]
    while todo:
        record = todo.pop()
        for observed, throttle, limits in product(
            _OBSERVED, (True, False), (None, SLOW)
        ):
            steps = [
                reconcile(
                    record,
                    observed,
                    throttle=throttle,
                    throttle_limits=limits,
                    simulate=simulate,
                )
            ]
            if not simulate:
                steps.append(restore(record, observed))
            for step in steps:
                nexts = [step.record]
                if step.write is not None and not simulate:
                    nexts.append(confirm(step.record))
                for following in nexts:
                    if following not in seen:
                        seen.add(following)
                        todo.append(following)
    return {_shape(record) for record in seen}


def _confirm_v010(record: TargetRecord) -> TargetRecord:
    """What every published version wrote once a write was confirmed:
    `pending` cleared, `pending_from` left behind."""
    return replace(record, pending=None)


def test_the_shapes_the_machine_writes_are_the_ten_of_the_published_versions():
    assert _reached(simulate=False, confirm=_confirm_v010) == {
        ("engaged", "before", "applied", "-", "-"),
        ("engaged", "before", "applied", "-", "pending_from"),
        ("engaged", "before", "applied", "pending", "pending_from"),
        ("idle", "-", "-", "-", "-"),
        ("idle", "-", "-", "-", "pending_from"),
        ("idle", "-", "-", "pending", "pending_from"),
        ("idle", "before", "applied", "-", "pending_from"),
        ("idle", "before", "applied", "pending", "pending_from"),
        ("yielded", "-", "-", "-", "-"),
        ("yielded", "before", "applied", "-", "-"),
    }


def test_observation_mode_reaches_five_shapes():
    assert _reached(simulate=True, confirm=_confirm_v010) == {
        ("engaged", "before", "applied", "-", "-"),
        ("idle", "-", "-", "-", "-"),
        ("idle", "before", "applied", "-", "-"),
        ("yielded", "-", "-", "-", "-"),
        ("yielded", "before", "applied", "-", "-"),
    }


def test_every_record_a_published_version_wrote_round_trips():
    records = [TargetRecord()]
    for record in records:
        for observed, throttle in product(_OBSERVED, (True, False)):
            for step in (
                reconcile(
                    record,
                    observed,
                    throttle=throttle,
                    throttle_limits=SLOW,
                    simulate=False,
                ),
                restore(record, observed),
            ):
                for following in (step.record, _confirm_v010(step.record)):
                    if following not in records:
                        records.append(following)
    assert len(records) >= 10
    for record in records:
        document = StateDocument({"main": record})
        assert decode_state(encode_state(document)) == document


def test_memory_without_a_record_is_kept():
    decoded = decode_state(encode_state(StateDocument(memory={"main": SEEN})))
    assert decoded.memory == {"main": SEEN}
    assert decoded.records["main"].ownership is Ownership.IDLE


def test_the_encoded_document_declares_its_schema_version():
    assert encode_state(StateDocument())["schema_version"] == SCHEMA_VERSION


def test_an_empty_document_decodes_to_nothing_owned():
    assert decode_state({}) == StateDocument()


@pytest.mark.parametrize("version", [0, 3, "2", True, [], None])
def test_an_unknown_schema_version_is_refused(version):
    with pytest.raises(StateDocumentError, match="schema_version"):
        decode_state({"schema_version": version, "targets": {}})


def test_an_engaged_target_without_a_recorded_state_is_refused():
    raw = {
        "schema_version": SCHEMA_VERSION,
        "targets": {"main": {"ownership": "engaged"}},
    }
    with pytest.raises(StateDocumentError, match="engaged without"):
        decode_state(raw)


def test_an_unknown_ownership_is_refused():
    raw = {
        "schema_version": SCHEMA_VERSION,
        "targets": {"main": {"ownership": "borrowed"}},
    }
    with pytest.raises(StateDocumentError):
        decode_state(raw)


@pytest.mark.parametrize(
    "state",
    [
        {"throttled": "yes", "download_limit": 0, "upload_limit": 0},
        {"throttled": True, "download_limit": -1, "upload_limit": 0},
        {"throttled": True, "download_limit": True, "upload_limit": 0},
        {"throttled": True, "download_limit": 0},
    ],
)
def test_a_malformed_target_state_is_refused(state):
    raw = {
        "schema_version": SCHEMA_VERSION,
        "targets": {"main": {"ownership": "idle", "before": state}},
    }
    with pytest.raises(StateDocumentError):
        decode_state(raw)


def test_a_bad_timestamp_is_refused():
    raw = {
        "schema_version": SCHEMA_VERSION,
        "targets": {"main": {"last_activity_at": "yesterday-ish"}},
    }
    with pytest.raises(StateDocumentError, match="last_activity_at"):
        decode_state(raw)


@pytest.mark.parametrize(
    "stamp", ["2026-10-27T20:00:00", 1761595200, True, ["2026-10-27"]]
)
def test_a_timestamp_without_an_offset_or_not_text_is_refused(stamp):
    for raw in (
        {"targets": {"main": {"last_activity_at": stamp}}},
        {"tasks": {"jellyfin": {"last_activity_at": stamp}}},
    ):
        with pytest.raises(StateDocumentError, match="last_activity_at"):
            decode_state({"schema_version": SCHEMA_VERSION, **raw})


STOPPED = TaskRecord(
    TaskOwnership.STOPPED,
    cancelled_start="2026-10-30T21:25:06.0000000Z",
    pending=TaskWrite.START,
    pending_from="2026-10-30T21:25:06.0000000Z",
)


def test_task_records_survive_an_encode_decode_round_trip():
    document = StateDocument(
        records={"main": TargetRecord()},
        memory={"main": SEEN},
        tasks={
            "jellyfin": {
                "RefreshLibrary": STOPPED,
                "RefreshChapterImages": TaskRecord(TaskOwnership.YIELDED),
                # A task that never ran has the identity None.
                "TaskExtractMediaSegments": TaskRecord(
                    TaskOwnership.STOPPED,
                    pending=TaskWrite.STOP,
                    pending_from=None,
                ),
            }
        },
        task_memory={"jellyfin": SEEN},
    )
    assert decode_state(encode_state(document)) == document


def test_task_memory_without_a_record_is_kept_apart_from_the_targets():
    # A task source and a target may share a name.
    document = StateDocument(
        memory={"jellyfin": SEEN}, task_memory={"jellyfin": SEEN}
    )
    encoded = encode_state(document)
    assert encoded["tasks"] == {
        "jellyfin": {"last_activity_at": SEEN.isoformat(), "records": {}}
    }
    decoded = decode_state(encoded)
    assert decoded.task_memory == {"jellyfin": SEEN}
    assert decoded.tasks == {"jellyfin": {}}


def test_an_idle_task_record_is_not_persisted():
    idle = {"RefreshLibrary": TaskRecord()}
    document = StateDocument(tasks={"jellyfin": idle})
    encoded = encode_state(document)
    assert encoded["tasks"] == {
        "jellyfin": {"last_activity_at": None, "records": {}}
    }


def test_a_version_1_file_is_read_as_owning_no_task():
    raw = {
        "schema_version": 1,
        "targets": {
            "main": {
                "ownership": "engaged",
                "before": {
                    "throttled": False,
                    "download_limit": 0,
                    "upload_limit": 0,
                },
                "applied": {
                    "throttled": True,
                    "download_limit": 1024,
                    "upload_limit": 1024,
                },
                "last_activity_at": SEEN.isoformat(),
            }
        },
    }
    decoded = decode_state(raw)
    assert decoded.records["main"].ownership is Ownership.ENGAGED
    assert decoded.memory == {"main": SEEN}
    assert decoded.tasks == {}
    assert decoded.task_memory == {}


def test_a_version_1_file_with_tasks_is_refused():
    raw = {"schema_version": 1, "targets": {}, "tasks": {"jellyfin": {}}}
    with pytest.raises(StateDocumentError, match="version 1"):
        decode_state(raw)


def _task_document(entry):
    return {
        "schema_version": SCHEMA_VERSION,
        "targets": {},
        "tasks": {"jellyfin": {"records": {"RefreshLibrary": entry}}},
    }


@pytest.mark.parametrize(
    "entry",
    [
        {"ownership": "borrowed"},
        {"ownership": "stopped", "pending": "pause"},
        {"ownership": "yielded", "pending": "stop"},
        {"ownership": "idle", "pending": "start"},
        {"ownership": "stopped", "cancelled_start": 12},
        {"ownership": "stopped", "pending": "stop", "pending_from": []},
        "stopped",
    ],
)
def test_a_malformed_task_record_is_refused(entry):
    with pytest.raises(StateDocumentError):
        decode_state(_task_document(entry))


@pytest.mark.parametrize(
    "section",
    [
        [],
        {"jellyfin": []},
        {"jellyfin": {"records": []}},
        {"jellyfin": {"last_activity_at": "yesterday-ish"}},
    ],
)
def test_a_malformed_tasks_section_is_refused(section):
    raw = {"schema_version": SCHEMA_VERSION, "targets": {}, "tasks": section}
    with pytest.raises(StateDocumentError):
        decode_state(raw)
