# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/signing.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Asymmetric signatures (Ed25519, RFC 8032) for repair candidates, approvals and backup manifests.

An HMAC secret has to be on both sides of a check, so whoever can verify a candidate can also forge
one. With a key pair the signer holds the private key (a 32-byte seed) and the verifier only the public
key: a host that checks a backup or a candidate can no longer make one.

This project has no required dependencies, so the algorithm is the reference one of RFC 8032 written with
Python integers. It is checked against the test vectors of the RFC. Two limits, stated plainly:

  * the pure version is not constant-time: sign on the machine of the operator that holds the seed, never
    on a shared host where another process could time it. When the `cryptography` package is installed
    (an optional dependency, OpenSSL underneath) the operations that use the seed - deriving the public
    key and signing - go through it instead and are constant-time; `signing_backend()` says which one is
    in use and `HYDRA_UMC_DEV_SERVER_PURE_ED25519=1` forces the pure one. Verification handles only public
    data, so it always uses the pure code and is unaffected.
  * the pure version is slower than a C library (a few milliseconds per signature), which does not matter
    for a manifest or a candidate.

Keys travel as text: `ed25519-seed:<64 hex>` (private, keep it 0600 and out of version control) and
`ed25519-public:<64 hex>`; a signature is `ed25519:<128 hex>`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from typing import Any

from .config import ConfigValidationError

SEED_PREFIX = "ed25519-seed:"
PUBLIC_PREFIX = "ed25519-public:"
SIGNATURE_PREFIX = "ed25519:"

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)
_HEX32 = re.compile(r"^[0-9a-f]{64}$")
_HEX64 = re.compile(r"^[0-9a-f]{128}$")


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _I % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)  # extended coordinates (X, Y, Z, T)


def _add(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    a1 = (a[1] - a[0]) * (b[1] - b[0]) % _P
    b1 = (a[1] + a[0]) * (b[1] + b[0]) % _P
    c = 2 * a[3] * b[3] * _D % _P
    d = 2 * a[2] * b[2] % _P
    e, f, g, h = b1 - a1, d - c, d + c, b1 + a1
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(scalar: int, point: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    result = (0, 1, 1, 0)
    while scalar > 0:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _equal(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _compress(point: tuple[int, int, int, int]) -> bytes:
    zinv = _inv(point[2])
    x, y = point[0] * zinv % _P, point[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data: bytes) -> tuple[int, int, int, int] | None:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _expand(seed: bytes) -> tuple[int, bytes]:
    digest = _sha512(seed)
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return scalar, digest[32:]


def _hash_int(data: bytes) -> int:
    return int.from_bytes(_sha512(data), "little")


def _native_ed25519() -> Any:
    """The `cryptography` Ed25519 module when it can be used, else None. Looked up on every call so a test can switch it."""
    if os.environ.get("HYDRA_UMC_DEV_SERVER_PURE_ED25519", "").strip() == "1":
        return None
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: PLC0415 - optional dependency
    except ImportError:
        return None
    return ed25519


def signing_backend() -> str:
    """`native` when the seed-dependent operations go through the `cryptography` package, `pure` otherwise."""
    return "native" if _native_ed25519() is not None else "pure"


def _pure_public_key_bytes(seed: bytes) -> bytes:
    scalar, _ = _expand(seed)
    return _compress(_mul(scalar, _G))


def public_key_bytes(seed: bytes) -> bytes:
    if len(seed) != 32:
        raise ConfigValidationError("an Ed25519 seed is 32 bytes")
    native = _native_ed25519()
    if native is not None:
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

        key = native.Ed25519PrivateKey.from_private_bytes(seed)
        return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _pure_public_key_bytes(seed)


def sign_bytes(seed: bytes, message: bytes) -> bytes:
    if len(seed) != 32:
        raise ConfigValidationError("an Ed25519 seed is 32 bytes")
    native = _native_ed25519()
    if native is not None:
        return native.Ed25519PrivateKey.from_private_bytes(seed).sign(message)
    return _pure_sign_bytes(seed, message)


def _pure_sign_bytes(seed: bytes, message: bytes) -> bytes:
    scalar, prefix = _expand(seed)
    public = _compress(_mul(scalar, _G))
    r = _hash_int(prefix + message) % _L
    big_r = _compress(_mul(r, _G))
    k = _hash_int(big_r + public + message) % _L
    s = (r + k * scalar) % _L
    return big_r + int.to_bytes(s, 32, "little")


def verify_bytes(public: bytes, message: bytes, signature: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    a = _decompress(public)
    r = _decompress(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    k = _hash_int(signature[:32] + public + message) % _L
    return _equal(_mul(s, _G), _add(r, _mul(k, a)))


# ---------------------------------------------------------------------------
# Text forms and the documents that get signed
# ---------------------------------------------------------------------------
def generate_key_pair(random: Any = os.urandom) -> tuple[str, str]:
    """A new `(seed text, public key text)`."""
    seed = random(32)
    return SEED_PREFIX + seed.hex(), PUBLIC_PREFIX + public_key_bytes(seed).hex()


def public_key_from_seed(seed_text: str) -> str:
    return PUBLIC_PREFIX + public_key_bytes(_parse(seed_text, SEED_PREFIX, _HEX32, "private key")).hex()


def _parse(text: str, prefix: str, pattern: re.Pattern[str], what: str) -> bytes:
    value = text.strip()
    if not value.startswith(prefix) or not pattern.fullmatch(value[len(prefix):]):
        raise ConfigValidationError(f"the {what} must look like '{prefix}<hex>'")
    return bytes.fromhex(value[len(prefix):])


def is_public_key(text: str) -> bool:
    return text.strip().startswith(PUBLIC_PREFIX)


def canonical_bytes(body: dict[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_body(seed_text: str, body: dict[str, Any]) -> str:
    seed = _parse(seed_text, SEED_PREFIX, _HEX32, "private key")
    return SIGNATURE_PREFIX + sign_bytes(seed, canonical_bytes(body)).hex()


def verify_body(public_text: str, body: dict[str, Any], signature: str) -> bool:
    """Whether `signature` is the Ed25519 signature of `body` by the owner of `public_text`.
    A malformed key or signature is simply not valid."""
    try:
        public = _parse(public_text, PUBLIC_PREFIX, _HEX32, "public key")
    except ConfigValidationError:
        return False
    if not signature.startswith(SIGNATURE_PREFIX) or not _HEX64.fullmatch(signature[len(SIGNATURE_PREFIX):]):
        return False
    return verify_bytes(public, canonical_bytes(body), bytes.fromhex(signature[len(SIGNATURE_PREFIX):]))


def signature_matches(key_text: str, body: dict[str, Any], signature: str) -> bool:
    """One check for either kind of key: `ed25519-public:...` verifies an Ed25519 signature, anything
    else is an HMAC secret. The kinds never mix: a public key does not accept an HMAC signature (no
    downgrade) and a secret does not accept an Ed25519 one."""
    if not signature:
        return False
    if is_public_key(key_text):
        return verify_body(key_text, body, signature)
    if signature.startswith(SIGNATURE_PREFIX):
        return False
    mac = hmac.new(key_text.encode("utf-8"), canonical_bytes(body), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, mac)
