# =============================================================================
# HYDRA-UMC-SDK - tools/canonical/server_identity.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The signed token of HYDRA-UMC-SERVER as the identity of a caller of a Python service on the standard library HTTP server, written once.

This file has a single canonical copy (`tools/canonical/server_identity.py` of HYDRA-UMC-SDK) that is vendored, byte for byte, into the services that list it in
`PER_REPOSITORY_FILES` of `tools/sync_repo_tools.py`; the script keeps the copies identical. It needs nothing but the standard library, and nothing in it is
specific to a service: the name of the environment variable comes from the package the file sits in.

The SERVER is the one issuer of identity of the family. A service that carries this file can also ask the SERVER who is calling, instead of (or besides) a token of its
own. It is an opt-in, and the default changes nothing:

* Off (the default): no identity key is configured and the service behaves exactly as before, with its own bearer token or none.
* On (`--identity-key-file FILE`, or `HYDRA_UMC_<SERVICE>_IDENTITY_KEY_FILE=FILE`, where `<SERVICE>` is the package name in capitals, for example
  `HYDRA_UMC_VISION_NODE_IDENTITY_KEY_FILE`): the file holds the signing key of the SERVER (its `JWT_SECRET`, at least 32 characters, never read from the command line)
  and a request is accepted when it carries a valid token of the SERVER, or the token of the service itself when it has one. With the key on, a request with no
  credential is refused even on a service that had no token of its own: the switch is how an operator closes a service that was open on loopback.

What is checked in a token of the SERVER: a JWT (RFC 7519) whose algorithm is exactly HS256 (`none` and any other are refused), the signature (constant time), a present
and future `exp`, an `nbf` that has passed, a non-empty `username` and a role of `admin`, `operator` or `viewer`. A request that reads (GET, HEAD, OPTIONS) is accepted for
any of the three roles; a request that changes something needs `admin` or `operator`. What a service cannot check is a revocation the SERVER keeps on its side (a changed
password, a deleted account): keep `JWT_EXPIRES_IN` of the SERVER short for the accounts that call services. The key is shared with the services that verify, because the
signature is symmetric: a service that can verify a token could also forge one, so the key file must be readable only by the group of that service.

With the key on, `GET /health` and `GET /stats` need an identity too: nothing is open. The probe of a container therefore signs a short-lived token of its own with the same key
file (`python -m <package>.server_identity probe --port PORT [--path /health]`, exit 0 when the service answers 200), which never leaves the machine and needs no
token of the SERVER.

The service takes the key at start (`identity_key_from`), keeps it on its server object, and asks `accepts(handler, own_token, key)` where it used to compare the token.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import json
import math
import os
import time
from dataclasses import dataclass
from hashlib import sha256
from http.server import BaseHTTPRequestHandler
from urllib.error import URLError
from urllib.request import Request, urlopen

_PACKAGE = (__package__ or __name__).split(".", 1)[0]
ENV_IDENTITY_KEY_FILE = f"{_PACKAGE.upper()}_IDENTITY_KEY_FILE"
MIN_KEY_LENGTH = 32
MAX_TOKEN_CHARS = 4096
IAT_SKEW_SECONDS = 5  # clock difference tolerated for an `iat` in the future, as the SERVER does
ROLES = ("admin", "operator", "viewer")
WRITE_ROLES = frozenset({"admin", "operator"})
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class IdentityError(Exception):
    """The caller has no valid identity; `str()` is the reason, which names no key, token or path."""


@dataclass(frozen=True)
class Identity:
    username: str
    role: str


def load_identity_key(path: str) -> bytes:
    """Read the verification key from a file. Raises ValueError (the message never holds the key)."""
    try:
        with open(path, encoding="utf-8") as handle:
            key = handle.read().strip()
    except OSError as error:
        raise ValueError(f"cannot read the identity key file: {error.strerror or 'unreadable'}") from error
    if len(key) < MIN_KEY_LENGTH:
        raise ValueError(f"the identity key must have at least {MIN_KEY_LENGTH} characters")
    return key.encode("utf-8")


def identity_key_from(flag_path: str | None = None, environ: dict[str, str] | None = None) -> bytes | None:
    """The key named by the flag of the command line, or else by the environment variable; None when neither names one (the identity of the SERVER is off)."""
    env = os.environ if environ is None else environ
    path = (flag_path or env.get(ENV_IDENTITY_KEY_FILE, "")).strip()
    return load_identity_key(path) if path else None


