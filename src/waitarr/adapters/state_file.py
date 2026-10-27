"""The state store: one JSON file, replaced atomically."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from waitarr.core.records import StateDocumentError

__all__ = ["JsonStateFile"]


class JsonStateFile:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, object]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            raise StateDocumentError(
                f"{self._path} is not valid JSON ({error}); move it aside "
                "only after checking what it says Waitarr owns"
            ) from error
        if not isinstance(document, dict):
            raise StateDocumentError(f"{self._path} must hold a JSON object")
        return document

    def save(self, document: dict[str, object]) -> None:
        # Write-then-rename: a crash leaves the old file or the new one,
        # never half of either.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=self._path.parent, prefix=f".{self._path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
