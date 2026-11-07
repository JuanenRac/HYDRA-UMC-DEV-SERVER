# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/trust_store.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The trust store: which public keys a host accepts, each under an alias.

A host that verifies a repair candidate, an approval or a backup manifest needs the PUBLIC key of whoever signed it and
nothing else. The store is a small JSON document that maps an alias ("Ana bench 1", "release approver") to a public key
(`ed25519-public:<64 hex>`), plus a list of revoked aliases:

    {"trusted_keys": {"Ana bench 1": "ed25519-public:..."}, "revoked": ["Old laptop"]}

Rules, all on the safe side:

  * the store holds public keys only. A private seed (`ed25519-seed:...`) found in it is refused with the alias named (never the
    value), and the entry is left out: a store that leaked would have leaked a signing key;
  * an entry that is malformed is left out and named in the problems; a key that is left out is simply not trusted;
  * a revoked alias never verifies, whatever its key signed;
  * an alias is 1 to 40 letters, digits, spaces or `._@-`;
  * a signature is attributed to the first alias, in alphabetical order, whose key verifies it, so "signed by Ana" is a statement the
    host can make and an unknown signer is `None`, not a pass.

The private key never leaves the approver: signing happens with `ops sign-backup` or `signed_ed25519` on the approver's own machine, and
this module has no function that reads a seed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ConfigValidationError, load_json_document
from .signing import PUBLIC_PREFIX, SEED_PREFIX, verify_body

TRUST_KEY = "trusted_keys"
REVOKED_KEY = "revoked"
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{0,39}$")
_PUBLIC = re.compile(r"^" + re.escape(PUBLIC_PREFIX) + r"[0-9a-f]{64}$")


def valid_alias(alias: object) -> bool:
    return isinstance(alias, str) and bool(_ALIAS.match(alias)) and alias == alias.strip()


@dataclass(frozen=True)
class TrustStore:
    keys: dict[str, str] = field(default_factory=dict)
    revoked: frozenset[str] = frozenset()

    def active_aliases(self) -> list[str]:
        return sorted(alias for alias in self.keys if alias not in self.revoked)

    def key_for(self, alias: str) -> str | None:
        """The public key text of a trusted, not revoked alias, else None."""
        if alias in self.revoked:
            return None
        return self.keys.get(alias)

    def identify(self, body: dict[str, Any], signature: str) -> str | None:
        """The alias of the trusted key that made `signature` over `body`, or None (unknown signer or invalid signature)."""
        for alias in self.active_aliases():
            if verify_body(self.keys[alias], body, signature):
                return alias
        return None

    def verify(self, body: dict[str, Any], signature: str, *, signer: str | None = None) -> bool:
        """With `signer`, the signature has to be that alias's; without, any trusted alias will do."""
        if signer is None:
            return self.identify(body, signature) is not None
        key = self.key_for(signer)
        return key is not None and verify_body(key, body, signature)

    def to_dict(self) -> dict[str, Any]:
        return {TRUST_KEY: dict(sorted(self.keys.items())), REVOKED_KEY: sorted(self.revoked)}

    def with_key(self, alias: str, public_key: str) -> "TrustStore":
        if not valid_alias(alias):
            raise ConfigValidationError("an alias must be 1 to 40 letters, digits, spaces or ._@-")
        if public_key.strip().startswith(SEED_PREFIX):
            raise ConfigValidationError("that is a private key: the trust store holds public keys only")
        if not _PUBLIC.match(public_key.strip()):
            raise ConfigValidationError(f"the public key must look like '{PUBLIC_PREFIX}<64 hex digits>'")
        if alias in self.keys and self.keys[alias] != public_key.strip():
            raise ConfigValidationError(f"the alias {alias!r} already holds another key: revoke it and use a new alias")
        return TrustStore({**self.keys, alias: public_key.strip()}, self.revoked)

    def with_revoked(self, alias: str) -> "TrustStore":
        if alias not in self.keys:
            raise ConfigValidationError(f"the alias {alias!r} is not in the trust store")
        return TrustStore(dict(self.keys), self.revoked | {alias})


def trust_store_from_config(data: object) -> tuple[TrustStore, list[str]]:
    """`(store, problems)` from a parsed document. Problems name the alias, never the value."""
    problems: list[str] = []
    keys: dict[str, str] = {}
    if data is None:
        return TrustStore(), problems
    if not isinstance(data, dict):
        return TrustStore(), ["the trust store must be a JSON object"]
    entries = data.get(TRUST_KEY, {})
    if not isinstance(entries, dict):
        problems.append(f"{TRUST_KEY} must be an object of alias: public key")
        entries = {}
    for alias, value in entries.items():
        if not valid_alias(alias):
            problems.append(f"{TRUST_KEY}: an alias must be 1 to 40 letters, digits, spaces or ._@- ({str(alias)[:20]!r} was left out)")
        elif isinstance(value, str) and value.strip().startswith(SEED_PREFIX):
            problems.append(f"{TRUST_KEY}: the entry of {alias!r} is a private key and was left out (the store holds public keys only)")
        elif not isinstance(value, str) or not _PUBLIC.match(value.strip()):
            problems.append(f"{TRUST_KEY}: the key of {alias!r} is not '{PUBLIC_PREFIX}<64 hex digits>' and was left out")
        else:
            keys[alias] = value.strip()
    raw_revoked = data.get(REVOKED_KEY, [])
    revoked: set[str] = set()
    if not isinstance(raw_revoked, list) or not all(isinstance(item, str) for item in raw_revoked):
        problems.append(f"{REVOKED_KEY} must be a list of aliases")
    else:
        for alias in raw_revoked:
            if alias not in keys:
                problems.append(f"{REVOKED_KEY}: {alias!r} is not a trusted alias")
            revoked.add(alias)
    return TrustStore(keys, frozenset(revoked)), problems


def load_trust_store(path: Path) -> tuple[TrustStore, list[str]]:
    """Read the store from a file. A file that does not exist is an error, not an empty store: a host that
    was told to trust a store and cannot read it must not go on as if it trusted nobody by choice."""
    return trust_store_from_config(load_json_document(path))


def save_trust_store(path: Path, store: TrustStore) -> None:
    """Write the store, replacing the file atomically (the store is public data: 0644)."""
    text = json.dumps(store.to_dict(), indent=2, ensure_ascii=False) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)
