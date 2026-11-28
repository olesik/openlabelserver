"""SQLAlchemy models of the tables the stored resources live in (B2 — Storage).

The row shape is the one API §7.1 and §8.3 to §8.7 publish: a catalogs row is only the
identity, the domain document and the two timestamps, an asset row adds the metadata
OpenAPI's `Asset` schema names beside its bytes, and a render job row keeps the
submission §8.7 accepted and the status it has reached. `backend/storage.py` creates
these tables in SQLite and is the only code that reads or writes them, so the models
are the storage layer's schema rather than a second description of the API.

A catalog keeps one table per resource type instead of one table with a `kind` column,
because the `templates`, `stocks` and `calibrations` tables an existing
`OPENLABEL_DATABASE` already holds stay readable without a migration. Their rows have
the same four columns, which `CatalogRecord` declares once.
"""

from __future__ import annotations

from sqlalchemy import Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """The metadata every table of the storage layer is created from."""


class CatalogRecord(Base):
    """One catalog row: the identity, the domain document and its §7.1 timestamps.

    The document is the JSON text the client submitted, stored as text rather than as
    a database-native type so a row reads back exactly as it was written.
    """

    __abstract__ = True

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str | None] = mapped_column(String, nullable=True)


class TemplateRecord(CatalogRecord):
    """The `templates` catalog (API §8.3)."""

    __tablename__ = "templates"


class StockRecord(CatalogRecord):
    """The `stocks` catalog (API §8.4)."""

    __tablename__ = "stocks"


class CalibrationRecord(CatalogRecord):
    """The `calibrations` catalog (API §8.5)."""

    __tablename__ = "calibrations"


class AssetRecord(Base):
    """The `assets` table: a file with the metadata API §8.6 publishes about it.

    The bytes are stored as uploaded, and the size and digest are computed from those
    same bytes, so a row cannot describe something other than what it serves.
    """

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class RenderJobRecord(Base):
    """The `render_jobs` table: an accepted submission and the status it reached.

    §5.5's `error` is JSON text of the failure detail, present only once a job fails,
    and `completed_at` is the moment a terminal status was stored.
    """

    __tablename__ = "render_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)


class IdempotencyRecord(Base):
    """The `idempotency` table: which response each §10 key already answered.

    A row records a fingerprint of the request body and the id the response named, not
    the response itself, so a replay is rebuilt from the resource that exists.
    """

    __tablename__ = "idempotency"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    resource_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
