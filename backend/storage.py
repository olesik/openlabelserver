"""SQLite storage for the templates resource (API Spec §7.1, §7.2 and §8.3).

`TemplateStore` is the template catalog the API reads and writes. It is a SQLite
database rather than a process-local dictionary, so a stored template outlives the
process that created it: `create_app` takes the path and `OPENLABEL_DATABASE`
supplies it in a deployment. With neither, the store is process-local
(`:memory:`), which is a configuration default rather than a durability claim.

Only the identity, the RenderSpec document and the two §7.1 timestamps are stored.
`object` is derived, because the catalog is the resource type (API §7.2).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The database path setting CHECKLIST.md's Persistence section plans.
DATABASE_ENV = "OPENLABEL_DATABASE"
DEFAULT_DATABASE = ":memory:"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
)
"""


def _now() -> str:
    """An ISO 8601 UTC timestamp (API §7.1), spelled with the `Z` the examples use."""

    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class StoredTemplate:
    """One catalog row: the identity, the RenderSpec document and its §7.1 timestamps."""

    id: str
    document: dict[str, Any]
    created_at: str
    updated_at: str | None

    def resource(self) -> dict[str, Any]:
        """The body OpenAPI's `Template` schema describes for this row."""

        resource: dict[str, Any] = {
            "id": self.id,
            "object": "template",
            "created_at": self.created_at,
            "document": self.document,
        }
        if self.updated_at is not None:
            resource["updated_at"] = self.updated_at
        return resource


class TemplateStore:
    """The template catalog: one row per stored RenderSpec document.

    The application answers requests on several threads and a SQLite connection is
    not thread-safe unless it is serialized, so one connection is shared here under
    a lock instead of one connection per request.
    """

    def __init__(self, database: str | Path = DEFAULT_DATABASE) -> None:
        self._connection = sqlite3.connect(str(database), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._connection:
            self._connection.execute(_SCHEMA)

    @staticmethod
    def _template(row: tuple[Any, ...]) -> StoredTemplate:
        return StoredTemplate(row[0], json.loads(row[1]), row[2], row[3])

    def all(self) -> list[StoredTemplate]:
        """Every stored template, in the catalog's own order: creation, then id."""

        with self._lock:
            rows = self._connection.execute(
                "SELECT id, document, created_at, updated_at"
                " FROM templates ORDER BY created_at, id"
            ).fetchall()
        return [self._template(row) for row in rows]

    def get(self, template_id: str) -> StoredTemplate | None:
        """The stored template named `template_id`, or `None`."""

        with self._lock:
            row = self._connection.execute(
                "SELECT id, document, created_at, updated_at FROM templates WHERE id = ?",
                (template_id,),
            ).fetchone()
        return None if row is None else self._template(row)

    def insert(self, document: dict[str, Any]) -> StoredTemplate | None:
        """Store a new template; `None` when its id is already in the catalog (AR-103)."""

        stored = StoredTemplate(document["id"], document, _now(), None)
        try:
            # The connection is its own transaction context manager: it commits on
            # success and rolls back on the failed insert, so a rejected duplicate does
            # not leave a write transaction holding the database.
            with self._lock, self._connection:
                self._connection.execute(
                    "INSERT INTO templates (id, document, created_at) VALUES (?, ?, ?)",
                    (stored.id, json.dumps(document), stored.created_at),
                )
        except sqlite3.IntegrityError:
            return None
        return stored

    def replace(self, template_id: str, document: dict[str, Any]) -> StoredTemplate | None:
        """Overwrite the stored document and stamp `updated_at`; `None` when absent."""

        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE templates SET document = ?, updated_at = ? WHERE id = ?",
                (json.dumps(document), _now(), template_id),
            )
            if cursor.rowcount == 0:
                return None
            row = self._connection.execute(
                "SELECT id, document, created_at, updated_at FROM templates WHERE id = ?",
                (template_id,),
            ).fetchone()
        return None if row is None else self._template(row)

    def delete(self, template_id: str) -> bool:
        """Remove a template; `False` when it was not stored."""

        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        return cursor.rowcount > 0
