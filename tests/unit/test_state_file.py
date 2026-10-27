import json

import pytest

from waitarr.adapters.state_file import JsonStateFile
from waitarr.core.records import StateDocumentError


def test_a_missing_file_loads_as_an_empty_document(tmp_path):
    assert JsonStateFile(tmp_path / "state.json").load() == {}


def test_a_saved_document_loads_back_unchanged(tmp_path):
    store = JsonStateFile(tmp_path / "state.json")
    document = {"schema_version": 1, "targets": {"main": {"x": [1, 2]}}}
    store.save(document)
    assert store.load() == document


def test_saving_creates_missing_parent_directories(tmp_path):
    store = JsonStateFile(tmp_path / "deep" / "er" / "state.json")
    store.save({"a": 1})
    assert store.load() == {"a": 1}


def test_saving_replaces_the_previous_content_and_leaves_no_temporary_file(
    tmp_path,
):
    store = JsonStateFile(tmp_path / "state.json")
    store.save({"a": 1})
    store.save({"b": 2})
    assert store.load() == {"b": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_a_failed_save_keeps_the_old_file_and_cleans_up(tmp_path):
    store = JsonStateFile(tmp_path / "state.json")
    store.save({"a": 1})
    with pytest.raises(TypeError):
        store.save({"bad": object()})
    assert json.loads((tmp_path / "state.json").read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_invalid_json_is_refused_rather_than_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StateDocumentError, match="not valid JSON"):
        JsonStateFile(path).load()


def test_a_json_document_that_is_not_an_object_is_refused(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(StateDocumentError, match="JSON object"):
        JsonStateFile(path).load()
