# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/operations.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS09 - stable operation and restore.

Two pieces, each defended by test:

  * a verified backup / restore of this host's own durable state. Every
    file in a backup carries a sha256; `verify_backup()` re-hashes and
    flags any drift, and `restore_backup()` refuses a backup taken for a
    DIFFERENT instance id or a DIFFERENT schema version, or one whose
    files no longer match the manifest.
  * an operational health check over the durable queue and the disk:
    orphaned (expired-but-still-leased) entries, a journal over its row
    cap, and free disk under the configured floor each make the report
    not-ok, with a named finding.

All filesystem contact is behind the injectable `BackupFs` seam, so the
tests run against a fake tree and never a real state directory.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, runtime_checkable

from .config import ConfigValidationError, _require_str
from .durable_queue import STATE_LEASED, DurableQueue

BACKUP_SCHEMA_VERSION = "dev-server-state/1"


# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------
@runtime_checkable
class BackupFs(Protocol):
    def read_bytes(self, path: str) -> bytes: ...

    def write_bytes(self, path: str, data: bytes) -> None: ...

    def sha256(self, path: str) -> str: ...

    def exists(self, path: str) -> bool: ...


@dataclass(frozen=True)
class BackupManifest:
    backup_id: str
    instance_id: str
    schema_version: str
    files: dict[str, str] = field(default_factory=dict)  # relpath -> sha256

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "instance_id": self.instance_id,
            "schema_version": self.schema_version,
            "files": dict(sorted(self.files.items())),
        }

    @staticmethod
    def from_dict(data: object) -> "BackupManifest":
        if not isinstance(data, dict):
            raise ConfigValidationError("backup manifest must be a JSON object")
        errors: list[str] = []
        backup_id = _require_str(data, "backup_id", errors)
        instance_id = _require_str(data, "instance_id", errors)
        schema_version = _require_str(data, "schema_version", errors)
        files_raw = data.get("files", {})
        if not isinstance(files_raw, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and k and v for k, v in files_raw.items()
        ):
            errors.append("'files' must be a map of relpath -> sha256 hex")
            files_raw = {}
        if errors:
            raise ConfigValidationError("; ".join(errors))
        return BackupManifest(backup_id, instance_id, schema_version, dict(files_raw))


def _join(root: str, rel: str) -> str:
    return (root.rstrip("/") + "/" + rel.lstrip("/")).replace("\\", "/")


def create_backup(
    source_root: str,
    relpaths: Iterable[str],
    backup_root: str,
    fs: BackupFs,
    *,
    backup_id: str,
    instance_id: str,
    schema_version: str = BACKUP_SCHEMA_VERSION,
) -> BackupManifest:
    files: dict[str, str] = {}
    for rel in sorted(relpaths):
        src = _join(source_root, rel)
        if not fs.exists(src):
            raise ConfigValidationError(f"backup source {rel!r} does not exist under {source_root!r}")
        fs.write_bytes(_join(backup_root, rel), fs.read_bytes(src))
        files[rel] = fs.sha256(_join(backup_root, rel))
    return BackupManifest(backup_id=backup_id, instance_id=instance_id, schema_version=schema_version, files=files)


@dataclass(frozen=True)
class VerifyBackupResult:
    ok: bool
    verified: tuple[str, ...] = ()
    mismatches: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "verified": list(self.verified),
                "mismatches": list(self.mismatches), "missing": list(self.missing)}


def verify_backup(manifest: BackupManifest, backup_root: str, fs: BackupFs) -> VerifyBackupResult:
    verified: list[str] = []
    mismatches: list[str] = []
    missing: list[str] = []
    for rel, expected in sorted(manifest.files.items()):
        path = _join(backup_root, rel)
        if not fs.exists(path):
            missing.append(rel)
        elif fs.sha256(path) == expected:
            verified.append(rel)
        else:
            mismatches.append(rel)
    return VerifyBackupResult(
        ok=not mismatches and not missing,
        verified=tuple(verified), mismatches=tuple(mismatches), missing=tuple(missing),
    )


@dataclass(frozen=True)
class RestoreResult:
    ok: bool
    restored: tuple[str, ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "restored": list(self.restored), "reason": self.reason}


def restore_backup(
    manifest: BackupManifest,
    backup_root: str,
    restore_root: str,
    fs: BackupFs,
    *,
    expected_instance_id: str,
    expected_schema_version: str = BACKUP_SCHEMA_VERSION,
) -> RestoreResult:
    if manifest.instance_id != expected_instance_id:
        return RestoreResult(False, reason=f"backup is for instance {manifest.instance_id!r}, not {expected_instance_id!r}")
    if manifest.schema_version != expected_schema_version:
        return RestoreResult(False, reason=f"backup schema {manifest.schema_version!r} != {expected_schema_version!r}")
    check = verify_backup(manifest, backup_root, fs)
    if not check.ok:
        return RestoreResult(False, reason=f"backup is not intact: mismatches={check.mismatches} missing={check.missing}")
    restored: list[str] = []
    for rel in sorted(manifest.files):
        fs.write_bytes(_join(restore_root, rel), fs.read_bytes(_join(backup_root, rel)))
        restored.append(rel)
    return RestoreResult(True, restored=tuple(restored))


# ---------------------------------------------------------------------------
# Operational health
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class HealthFinding:
    name: str
    detail: str


@dataclass(frozen=True)
class HealthReport:
    ok: bool
    findings: tuple[HealthFinding, ...] = ()
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "findings": [{"name": f.name, "detail": f.detail} for f in self.findings],
            "stats": self.stats,
        }


def check_operational_health(
    queue: DurableQueue,
    *,
    free_disk_gb: float | None = None,
    min_free_disk_gb: float = 2.0,
    journal_row_cap: int = 10_000,
    now: float | None = None,
) -> HealthReport:
    at = time.time() if now is None else now
    stats = queue.stats()
    findings: list[HealthFinding] = []

    orphaned = queue._conn.execute(  # read-only count
        f"SELECT COUNT(*) AS n FROM entries WHERE state = '{STATE_LEASED}' AND lease_expires_at < ?",
        (at,),
    ).fetchone()["n"]
    if orphaned:
        findings.append(HealthFinding(
            "orphaned-leases",
            f"{orphaned} entr{'y' if orphaned == 1 else 'ies'} leased but expired - run `queue reconcile`",
        ))

    if stats["journal_rows"] > journal_row_cap:
        findings.append(HealthFinding(
            "journal-over-cap",
            f"{stats['journal_rows']} journal rows over the cap {journal_row_cap} - run `prune_journal`",
        ))

    if free_disk_gb is not None and free_disk_gb < min_free_disk_gb:
        findings.append(HealthFinding(
            "low-disk", f"{free_disk_gb:.1f} GiB free, floor is {min_free_disk_gb:.1f}",
        ))

    return HealthReport(ok=not findings, findings=tuple(findings), stats=stats)


# ---------------------------------------------------------------------------
# The one real filesystem
# ---------------------------------------------------------------------------
class SystemBackupFs:
    def read_bytes(self, path: str) -> bytes:
        with open(path, "rb") as handle:
            return handle.read()

    def write_bytes(self, path: str, data: bytes) -> None:
        import os

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def sha256(self, path: str) -> str:
        import hashlib

        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def exists(self, path: str) -> bool:
        import os

        return os.path.exists(path)
