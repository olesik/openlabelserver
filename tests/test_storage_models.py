"""Tests for `backend/models.py` and the SQLAlchemy store built on it (B2 — Storage).

The models are the schema of the database an earlier version already wrote, so these
tests check both the row shape each table publishes and that such a file stays readable
through the stores, rather than only that a fresh database can be created.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import storage  # noqa: E402
from backend.models import Base  # noqa: E402

# API §7.1 and §8.6 to §8.7: the columns each table carries. A catalog row is the
# identity, the document and the two timestamps; an asset carries its file; a render
# job carries the submission and the status it reached.
COLUMNS = {
    "templates": ["id", "document", "created_at", "updated_at"],
    "stocks": ["id", "document", "created_at", "updated_at"],
    "calibrations": ["id", "document", "created_at", "updated_at"],
    "assets": [
        "id",
        "name",
        "content_type",
        "size_bytes",
        "sha256",
        "content",
        "created_at",
    ],
    "render_jobs": [
        "id",
        "status",
        "request",
        "progress",
        "error",
        "created_at",
        "updated_at",
        "completed_at",
    ],
    "idempotency": ["key", "fingerprint", "resource_id", "created_at"],
}

# The templates table as the previous raw-SQL schema created it, so a database written
# before the models existed is what the compatibility test opens.
LEGACY_TEMPLATES = """
CREATE TABLE templates (
    id TEXT PRIMARY KEY,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
)
"""


def test_the_models_declare_the_tables_and_columns_the_stores_use() -> None:
    assert set(Base.metadata.tables) == set(COLUMNS)
    for table, columns in COLUMNS.items():
        assert [column.name for column in Base.metadata.tables[table].columns] == columns


def test_a_new_database_holds_every_table(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    storage.Database(path)
    with sqlite3.connect(path) as connection:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert set(COLUMNS) <= names


def test_a_database_written_by_the_previous_schema_stays_readable(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    document = {"metadata": {"id": "legacy-label", "name": "Legacy label"}}
    with sqlite3.connect(path) as connection:
        connection.execute(LEGACY_TEMPLATES)
        connection.execute(
            "INSERT INTO templates (id, document, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)",
            ("legacy-label", json.dumps(document), "2026-01-01T00:00:00.000000Z", None),
        )

    store = storage.Database(path).store("templates", "template")
    stored = store.get("legacy-label")
    assert stored is not None
    assert stored.resource() == {
        "id": "legacy-label",
        "object": "template",
        "created_at": "2026-01-01T00:00:00.000000Z",
        "document": document,
    }

    replaced = store.replace("legacy-label", {"metadata": {"id": "legacy-label"}})
    assert replaced is not None
    assert replaced.updated_at is not None


def test_a_store_refuses_a_table_that_is_not_a_catalog() -> None:
    with pytest.raises(ValueError, match="not a catalog table"):
        storage.Database().store("assets", "asset")
