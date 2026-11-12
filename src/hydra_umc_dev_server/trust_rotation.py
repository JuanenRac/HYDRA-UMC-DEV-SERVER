# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/trust_rotation.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Where the trust store lives on the CM5, and how a key in it is replaced with a signed rotation.

Location. The trust store of a CM5 is the directory `/etc/hydra-umc/trust`, owned by root with mode 0700, outside the data of any application: a
service that is compromised cannot add its own key to it. The directory holds two files, `trust.json` (the store of `trust_store.py`) and
`rotation.log` (one line of JSON per rotation, chained by hash). `check_trust_dir` says what is wrong with a directory; `ensure_trust_dir` creates
it, and only as root.

Rotation. A key is replaced by a new one only when the key being replaced signs the statement. The statement names the old alias and key, the new
alias and key, the sequence number (1 for the first rotation, then one more each time) and the hash of the previous log record. Applying it
adds the new alias and revokes the old one in one step, and appends a record that holds the statement and the signature. Nothing else can change
the store through this module: a statement that is not signed by the current key of an active alias, that skips or repeats a sequence number, that
does not follow the last record, or that brings a key already in the store, is refused and the store and the log stay as they were.

Switch. Rotation is off unless `HYDRA_UMC_TRUST_ROTATION=1` is set (or the caller passes `enabled=True`): the default is a store that only changes with
`trust add` and `trust revoke` by someone with the directory open as root. The private key never reaches this module except in `sign_rotation`,
which runs on the approver's own machine and returns only the signature.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .config import ConfigValidationError
from .signing import PUBLIC_PREFIX, canonical_bytes, is_public_key, sign_body, verify_body
from .trust_store import TrustStore, load_trust_store, save_trust_store, valid_alias

TRUST_DIR = Path("/etc/hydra-umc/trust")
STORE_NAME = "trust.json"
LOG_NAME = "rotation.log"
ROTATION_ENV = "HYDRA_UMC_TRUST_ROTATION"
ACTION = "rotate-trust-key"
GENESIS = "0" * 64
_BODY_KEYS = {"action", "old", "old_key", "new", "new_key", "sequence", "previous"}


def rotation_enabled(environ: Mapping[str, str] | None = None) -> bool:
    return (environ if environ is not None else os.environ).get(ROTATION_ENV, "") == "1"


def check_trust_dir(
    path: Path,
    *,
    app_data_dirs: tuple[Path, ...] = (),
    lstat: Callable[[Path], os.stat_result] = lambda p: p.lstat(),
) -> list[str]:
    """What is wrong with the trust directory: it is missing, is a link, is not owned by root, is open to the group or to others, holds a store or a
    log that others can write, or lies inside the data of an application. An empty list means it is fit. `lstat` can be replaced in tests."""
    problems: list[str] = []
    try:
        info = lstat(path)
    except OSError:
        return [f"{path} does not exist"]
    if stat.S_ISLNK(info.st_mode):
        problems.append(f"{path} is a symbolic link")
    elif not stat.S_ISDIR(info.st_mode):
        problems.append(f"{path} is not a directory")
        return problems
    if info.st_uid != 0:
        problems.append(f"{path} is not owned by root (owner {info.st_uid})")
    if info.st_mode & 0o077:
        problems.append(f"{path} is open to the group or to others (mode {stat.S_IMODE(info.st_mode):04o}, expected 0700)")
    for name in (STORE_NAME, LOG_NAME):
        try:
            child = lstat(path / name)
        except OSError:
            continue
        if stat.S_ISLNK(child.st_mode):
            problems.append(f"{name} is a symbolic link")
        if child.st_uid != 0:
            problems.append(f"{name} is not owned by root (owner {child.st_uid})")
        if child.st_mode & 0o022:
            problems.append(f"{name} can be written by the group or by others (mode {stat.S_IMODE(child.st_mode):04o})")
    resolved = path.resolve()
    for data_dir in app_data_dirs:
        data = data_dir.resolve()
        if resolved == data or data in resolved.parents:
            problems.append(f"{path} lies inside the data of an application ({data_dir})")
    return problems


def ensure_trust_dir(path: Path = TRUST_DIR) -> None:
    """Creates the directory with mode 0700. Only root can: anyone else gets a refusal, not a directory that root does not own."""
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() != 0:
        raise ConfigValidationError("the trust directory is created by root")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def record_hash(body: dict[str, Any], signature: str, previous: str) -> str:
    return hashlib.sha256(previous.encode("ascii") + b"\n" + canonical_bytes(body) + b"\n" + signature.encode("ascii")).hexdigest()


