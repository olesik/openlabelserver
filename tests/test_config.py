"""Tests for `backend/config.py` and the application built from its settings.

The settings are the whole of what a deployment tells the service, so these tests
cover the defaults, the two variables that configure it, and the one wrong value that
has to stop the application instead of being defaulted away.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import auth, config, main, storage  # noqa: E402

# API §4.2 and §4.6: one principal with a Bearer token and an API key, so the loaded
# credentials can be asked for both.
PRINCIPALS = {
    "principals": [
        {
            "id": "prn_owner",
            "username": "owner",
            "roles": ["admin"],
            "bearer_token": "owner-token",
            "api_key": "ols_owner_key",
        }
    ]
}


def test_an_empty_environment_is_the_process_local_default() -> None:
    settings = config.Settings.from_environment(environ={})

    assert settings.database == storage.DEFAULT_DATABASE
    assert settings.credentials is None


def test_the_configured_database_is_read() -> None:
    settings = config.Settings.from_environment(
        environ={storage.DATABASE_ENV: "catalog.sqlite"}
    )

    assert settings.database == "catalog.sqlite"


def test_an_explicit_database_wins_over_the_environment() -> None:
    settings = config.Settings.from_environment(
        "explicit.sqlite", environ={storage.DATABASE_ENV: "configured.sqlite"}
    )

    assert settings.database == "explicit.sqlite"


def test_an_empty_variable_is_the_default() -> None:
    """Compose passes a variable it means to leave out as an empty string."""

    settings = config.Settings.from_environment(
        environ={storage.DATABASE_ENV: "", auth.AUTH_ENV: ""}
    )

    assert settings.database == storage.DEFAULT_DATABASE
    assert settings.credentials is None


def test_credentials_are_read_and_their_principals_indexed() -> None:
    settings = config.Settings.from_environment(
        environ={auth.AUTH_ENV: json.dumps(PRINCIPALS)}
    )

    assert settings.credentials is not None
    principal = settings.credentials.principal("Bearer owner-token", None)
    assert principal is not None
    assert principal.id == "prn_owner"
    assert settings.credentials.principal(None, "ols_owner_key") is not None


def test_a_malformed_auth_configuration_names_the_variable() -> None:
    with pytest.raises(ValueError, match=auth.AUTH_ENV):
        config.Settings.from_environment(environ={auth.AUTH_ENV: "not json"})


def test_the_application_takes_the_configured_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the setting the application would open no file at all."""

    path = tmp_path / "configured.sqlite"
    monkeypatch.setenv(storage.DATABASE_ENV, str(path))

    main.create_app()

    assert path.exists()
