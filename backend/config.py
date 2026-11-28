"""Server configuration (B2 — Storage).

Every setting the service reads from its environment is loaded here, once, when the
application is built, so there is one answer to "how is this deployment configured"
rather than an `environ.get` at each use. Two variables configure the backend: the
database path (B2's SQLite file) and the credential configuration API §4.1 describes.

The rest of the process configuration belongs to the entrypoint rather than the
application. `scripts/entrypoints/backend.sh` takes `OLS_PORT` for the port uvicorn
binds and `OLS_MODE` for stub or application, and the Compose files pass `OLS_ENV` and
`OLS_LOG_LEVEL` to the services that consume them. No backend code reads those, so
they are not restated here: a setting with no consumer is configuration nobody can
check.

An unset variable and one set to the empty string mean the same thing — the default —
because that is how Compose passes a variable a deployment leaves out. A variable that
is set to something wrong is not defaulted; `OPENLABEL_AUTH` already names the
principal and field at fault (`backend/auth.py`), and the message this module raises
names the variable.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from backend import auth, storage


@dataclass(frozen=True)
class Settings:
    """How this deployment is configured: where it stores and who may call it.

    `database` is the SQLite path the catalogs, assets and jobs share; the process-local
    default keeps them for the life of the process rather than for the life of a
    deployment, which is a configuration default and not a durability claim.
    `credentials` is `None` when `OPENLABEL_AUTH` is absent, which is API §4.1's
    authentication-off development mode rather than an empty credential set.
    """

    database: str | Path = storage.DEFAULT_DATABASE
    credentials: auth.Credentials | None = None

    @classmethod
    def from_environment(
        cls,
        database: str | Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> Settings:
        """Read the environment, with `database` overriding the configured path.

        `database` is the injection point tests and the conformance suite use, and it
        wins over `OPENLABEL_DATABASE` because it is the caller's explicit choice. An
        empty `OPENLABEL_AUTH` is no configuration rather than an empty list of
        principals, which is how earlier builds already read it.
        """

        values = os.environ if environ is None else environ
        chosen = database or values.get(storage.DATABASE_ENV) or storage.DEFAULT_DATABASE
        configured_auth = values.get(auth.AUTH_ENV) or None
        credentials = (
            None if configured_auth is None else auth.Credentials.from_json(configured_auth)
        )
        return cls(database=chosen, credentials=credentials)