def read_log(path: Path) -> list[dict[str, Any]]:
    """The records of the log, in order. A line that is not a record is an error: a log with a hole is not a history."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise ConfigValidationError(f"{path.name} line {number} is not JSON") from exc
        if not isinstance(record, dict) or not {"sequence", "body", "signature", "hash"} <= set(record):
            raise ConfigValidationError(f"{path.name} line {number} is not a rotation record")
        records.append(record)
    return records


def verify_log(records: list[dict[str, Any]]) -> list[str]:
    """Problems of a log: a sequence that does not count 1, 2, 3, a chain that does not follow, a hash that is not the one of its content, a signature
    that is not the one of the key the statement replaced. Empty means the log is a consistent history."""
    problems: list[str] = []
    previous = GENESIS
    for index, record in enumerate(records, start=1):
        body = record.get("body")
        signature = record.get("signature")
        if not isinstance(body, dict) or not isinstance(signature, str):
            problems.append(f"record {index} has no statement or no signature")
            break
        if record.get("sequence") != index or body.get("sequence") != index:
            problems.append(f"record {index} has the sequence {record.get('sequence')}")
        if body.get("previous") != previous:
            problems.append(f"record {index} does not follow the previous record")
        if record.get("hash") != record_hash(body, signature, previous):
            problems.append(f"record {index} does not match its hash")
        old_key = body.get("old_key")
        if not isinstance(old_key, str) or not verify_body(old_key, body, signature):
            problems.append(f"record {index} is not signed by the key it replaced")
        previous = str(record.get("hash"))
    return problems


def rotation_body(store: TrustStore, records: list[dict[str, Any]], old_alias: str, new_alias: str, new_public_key: str) -> dict[str, Any]:
    """The statement to sign for replacing `old_alias` by `new_alias`, built from the current store and log."""
    old_key = store.key_for(old_alias)
    if old_key is None:
        raise ConfigValidationError(f"{old_alias!r} is not an active alias of the trust store")
    return {
        "action": ACTION,
        "old": old_alias,
        "old_key": old_key,
        "new": new_alias,
        "new_key": new_public_key.strip(),
        "sequence": len(records) + 1,
        "previous": str(records[-1]["hash"]) if records else GENESIS,
    }


def sign_rotation(seed_text: str, body: dict[str, Any]) -> str:
    """On the approver's machine: signs the statement with the private key that is being replaced. Returns only the signature."""
    return sign_body(seed_text, body)


def apply_rotation(store: TrustStore, records: list[dict[str, Any]], body: dict[str, Any], signature: str, *, enabled: bool) -> tuple[TrustStore, dict[str, Any]]:
    """The new store and the record to append, or ConfigValidationError with the reason. Nothing is written here."""
    if not enabled:
        raise ConfigValidationError(f"the rotation of trust keys is off ({ROTATION_ENV}=1 switches it on)")
    problems = verify_log(records)
    if problems:
        raise ConfigValidationError("the rotation log is damaged: " + "; ".join(problems))
    if not isinstance(body, dict) or set(body) != _BODY_KEYS or body.get("action") != ACTION:
        raise ConfigValidationError("the statement is not a trust key rotation")
    old, new, old_key, new_key = body["old"], body["new"], body["old_key"], body["new_key"]
    if not (valid_alias(old) and valid_alias(new)):
        raise ConfigValidationError("an alias must be 1 to 40 letters, digits, spaces or ._@-")
    if old == new:
        raise ConfigValidationError("the new alias must differ from the old one: an alias keeps its key")
    if store.key_for(old) != old_key:
        raise ConfigValidationError(f"{old!r} is not an active alias holding that key")
    if not isinstance(new_key, str) or not is_public_key(new_key):
        raise ConfigValidationError(f"the new key must look like '{PUBLIC_PREFIX}<64 hex digits>'")
    if new_key == old_key or new_key in store.keys.values():
        raise ConfigValidationError("the new key is already in the trust store")
    if new in store.keys:
        raise ConfigValidationError(f"the alias {new!r} is already in the trust store")
    if body["sequence"] != len(records) + 1:
        raise ConfigValidationError(f"the sequence must be {len(records) + 1}")
    previous = str(records[-1]["hash"]) if records else GENESIS
    if body["previous"] != previous:
        raise ConfigValidationError("the statement does not follow the last record of the log")
    if not isinstance(signature, str) or not verify_body(old_key, body, signature):
        raise ConfigValidationError("the statement is not signed by the key it replaces")
    updated = store.with_key(new, new_key).with_revoked(old)
    record = {"sequence": body["sequence"], "body": body, "signature": signature, "hash": record_hash(body, signature, previous)}
    return updated, record


def rotate_in_directory(directory: Path, body: dict[str, Any], signature: str, *, enabled: bool | None = None) -> TrustStore:
    """Reads the store and the log of `directory`, applies the rotation, and writes the log first and the store second: a cut in between leaves a log
    that is one record ahead of the store, which the next call reports instead of repeating."""
    allowed = rotation_enabled() if enabled is None else enabled
    store, problems = load_trust_store(directory / STORE_NAME)
    if problems:
        raise ConfigValidationError("the trust store has problems: " + "; ".join(problems))
    records = read_log(directory / LOG_NAME)
    updated, record = apply_rotation(store, records, body, signature, enabled=allowed)
    with open(directory / LOG_NAME, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    save_trust_store(directory / STORE_NAME, updated)
    return updated


def log_agrees_with_store(store: TrustStore, records: list[dict[str, Any]]) -> list[str]:
    """Problems between the log and the store: every rotated key must be revoked and every new key present, unless a later record replaced it."""
    problems: list[str] = []
    for index, record in enumerate(records, start=1):
        body = record.get("body", {})
        old, new = body.get("old"), body.get("new")
        if old not in store.revoked:
            problems.append(f"record {index}: {old!r} is not revoked in the store")
        if new not in store.keys:
            problems.append(f"record {index}: {new!r} is not in the store")
    return problems
