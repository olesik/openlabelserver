"""Bearer-token and API-key authentication for the `/v1` API (API Spec §4).

API §4.2 names the two schemes and §4.6 the roles, but §4.3 and §4.4 — token
issuance and API-key lifecycle — are not implemented yet, so the credentials a
request presents come from server configuration: `OPENLABEL_AUTH` holds one JSON
object, `{"principals": [{"id": …, "username": …, "roles": […], "bearer_token": …}]}`,
each principal carrying the §4.5 identity and at least one credential. Without the
variable authentication is off and the service answers as the single implicit
administrator of §4.1.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# API Spec §4.6: the roles v1.0 defines.
ROLES = ("admin", "operator", "viewer")

# API Spec §4.2: the headers the two schemes read.
BEARER_HEADER = "authorization"
API_KEY_HEADER = "x-api-key"

# API Spec §4.4: an API key is an opaque server-issued `ols_` string.
API_KEY_PREFIX = "ols_"

# API Spec §4.7: the challenge a `401` carries.
CHALLENGE = 'Bearer realm="OpenLabelServer"'

# API Spec §8.1: the system endpoints answer without credentials.
PUBLIC_PATHS = frozenset({"/v1/health", "/v1/info"})

# API Spec §4.6: only `admin` has write access; every role may read.
READ_ROLES = frozenset(ROLES)
WRITE_ROLES = frozenset({"admin"})

# API Spec §4.1: the server configuration that enables authentication.
AUTH_ENV = "OPENLABEL_AUTH"


@dataclass(frozen=True)
class Principal:
    """The §4.5 identity a credential names, with the §4.6 roles it holds."""

    id: str
    username: str
    roles: tuple[str, ...]

    def permits(self, roles: frozenset[str]) -> bool:
        """Whether the principal holds one of the roles an operation accepts."""

        return bool(roles.intersection(self.roles))


class Credentials:
    """The configured principals, indexed by the credential each one presents."""

    def __init__(
        self, tokens: Mapping[str, Principal], keys: Mapping[str, Principal]
    ) -> None:
        self._tokens = dict(tokens)
        self._keys = dict(keys)

    @classmethod
    def from_json(cls, configured: str) -> Credentials:
        """Read the configuration `OPENLABEL_AUTH` holds, or say what is wrong with it."""

        try:
            config = json.loads(configured)
        except json.JSONDecodeError as error:
            raise ValueError(f"{AUTH_ENV} is not valid JSON: {error.msg}.") from None
        if not isinstance(config, dict):
            raise ValueError(f'{AUTH_ENV} must be a JSON object carrying "principals".')
        return cls.from_config(config)

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> Credentials:
        """Index a configuration's principals by the Bearer token and API key each names."""

        entries = config.get("principals")
        if not isinstance(entries, list) or not entries:
            raise ValueError(f'{AUTH_ENV} must carry a non-empty "principals" array.')
        tokens: dict[str, Principal] = {}
        keys: dict[str, Principal] = {}
        for position, entry in enumerate(entries):
            principal, token, key = _principal(entry, position)
            if token is not None:
                _claim(tokens, token, principal, "bearer_token")
            if key is not None:
                _claim(keys, key, principal, "api_key")
        return cls(tokens, keys)

    def principal(self, authorization: str | None, api_key: str | None) -> Principal | None:
        """The principal §4.2 selects: the Bearer token first, the API key without one."""

        if authorization is not None:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer":
                return None
            return self._tokens.get(token.strip())
        if api_key is not None:
            return self._keys.get(api_key)
        return None


def roles_for(method: str) -> frozenset[str]:
    """The §4.6 roles an operation accepts: every role reads, `admin` alone writes."""

    return READ_ROLES if method in ("GET", "HEAD", "OPTIONS") else WRITE_ROLES


def _text(entry: Mapping[str, Any], field: str, position: int) -> str:
    """One required string of a principal, or the configuration error it is not."""

    value = entry.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f'principal {position} needs a non-empty "{field}" string.')
    return value


def _principal(entry: Any, position: int) -> tuple[Principal, str | None, str | None]:
    """One configured principal and the credentials it presents."""

    if not isinstance(entry, dict):
        raise ValueError(f"principal {position} is not a JSON object.")
    identifier = _text(entry, "id", position)
    username = _text(entry, "username", position)
    roles = entry.get("roles")
    if not isinstance(roles, list) or not roles or not all(isinstance(role, str) for role in roles):
        raise ValueError(f'principal {position} needs a non-empty "roles" array of strings.')
    unknown = sorted(set(roles) - set(ROLES))
    if unknown:
        raise ValueError(f'principal {position} names roles outside §4.6: {", ".join(unknown)}.')
    if len(set(roles)) != len(roles):
        raise ValueError(f"principal {position} repeats a role.")
    token = entry.get("bearer_token")
    key = entry.get("api_key")
    if token is None and key is None:
        raise ValueError(f'principal {position} needs a "bearer_token" or an "api_key".')
    if token is not None and (not isinstance(token, str) or not token):
        raise ValueError(f'principal {position} has an empty "bearer_token".')
    if key is not None:
        if not isinstance(key, str) or not key:
            raise ValueError(f'principal {position} has an empty "api_key".')
        if not key.startswith(API_KEY_PREFIX):
            raise ValueError(
                f'principal {position} names an api_key without the "{API_KEY_PREFIX}" prefix.'
            )
    return Principal(identifier, username, tuple(roles)), token, key


def _claim(
    index: dict[str, Principal], credential: str, principal: Principal, field: str
) -> None:
    """Index one credential, refusing a second principal that presents the same one."""

    if credential in index:
        raise ValueError(
            f'the {field} of principal "{principal.id}" is already configured.'
        )
    index[credential] = principal
