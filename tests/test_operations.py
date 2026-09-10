# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_operations.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS09 - stable operation and verified restore. Backup / restore run
against a fake filesystem; health runs against an in-memory queue."""
import hashlib
import unittest

from hydra_umc_dev_server.durable_queue import DurableQueue
from hydra_umc_dev_server.operations import (
    BACKUP_SCHEMA_VERSION,
    BackupFs,
    check_operational_health,
    create_backup,
    restore_backup,
    verify_backup,
)
from hydra_umc_dev_server.recipe import TaskRecipe


class FakeBackupFs:
    def __init__(self, files: dict[str, bytes] | None = None):
        self.blobs: dict[str, bytes] = dict(files or {})

    def read_bytes(self, path: str) -> bytes:
        return self.blobs[path]

    def write_bytes(self, path: str, data: bytes) -> None:
        self.blobs[path] = data

    def sha256(self, path: str) -> str:
        return hashlib.sha256(self.blobs[path]).hexdigest()

    def exists(self, path: str) -> bool:
        return path in self.blobs


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.fs = FakeBackupFs({
            "/state/queue.sqlite3": b"the queue bytes",
            "/state/config/task-policy.json": b'{"allow_deploy": false}',
        })

    def _backup(self):
        return create_backup(
            "/state", ["queue.sqlite3", "config/task-policy.json"], "/backups/b1", self.fs,
            backup_id="b1", instance_id="dev-server-01",
        )

    def test_a_fresh_backup_verifies(self):
        manifest = self._backup()
        self.assertEqual(set(manifest.files), {"queue.sqlite3", "config/task-policy.json"})
        self.assertTrue(verify_backup(manifest, "/backups/b1", self.fs).ok)

    def test_verify_detects_a_tampered_backup_file(self):
        manifest = self._backup()
        self.fs.blobs["/backups/b1/queue.sqlite3"] = b"corrupted"
        result = verify_backup(manifest, "/backups/b1", self.fs)
        self.assertFalse(result.ok)
        self.assertEqual(result.mismatches, ("queue.sqlite3",))

    def test_restore_round_trips_the_exact_bytes(self):
        manifest = self._backup()
        # lose the originals
        del self.fs.blobs["/state/queue.sqlite3"]
        del self.fs.blobs["/state/config/task-policy.json"]
        result = restore_backup(manifest, "/backups/b1", "/state", self.fs, expected_instance_id="dev-server-01")
        self.assertTrue(result.ok)
        self.assertEqual(self.fs.blobs["/state/queue.sqlite3"], b"the queue bytes")

    def test_restore_refuses_a_backup_for_another_instance(self):
        manifest = self._backup()
        result = restore_backup(manifest, "/backups/b1", "/state", self.fs, expected_instance_id="dev-server-99")
        self.assertFalse(result.ok)
        self.assertIn("instance", result.reason)

    def test_restore_refuses_an_incompatible_schema(self):
        manifest = create_backup(
            "/state", ["queue.sqlite3"], "/backups/b2", self.fs,
            backup_id="b2", instance_id="dev-server-01", schema_version="dev-server-state/9",
        )
        result = restore_backup(manifest, "/backups/b2", "/state", self.fs,
                                expected_instance_id="dev-server-01",
                                expected_schema_version=BACKUP_SCHEMA_VERSION)
        self.assertFalse(result.ok)
        self.assertIn("schema", result.reason)

    def test_restore_refuses_a_corrupted_backup(self):
        manifest = self._backup()
        self.fs.blobs["/backups/b1/queue.sqlite3"] = b"corrupted"
        result = restore_backup(manifest, "/backups/b1", "/state", self.fs, expected_instance_id="dev-server-01")
        self.assertFalse(result.ok)
        self.assertIn("not intact", result.reason)

    def test_the_fake_fs_satisfies_the_protocol(self):
        self.assertIsInstance(FakeBackupFs(), BackupFs)


def _recipe(task_id="h-1") -> TaskRecipe:
    return TaskRecipe.from_dict({
        "task_id": task_id, "repo": "r", "revision": "0.0.9",
        "command": ["pytest"], "timeout_seconds": 60, "input_paths": [],
    })


class HealthCheckTests(unittest.TestCase):
    def test_a_quiet_queue_with_room_on_disk_is_healthy(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "b", now=1000.0)
            report = check_operational_health(q, free_disk_gb=50.0, min_free_disk_gb=2.0, now=1000.0)
            self.assertTrue(report.ok, report.to_dict())

    def test_an_orphaned_lease_is_a_finding(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "b", now=1000.0)
            q.lease("w1", 10, now=1000.0)
            report = check_operational_health(q, now=1030.0)  # lease expired, not yet reconciled
            self.assertFalse(report.ok)
            self.assertIn("orphaned-leases", [f.name for f in report.findings])

    def test_a_journal_over_its_cap_is_a_finding(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "b", now=0.0)
            for i in range(6):
                q.lease("w1", 1, now=100.0 + i * 10)
                q.reconcile(now=105.0 + i * 10)
            report = check_operational_health(q, journal_row_cap=3, now=1000.0)
            self.assertFalse(report.ok)
            self.assertIn("journal-over-cap", [f.name for f in report.findings])

    def test_low_disk_is_a_finding(self):
        with DurableQueue(":memory:") as q:
            report = check_operational_health(q, free_disk_gb=0.5, min_free_disk_gb=2.0, now=1000.0)
            self.assertFalse(report.ok)
            self.assertIn("low-disk", [f.name for f in report.findings])


if __name__ == "__main__":
    unittest.main()
