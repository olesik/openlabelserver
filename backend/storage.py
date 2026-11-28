"""SQLite storage for the stored resources (API Spec §7.1, §8.3 to §8.7).

`Database` owns the SQLite file the API's catalogs live in, and the tables in it are the
SQLAlchemy models `backend/models.py` declares (B2 — Storage). `DocumentStore` is one
catalog of that file: templates, stocks and calibration profiles are each a catalog of
domain documents, keyed by the identity API §9.3 normalizes. `AssetStore` is the
`assets` table of the same file: an asset is a file rather than a domain document, so
its row carries the bytes and the metadata OpenAPI's `Asset` schema publishes instead.
`IdempotencyStore` is the `idempotency` table, which remembers the response each API
§10 key already answered. A database rather than a process-local dictionary is what
lets a stored resource outlive the process that created it: `create_app` takes the path
and `OPENLABEL_DATABASE` supplies it in a deployment. With neither, the database is
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
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import URL, Engine, create_engine, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.models import (
    AssetRecord,
    Base,
    CalibrationRecord,
    CatalogRecord,
    IdempotencyRecord,
    RenderJobRecord,
    StockRecord,
    TemplateRecord,
)

# The database path setting CHECKLIST.md's Persistence section plans.
DATABASE_ENV = "OPENLABEL_DATABASE"
DEFAULT_DATABASE = ":memory:"

# API §10: a duplicated key replays the original response for a day, and is free after.
IDEMPOTENCY_WINDOW = timedelta(hours=24)

# API §8.3 to §8.5: one catalog per resource type, so one model per table. The table a
# store serves is fixed here rather than looked up from the request, because the catalog
# a resource belongs to is the resource type (API §7.2).
_CATALOGS: dict[str, type[CatalogRecord]] = {
    "templates": TemplateRecord,
    "stocks": StockRecord,
    "calibrations": CalibrationRecord,
}

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


def _create_engine(database: str) -> Engine:
    """An engine for `database`, sharing one connection when it is process-local.

    A `:memory:` database lives in its connection, so every session has to reach the
    same one or each would find an empty copy; a file database gets the default pool,
    whose connections all read the same file.
    """

    url = URL.create("sqlite+pysqlite", database=database)
    if database == DEFAULT_DATABASE:
        return create_engine(
            url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    return create_engine(url, connect_args={"check_same_thread": False})


class Database:
    """The SQLite database every catalog shares.

    The application answers requests on several threads and a SQLite connection is
    not thread-safe unless it is serialized, so every store operation holds one lock
    rather than opening a connection per request — and one engine for all the catalogs,
    so a write to one cannot find another holding the file.
    """

    def __init__(self, database: str | Path = DEFAULT_DATABASE) -> None:
        self.engine = _create_engine(str(database))
        self.lock = threading.Lock()
        with self.lock:
            # `create_all` checks for each table first, so a file an earlier version
            # wrote keeps its rows and gains only the tables it does not have yet.
            Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        """A unit of work on this database; the caller holds `lock` around it.

        Committing does not expire the loaded rows, so a store returns the values it
        just wrote: a replace reads the row it stored instead of re-selecting it, and
        no caller reads a row after `commit` only to have it reload behind them.
        """

        return Session(self.engine, expire_on_commit=False)

    def store(self, table: str, kind: str) -> DocumentStore:
        """The catalog in `table`, whose resources are of type `kind` (API §7.2)."""

        record = _CATALOGS.get(table)
        if record is None:
            raise ValueError(f"{table} is not a catalog table")
        return DocumentStore(self, record, kind)

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

    def __init__(
        self, database: Database, record: type[CatalogRecord], kind: str
    ) -> None:
        self._database = database
        self._record = record
        self._kind = kind

    def _document(self, row: CatalogRecord) -> StoredDocument:
        return StoredDocument(
            self._kind, row.id, json.loads(row.document), row.created_at, row.updated_at
        )

    def all(self) -> list[StoredDocument]:
        """Every stored document, in the catalog's own order: creation, then id."""

        with self._database.lock, self._database.session() as session:
            rows = session.scalars(
                select(self._record).order_by(self._record.created_at, self._record.id)
            ).all()
            return [self._document(row) for row in rows]

    def get(self, resource_id: str) -> StoredDocument | None:
        """The stored document named `resource_id`, or `None`."""

        with self._database.lock, self._database.session() as session:
            row = session.get(self._record, resource_id)
            return None if row is None else self._document(row)

    def insert(self, resource_id: str, document: dict[str, Any]) -> StoredDocument | None:
        """Store a new document; `None` when its id is already in the catalog (AR-104)."""

        stored = StoredDocument(self._kind, resource_id, document, _now(), None)
        with self._database.lock, self._database.session() as session:
            session.add(
                self._record(
                    id=stored.id,
                    document=json.dumps(document),
                    created_at=stored.created_at,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                # A rejected duplicate rolls back its own write rather than leaving a
                # transaction holding the database.
                session.rollback()
                return None
        return stored

    def replace(self, resource_id: str, document: dict[str, Any]) -> StoredDocument | None:
        """Overwrite the stored document and stamp `updated_at`; `None` when absent."""

        with self._database.lock, self._database.session() as session:
            row = session.get(self._record, resource_id)
            if row is None:
                return None
            row.document = json.dumps(document)
            row.updated_at = _now()
            session.commit()
            return self._document(row)

    def delete(self, resource_id: str) -> bool:
        """Remove a document; `False` when it was not stored."""

        with self._database.lock, self._database.session() as session:
            row = session.get(self._record, resource_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True


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
        with self._database.lock, self._database.session() as session:
            session.add(
                AssetRecord(
                    id=stored.id,
                    name=stored.name,
                    content_type=stored.content_type,
                    size_bytes=stored.size_bytes,
                    sha256=stored.sha256,
                    content=stored.content,
                    created_at=stored.created_at,
                )
            )
            session.commit()
        return stored

    @staticmethod
    def _asset(row: AssetRecord) -> StoredAsset:
        return StoredAsset(
            row.id,
            row.name,
            row.content_type,
            row.size_bytes,
            row.sha256,
            row.content,
            row.created_at,
        )

    def all(self, content_type: str | None = None) -> list[StoredAsset]:
        """Stored assets, newest first, optionally only those of `content_type`.

        Newest first is the order every §6.1 collection answers with by default, and
        the id breaks a tie so a page boundary can neither repeat nor skip a row.
        """

        statement = select(AssetRecord)
        if content_type is not None:
            statement = statement.where(AssetRecord.content_type == content_type)
        statement = statement.order_by(AssetRecord.created_at.desc(), AssetRecord.id.desc())
        with self._database.lock, self._database.session() as session:
            rows = session.scalars(statement).all()
            return [self._asset(row) for row in rows]

    def get(self, asset_id: str) -> StoredAsset | None:
        """The stored asset named `asset_id`, or `None`."""

        with self._database.lock, self._database.session() as session:
            row = session.get(AssetRecord, asset_id)
            return None if row is None else self._asset(row)

    def delete(self, asset_id: str) -> bool:
        """Remove an asset; `False` when it was not stored."""

        with self._database.lock, self._database.session() as session:
            row = session.get(AssetRecord, asset_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True


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
    def _request(row: IdempotencyRecord) -> IdempotentRequest:
        return IdempotentRequest(row.key, row.fingerprint, row.resource_id, row.created_at)

    @staticmethod
    def _live_since() -> str:
        """The oldest `created_at` a key still answers for: §10's 24 hours, as a stamp."""

        return _timestamp(datetime.now(UTC) - IDEMPOTENCY_WINDOW)

    def find(self, key: str) -> IdempotentRequest | None:
        """The live record for `key`, or `None` when it is unused or its day is past."""

        with self._database.lock, self._database.session() as session:
            row = session.get(IdempotencyRecord, key)
            if row is None or row.created_at < self._live_since():
                return None
            return self._request(row)

    def record(
        self, key: str, fingerprint: str, resource_id: str
    ) -> IdempotentRequest | None:
        """Claim `key` for this response; the record that already holds it when it cannot."""

        with self._database.lock, self._database.session() as session:
            # A row past its day is not a claim, and no sweeper runs: dropping every
            # expired row here keeps a key that is never reused from staying for good.
            session.execute(
                delete(IdempotencyRecord).where(
                    IdempotencyRecord.created_at < self._live_since()
                )
            )
            statement = (
                sqlite_insert(IdempotencyRecord)
                .values(
                    key=key,
                    fingerprint=fingerprint,
                    resource_id=resource_id,
                    created_at=_now(),
                )
                .on_conflict_do_nothing()
            )
            claimed = session.execute(statement).rowcount == 1
            session.commit()
            row = session.get(IdempotencyRecord, key)
        if claimed or row is None:
            return None
        return self._request(row)

    def forget(self, key: str) -> None:
        """Release `key`, for a record whose resource no longer exists."""

        with self._database.lock, self._database.session() as session:
            session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.key == key))
            session.commit()


class JobStore:
    """The `render_jobs` table: accepted submissions and the status each has reached.

    A job is stored when the API accepts it and moves only along the transitions API
    §8.7 documents, so its status is a fact of the store rather than a value a caller
    can write over.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def _job(self, row: RenderJobRecord) -> StoredJob:
        return StoredJob(
            row.id,
            row.status,
            json.loads(row.request),
            row.progress,
            None if row.error is None else json.loads(row.error),
            row.created_at,
            row.updated_at,
            row.completed_at,
        )

    def all(self) -> list[StoredJob]:
        """Every accepted job, in the store's own order: creation, then id."""

        with self._database.lock, self._database.session() as session:
            rows = session.scalars(
                select(RenderJobRecord).order_by(
                    RenderJobRecord.created_at, RenderJobRecord.id
                )
            ).all()
            return [self._job(row) for row in rows]

    def get(self, job_id: str) -> StoredJob | None:
        """The job named `job_id`, or `None`."""

        with self._database.lock, self._database.session() as session:
            row = session.get(RenderJobRecord, job_id)
            return None if row is None else self._job(row)

    def insert(self, job_id: str, request: dict[str, Any]) -> StoredJob:
        """Store an accepted submission as a `queued` job.

        The id is the server's to choose (§8.7), so there is no client-supplied
        identity to report as a duplicate and no insert that can lose the race.
        """

        job = StoredJob(job_id, JOB_QUEUED, request, 0, None, _now(), None, None)
        with self._database.lock, self._database.session() as session:
            session.add(
                RenderJobRecord(
                    id=job.id,
                    status=job.status,
                    request=json.dumps(request),
                    progress=job.progress,
                    error=None,
                    created_at=job.created_at,
                )
            )
            session.commit()
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

        with self._database.lock, self._database.session() as session:
            row = session.get(RenderJobRecord, job_id)
            if row is None:
                return None
            stored = self._job(row)
            if status not in JOB_TRANSITIONS[stored.status]:
                raise ValueError(f"a {stored.status} job cannot become {status}")
            now = _now()
            job = StoredJob(
                stored.id,
                status,
                stored.request,
                100
                if status == "completed"
                else (stored.progress if progress is None else progress),
                error if status == "failed" else None,
                stored.created_at,
                now,
                now if status in JOB_TERMINAL_STATUSES else None,
            )
            row.status = job.status
            row.progress = job.progress
            row.error = None if job.error is None else json.dumps(job.error)
            row.updated_at = job.updated_at
            row.completed_at = job.completed_at
            session.commit()
        return job
