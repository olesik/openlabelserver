"""SQLite storage for the stored resources (API Spec §7.1, §8.3 to §8.6).

`Database` owns the SQLite file the API's catalogs live in, and `DocumentStore` is one
table of it: templates, stocks and calibration profiles are each a catalog of domain
documents, keyed by the identity API §9.3 normalizes. `AssetStore` is the `assets`
table of the same file: an asset is a file rather than a domain document, so its row
carries the bytes and the metadata OpenAPI's `Asset` schema publishes instead. A
database rather than a process-local dictionary is what lets a stored resource
outlive the process that created it: `create_app` takes the path and
`OPENLABEL_DATABASE` supplies it in a deployment. With neither, the database is
process-local (`:memory:`), which is a configuration default rather than a durability
claim.

A domain document's row is only the identity, the document and the two §7.1
timestamps. `object` is derived, because the catalog is the resource type (API §7.2).
"""

from __future__ import annotations

import hashlib
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

# API §8.3 to §8.5: one catalog per resource type. Every catalog row is the same three
# things, so one table with a `kind` column could hold them all — but a table per type
# keeps the `templates` rows an existing `OPENLABEL_DATABASE` already holds readable
# without a migration that would have to rewrite them.
_TABLES = ("templates", "stocks", "calibrations")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS stocks (
    id TEXT PRIMARY KEY,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS calibrations (
    id TEXT PRIMARY KEY,
    document TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    content BLOB NOT NULL,
    created_at TEXT NOT NULL
)
"""


def _now() -> str:
    """An ISO 8601 UTC timestamp (API §7.1), spelled with the `Z` the examples use."""

    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class StoredDocument:
    """One catalog row: the identity, the domain document and its §7.1 timestamps."""

    kind: str
    id: str
    document: dict[str, Any]
    created_at: str
    updated_at: str | None

    def resource(self) -> dict[str, Any]:
        """The body OpenAPI's `Template`, `Stock` or `Calibration` schema describes."""

        resource: dict[str, Any] = {
            "id": self.id,
            "object": self.kind,
            "created_at": self.created_at,
            "document": self.document,
        }
        if self.updated_at is not None:
            resource["updated_at"] = self.updated_at
        return resource


@dataclass(frozen=True)
class StoredAsset:
    """One asset row: the metadata OpenAPI's `Asset` describes and the bytes it serves."""

    id: str
    name: str
    content_type: str
    size_bytes: int
    sha256: str
    content: bytes
    created_at: str

    def resource(self, url: str) -> dict[str, Any]:
        """The body OpenAPI's `Asset` schema describes, `url` naming the content."""

        return {
            "id": self.id,
            "object": "asset",
            "name": self.name,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "url": url,
            "created_at": self.created_at,
        }


class Database:
    """The SQLite database every catalog shares.

    The application answers requests on several threads and a SQLite connection is
    not thread-safe unless it is serialized, so one connection is shared here under
    a lock instead of one connection per request — and one connection for all the
    catalogs, so a write to one cannot find another holding the file.
    """

    def __init__(self, database: str | Path = DEFAULT_DATABASE) -> None:
        self.connection = sqlite3.connect(str(database), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock, self.connection:
            self.connection.executescript(_SCHEMA)

    def store(self, table: str, kind: str) -> DocumentStore:
        """The catalog in `table`, whose resources are of type `kind` (API §7.2)."""

        if table not in _TABLES:
            raise ValueError(f"{table} is not a catalog table")
        return DocumentStore(self, table, kind)

    def assets(self) -> AssetStore:
        """The binary asset catalog the `assets` table holds (API §8.6)."""

        return AssetStore(self)


class DocumentStore:
    """One catalog of domain documents, keyed by the id API §9.3 normalizes."""

    def __init__(self, database: Database, table: str, kind: str) -> None:
        self._database = database
        self._table = table
        self._kind = kind

    def _document(self, row: tuple[Any, ...]) -> StoredDocument:
        return StoredDocument(self._kind, row[0], json.loads(row[1]), row[2], row[3])

    def all(self) -> list[StoredDocument]:
        """Every stored document, in the catalog's own order: creation, then id."""

        with self._database.lock:
            rows = self._database.connection.execute(
                f"SELECT id, document, created_at, updated_at FROM {self._table}"
                " ORDER BY created_at, id"
            ).fetchall()
        return [self._document(row) for row in rows]

    def get(self, resource_id: str) -> StoredDocument | None:
        """The stored document named `resource_id`, or `None`."""

        with self._database.lock:
            row = self._database.connection.execute(
                f"SELECT id, document, created_at, updated_at FROM {self._table}"
                " WHERE id = ?",
                (resource_id,),
            ).fetchone()
        return None if row is None else self._document(row)

    def insert(self, resource_id: str, document: dict[str, Any]) -> StoredDocument | None:
        """Store a new document; `None` when its id is already in the catalog (AR-104)."""

        stored = StoredDocument(self._kind, resource_id, document, _now(), None)
        try:
            # The connection is its own transaction context manager: it commits on
            # success and rolls back on the failed insert, so a rejected duplicate does
            # not leave a write transaction holding the database.
            with self._database.lock, self._database.connection:
                self._database.connection.execute(
                    f"INSERT INTO {self._table} (id, document, created_at) VALUES (?, ?, ?)",
                    (stored.id, json.dumps(document), stored.created_at),
                )
        except sqlite3.IntegrityError:
            return None
        return stored

    def replace(self, resource_id: str, document: dict[str, Any]) -> StoredDocument | None:
        """Overwrite the stored document and stamp `updated_at`; `None` when absent."""

        with self._database.lock, self._database.connection:
            cursor = self._database.connection.execute(
                f"UPDATE {self._table} SET document = ?, updated_at = ? WHERE id = ?",
                (json.dumps(document), _now(), resource_id),
            )
            if cursor.rowcount == 0:
                return None
            row = self._database.connection.execute(
                f"SELECT id, document, created_at, updated_at FROM {self._table}"
                " WHERE id = ?",
                (resource_id,),
            ).fetchone()
        return None if row is None else self._document(row)

    def delete(self, resource_id: str) -> bool:
        """Remove a document; `False` when it was not stored."""

        with self._database.lock, self._database.connection:
            cursor = self._database.connection.execute(
                f"DELETE FROM {self._table} WHERE id = ?", (resource_id,)
            )
        return cursor.rowcount > 0


class AssetStore:
    """The `assets` table: file bytes with the metadata API §8.6 publishes about them.

    The bytes are stored exactly as uploaded, so a download is the file the client sent
    rather than a re-encoding of it; the size and digest are computed from those same
    bytes, so a row cannot describe something other than what it serves.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def insert(
        self, asset_id: str, name: str, content_type: str, content: bytes
    ) -> StoredAsset:
        """Store one uploaded file and return the row that now holds it.

        Asset ids are the server's to choose (§8.6), so unlike a catalog insert there
        is no client-supplied identity to report as a duplicate.
        """

        stored = StoredAsset(
            asset_id,
            name,
            content_type,
            len(content),
            hashlib.sha256(content).hexdigest(),
            content,
            _now(),
        )
        with self._database.lock, self._database.connection:
            self._database.connection.execute(
                "INSERT INTO assets (id, name, content_type, size_bytes, sha256, content,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    stored.id,
                    stored.name,
                    stored.content_type,
                    stored.size_bytes,
                    stored.sha256,
                    stored.content,
                    stored.created_at,
                ),
            )
        return stored

    def get(self, asset_id: str) -> StoredAsset | None:
        """The stored asset named `asset_id`, or `None`."""

        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT id, name, content_type, size_bytes, sha256, content, created_at"
                " FROM assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredAsset(row[0], row[1], row[2], row[3], row[4], row[5], row[6])