def _b64(segment: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (binascii.Error, ValueError) as error:
        raise IdentityError("the token is malformed") from error


def _json_part(segment: str) -> dict:
    try:
        value = json.loads(_b64(segment).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise IdentityError("the token is malformed") from error
    if not isinstance(value, dict):
        raise IdentityError("the token is malformed")
    return value


def verify_token(token: str | None, key: bytes, *, now: float | None = None) -> Identity:
    """The identity in a signed token of the SERVER, or IdentityError saying why there is none."""
    if not token:
        raise IdentityError("a signed token of HYDRA-UMC-SERVER is required")
    if len(token) > MAX_TOKEN_CHARS:
        raise IdentityError("the token is malformed")
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise IdentityError("the token is malformed")
    if _json_part(parts[0]).get("alg") != "HS256":
        raise IdentityError("the token algorithm is not accepted (only HS256)")
    expected = hmac.new(key, f"{parts[0]}.{parts[1]}".encode("ascii", "replace"), sha256).digest()
    if not hmac.compare_digest(expected, _b64(parts[2])):
        raise IdentityError("the token signature is not valid")
    claims = _json_part(parts[1])
    moment = time.time() if now is None else now
    exp = claims.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)) or not math.isfinite(exp):  # NaN compares false with everything: it would never expire
        raise IdentityError("the token has no expiry")
    if exp <= moment:
        raise IdentityError("the token has expired")
    nbf = claims.get("nbf")
    if nbf is not None and (isinstance(nbf, bool) or not isinstance(nbf, (int, float)) or not math.isfinite(nbf) or nbf > moment):
        raise IdentityError("the token is not valid yet")
    iat = claims.get("iat")
    if iat is not None and (isinstance(iat, bool) or not isinstance(iat, (int, float)) or not math.isfinite(iat) or iat > moment + IAT_SKEW_SECONDS):
        raise IdentityError("the token was issued in the future")
    username, role = claims.get("username"), claims.get("role")
    if not isinstance(username, str) or not username:
        raise IdentityError("the token names no user")
    if role not in ROLES:
        raise IdentityError("the token carries no known role")
    return Identity(username, role)


def _presented(handler: BaseHTTPRequestHandler) -> str:
    scheme, _, presented = handler.headers.get("Authorization", "").partition(" ")
    return presented.strip() if scheme == "Bearer" else ""


def accepts(handler: BaseHTTPRequestHandler, own_token: str, key: bytes | None) -> bool:
    """Whether the request may go on.

    No key (the identity of the SERVER is off): the earlier rule, which is open when the service has no token and otherwise needs exactly that bearer token.
    With a key: a valid token of the SERVER (any role to read, `admin` or `operator` to change), or the token of the service when it has one. Nothing else, and never
    open. The identity that was accepted is left on the handler as `identity` (None when the service's own token was used).
    """
    presented = _presented(handler)
    if key is None:
        return not own_token or (bool(presented) and hmac.compare_digest(presented.encode("utf-8"), own_token.encode("utf-8")))
    handler.identity = None  # type: ignore[attr-defined]
    if own_token and presented and hmac.compare_digest(presented.encode("utf-8"), own_token.encode("utf-8")):
        return True
    if presented.count(".") != 2:
        return False
    try:
        identity = verify_token(presented, key)
    except IdentityError:
        return False
    if handler.command not in READ_METHODS and identity.role not in WRITE_ROLES:
        return False
    handler.identity = identity  # type: ignore[attr-defined]
    return True


def sign_token(key: bytes, username: str = "health-probe", role: str = "viewer", ttl_seconds: int = 60, *, now: float | None = None) -> str:
    """A short-lived token of the SERVER format, signed with the shared key (what the probe of a container presents; a viewer can only read)."""
    def part(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    moment = time.time() if now is None else now
    head = part(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    body = part(json.dumps({"username": username, "role": role, "exp": int(moment) + ttl_seconds}).encode("utf-8"))
    signature = hmac.new(key, f"{head}.{body}".encode("ascii"), sha256).digest()
    return f"{head}.{body}.{part(signature)}"


def probe(port: int, path: str = "/health", key_file: str | None = None, host: str = "127.0.0.1", timeout: float = 3.0) -> bool:
    """Ask the service on this machine for `path`, presenting a token signed with the identity key when one is configured; True when it answers 200."""
    key = identity_key_from(key_file)
    headers = {"Authorization": f"Bearer {sign_token(key)}"} if key is not None else {}
    try:
        with urlopen(Request(f"http://{host}:{port}{path}", headers=headers), timeout=timeout) as response:  # noqa: S310 - http on loopback by design
            return response.status == 200
    except (URLError, OSError, ValueError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"python -m {_PACKAGE}.server_identity", description="Health probe for a service whose identity of HYDRA-UMC-SERVER is on.")
    parser.add_argument("command", choices=("probe",))
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--path", default="/health")
    parser.add_argument("--key-file", default=None, help=f"the identity key file (or {ENV_IDENTITY_KEY_FILE})")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    try:
        return 0 if probe(args.port, args.path, args.key_file, args.host) else 1
    except ValueError as error:
        print(f"error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
