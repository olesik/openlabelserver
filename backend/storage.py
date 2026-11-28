"""SQLite storage for the stored resources (API Spec §7.1, §8.3 to §8.6).

`Database` owns the SQLite file the API's catalogs live in, and `DocumentStore` is one
table of it: templates, stocks and calibration profiles are each a catalog of domain
documents, keyed by the identity API §9.3 normalizes. `AssetStore` is the `assets`
table of the same file: an asset is a file rather than a domain document, so its row
carries the bytes and the metadata OpenAPI's `Asset` schema publishes instead.
`IdempotencyStore` is the `idempotency` table, which remembers the response each API
§10 key already answered. A
database rather than a process-local dictionary is what lets a stored resource
outlive the process that created it: `create_app` takes the path and
`OPENLABEL_DATABASE` supplies it in a deployment. With neither, the database is
process-local (`:memory:`), which is a configuration default rather than a durability
claim.

A domain document's row is only the identity, the document and the two §7.1
timestamps. `object` is derived, because the catalog is the resource type (API §7.2).
A render job is neither a document nor a file: `JobStore` keeps the submission API
§8.7 accepted, the status it has reached and the §5.5 error of a failure.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# The database path setting CHECKLIST.md's Persistence section plans.
DATABASE_ENV = "OPENLABEL_DATABASE"
DEFAULT_DATABASE = ":memory:"

# API §10: a duplicated key replays the original response for a day, and is free after.
IDEMPOTENCY_WINDOW = timedelta(hours=24)

# API §8.3 to §8.5: one catalog per resource type. Every catalog row is the same three
# things, so one table with a `kind` column could hold them all — but a table per type
# keeps the `templates` rows an existing `OPENLABEL_DATABASE` already holds readable
# without a migration that would have to rewrite them.
_TABLES = ("templates", "stocks", "calibrations")

# API §8.7: a render job starts `queued` and moves forward only — a queued job cannot
# skip to a result and a terminal status is final. This table is the whole lifecycle
# the resource publishes, so it is the only place a status can come from.
JOB_QUEUED = "queued"
JOB_TERMINAL_STATUSES = ("completed", "failed", "cancelled")
JOB_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "queued": ("processing", "cancelled"),
    "processing": ("completed", "failed", "cancelled"),
    "completed": (),
    "failed": (),
    "cancelled": (),
}

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
);

CREATE TABLE IF NOT EXISTS render_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    request TEXT NOT NULL,
    progress INTEGER NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def _timestamp(moment: datetime) -> str:
    """An ISO 8601 UTC timestamp (API §7.1), spelled with the `Z` the examples use."""

    return moment.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _now() -> str:
    return _timestamp(datetime.now(UTC))


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


@dataclass(frozen=True)
class StoredJob:
    """One render job row: the submission API §8.7 accepted and what it has reached."""

    id: str
    status: str
    request: dict[str, Any]
    progress: int
    error: dict[str, Any] | None
    created_at: str
    updated_at: str | None
    completed_at: str | None

    def resource(self) -> dict[str, Any]:
        """The body OpenAPI's `RenderJob` schema describes.

        The submission is not echoed: `RenderJob` publishes the template, stock and
        output options a job was accepted with, not the document it will render. The
        §5.5 `error` and the completion time appear once the job has one.
        """

        resource: dict[str, Any] = {
            "id": self.id,
            "object": "render_job",
            "created_at": self.created_at,
            "status": self.status,
            "progress": self.progress,
        }
        for name in ("template_id", "stock_id", "output"):
            if name in self.request:
                resource[name] = self.request[name]
        if self.updated_at is not None:
            resource["updated_at"] = self.updated_at
        if self.completed_at is not None:
            resource["completed_at"] = self.completed_at
        if self.error is not None:
            resource["error"] = self.error
        return resource


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

    def jobs(self) -> JobStore:
        """The render job catalog the `render_jobs` table holds (API §8.7)."""

        return JobStore(self)

    def idempotency(self) -> IdempotencyStore:
        """The record of the response each `Idempotency-Key` already answered (§10)."""

        return IdempotencyStore(self)


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

    @staticmethod
    def _asset(row: tuple[Any, ...]) -> StoredAsset:
        return StoredAsset(row[0], row[1], row[2], row[3], row[4], row[5], row[6])

    def all(self, content_type: str | None = None) -> list[StoredAsset]:
        """Stored assets, newest first, optionally only those of `content_type`.

        Newest first is the order every §6.1 collection answers with by default, and
        the id breaks a tie so a page boundary can neither repeat nor skip a row.
        """

        query = (
            "SELECT id, name, content_type, size_bytes, sha256, content, created_at"
            " FROM assets"
        )
        parameters: tuple[Any, ...] = ()
        if content_type is not None:
            query += " WHERE content_type = ?"
            parameters = (content_type,)
        with self._database.lock:
            rows = self._database.connection.execute(
                f"{query} ORDER BY created_at DESC, id DESC", parameters
            ).fetchall()
        return [self._asset(row) for row in rows]

    def get(self, asset_id: str) -> StoredAsset | None:
        """The stored asset named `asset_id`, or `None`."""

        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT id, name, content_type, size_bytes, sha256, content, created_at"
                " FROM assets WHERE id = ?",
                (asset_id,),
            ).fetchone()
        return None if row is None else self._asset(row)

    def delete(self, asset_id: str) -> bool:
        """Remove an asset; `False` when it was not stored."""

        with self._database.lock, self._database.connection:
            cursor = self._database.connection.execute(
                "DELETE FROM assets WHERE id = ?", (asset_id,)
            )
        return cursor.rowcount > 0


@dataclass(frozen=True)
class IdempotentRequest:
    """One §10 key: the body it first answered and the resource that response named."""

    key: str
    fingerprint: str
    resource_id: str
    created_at: str


class IdempotencyStore:
    """The `idempotency` table: which response each `Idempotency-Key` already answered.

    A row records a fingerprint of the request body and the id the response named, not
    the response itself: a replay is rebuilt from the stored resource, so it answers the
    resource that exists rather than a copy of it that could drift.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _request(row: tuple[Any, ...]) -> IdempotentRequest:
        return IdempotentRequest(row[0], row[1], row[2], row[3])

    @staticmethod
    def _live_since() -> str:
        """The oldest `created_at` a key still answers for: §10's 24 hours, as a stamp."""

        return _timestamp(datetime.now(UTC) - IDEMPOTENCY_WINDOW)

    def find(self, key: str) -> IdempotentRequest | None:
        """The live record for `key`, or `None` when it is unused or its day is past."""

        with self._database.lock:
            row = self._database.connection.execute(
                "SELECT key, fingerprint, resource_id, created_at FROM idempotency"
                " WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None or row[3] < self._live_since():
            return None
        return self._request(row)

    def record(
        self, key: str, fingerprint: str, resource_id: str
    ) -> IdempotentRequest | None:
        """Claim `key` for this response; the record that already holds it when it cannot."""

        with self._database.lock, self._database.connection:
            # A row past its day is not a claim, and no sweeper runs: dropping every
            # expired row here keeps a key that is never reused from staying for good.
            self._database.connection.execute(
                "DELETE FROM idempotency WHERE created_at < ?", (self._live_since(),)
            )
            cursor = self._database.connection.execute(
                "INSERT OR IGNORE INTO idempotency (key, fingerprint, resource_id, created_at)"
                " VALUES (?, ?, ?, ?)",
                (key, fingerprint, resource_id, _now()),
            )
            claimed = cursor.rowcount == 1
            row = self._database.connection.execute(
                "SELECT key, fingerprint, resource_id, created_at FROM idempotency"
                " WHERE key = ?",
                (key,),
            ).fetchone()
        return None if claimed else self._request(row)

    def forget(self, key: str) -> None:
        """Release `key`, for a record whose resource no longer exists."""

        with self._database.lock, self._database.connection:
            self._database.connection.execute("DELETE FROM idempotency WHERE key = ?", (key,))


class JobStore:
    """The `render_jobs` table: accepted submissions and the status each has reached.

    A job is stored when the API accepts it and moves only along the transitions API
    §8.7 documents, so its status is a fact of the store rather than a value a caller
    can write over.
    """

    _COLUMNS = "id, status, request, progress, error, created_at, updated_at, completed_at"

    def __init__(self, database: Database) -> None:
        self._database = database

    def _job(self, row: tuple[Any, ...]) -> StoredJob:
        return StoredJob(
            row[0],
            row[1],
            json.loads(row[2]),
            row[3],
            None if row[4] is None else json.loads(row[4]),
            row[5],
            row[6],
            row[7],
        )

    def all(self) -> list[StoredJob]:
        """Every accepted job, in the store's own order: creation, then id."""

        with self._database.lock:
            rows = self._database.connection.execute(
                f"SELECT {self._COLUMNS} FROM render_jobs ORDER BY created_at, id"
            ).fetchall()
        return [self._job(row) for row in rows]

    def get(self, job_id: str) -> StoredJob | None:
        """The job named `job_id`, or `None`."""

        with self._database.lock:
            row = self._database.connection.execute(
                f"SELECT {self._COLUMNS} FROM render_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return None if row is None else self._job(row)

    def insert(self, job_id: str, request: dict[str, Any]) -> StoredJob:
        """Store an accepted submission as a `queued` job.

        The id is the server's to choose (§8.7), so there is no client-supplied
        identity to report as a duplicate and no insert that can lose the race.
        """

        job = StoredJob(job_id, JOB_QUEUED, request, 0, None, _now(), None, None)
        with self._database.lock, self._database.connection:
            self._database.connection.execute(
                "INSERT INTO render_jobs (id, status, request, progress, error, created_at,"
                " updated_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job.id, job.status, json.dumps(request), job.progress, None, job.created_at,
                 None, None),
            )
        return job

    def transition(
        self,
        job_id: str,
        status: str,
        *,
        progress: int | None = None,
        error: dict[str, Any] | None = None,
    ) -> StoredJob | None:
        """Move a job to `status`; `None` when no job has that id.

        A status the current one cannot reach raises `ValueError` instead of being
        stored, so `JOB_TRANSITIONS` is the lifecycle rather than a convention. A
        terminal status also stamps `completed_at`, because that is when the job
        stopped, and only a `failed` job keeps `error` — the §5.5 detail it exposes.
        """

        stored = self.get(job_id)
        if stored is None:
            return None
        if status not in JOB_TRANSITIONS[stored.status]:
            raise ValueError(f"a {stored.status} job cannot become {status}")
        now = _now()
        job = StoredJob(
            stored.id,
            status,
            stored.request,
            100 if status == "completed" else (stored.progress if progress is None else progress),
            error if status == "failed" else None,
            stored.created_at,
            now,
            now if status in JOB_TERMINAL_STATUSES else None,
        )
        with self._database.lock, self._database.connection:
            self._database.connection.execute(
                "UPDATE render_jobs SET status = ?, progress = ?, error = ?, updated_at = ?,"
                " completed_at = ? WHERE id = ?",
                (
                    job.status,
                    job.progress,
                    None if job.error is None else json.dumps(job.error),
                    job.updated_at,
                    job.completed_at,
                    job.id,
                ),
            )
        return job