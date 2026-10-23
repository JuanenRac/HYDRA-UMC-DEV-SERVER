# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_boundaries.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Edges that must hold: where a remote station may listen, what may end up in a
generated unit, how a runaway process tree is stopped, how the queue behaves when
two workers race, and which repair-cycle steps can be replayed."""
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.durable_queue import (
    STATE_DEAD_LETTER,
    STATE_LEASED,
    STATE_QUEUED,
    DurableQueue,
)
from hydra_umc_dev_server.recipe import TaskRecipe
from hydra_umc_dev_server.remote_station import RemoteAccess, RemoteIdentity
from hydra_umc_dev_server.repair_cycle import STATE_BLOCKED, STATE_NOT_STARTED, RepairCycle
from hydra_umc_dev_server.runner import (
    OUTCOME_REJECTED,
    SubprocessLauncher,
    build_task_env,
    run_task,
)


def _recipe(task_id="q-1", command=("pytest", "-q"), revision="0.0.5") -> TaskRecipe:
    return TaskRecipe.from_dict({
        "task_id": task_id, "repo": "HYDRA-UMC-DEV-SERVER", "revision": revision,
        "command": list(command), "timeout_seconds": 60, "input_paths": [],
    })


class _Run:
    outcome, exit_code, stdout_tail, stderr_tail = "completed", 0, "", ""


class RemoteStationValidationTests(unittest.TestCase):
    def test_wildcard_and_link_local_addresses_are_not_private_binds(self):
        for address in ("0.0.0.0", "::", "169.254.1.1", "fe80::1"):
            access = RemoteAccess.from_dict({"kind": "code-server", "port": 8722, "bind_address": address})
            self.assertFalse(access.is_loopback_or_private(), address)
        for address in ("127.0.0.1", "192.168.0.180", "10.1.2.3", "::1"):
            access = RemoteAccess.from_dict({"kind": "code-server", "port": 8722, "bind_address": address})
            self.assertTrue(access.is_loopback_or_private(), address)

    def test_a_newline_or_space_in_an_identity_cannot_reach_a_systemd_unit(self):
        for bad in (
            {"user": "svc", "home": "/srv/x\nExecStartPre=/bin/sh -c id"},
            {"user": "root ", "home": "/srv/x"},
            {"user": "svc", "home": "/srv/x y"},
            {"user": "svc", "home": "/srv/x", "workspace_subdir": "w\nExecStart=/bin/sh"},
            {"user": "Svc", "home": "/srv/x"},
        ):
            with self.assertRaises(ConfigValidationError, msg=repr(bad)):
                RemoteIdentity.from_dict(bad)
        RemoteIdentity.from_dict({"user": "hydra-dev-station", "home": "/srv/hydra-umc-dev/station"})


class TaskEnvironmentAndSpawnTests(unittest.TestCase):
    def test_windows_basics_are_passed_only_on_windows(self):
        source = {"PATH": "/usr/bin", "SYSTEMROOT": "C:\\Windows", "AWS_SECRET_ACCESS_KEY": "x"}
        env = build_task_env(source)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", env)
        self.assertEqual("SYSTEMROOT" in env, os.name == "nt")

    def test_a_missing_command_is_a_rejection_not_a_traceback(self):
        from hydra_umc_dev_server.config import TaskPolicy

        policy = TaskPolicy(
            allow_deploy=False, max_concurrent_tasks=1, allowed_commands=("definitely-not-a-real-command-xyz",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            from hydra_umc_dev_server.workspace import Workspace

            workspace = Workspace(task_id="t-1", root=str(Path(tmp)))
            recipe = _recipe("t-1", command=("definitely-not-a-real-command-xyz",))
            result = run_task(recipe, policy, workspace, SubprocessLauncher())
            self.assertEqual(result.outcome, OUTCOME_REJECTED)
            self.assertIn("could not be started", result.rejection_reason)


@unittest.skipUnless(os.name == "posix", "process groups are a POSIX feature")
class KillTreeTests(unittest.TestCase):
    def test_a_grandchild_that_ignores_sigterm_does_not_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "grandchild.pid"
            script = "\n".join([
                "import signal, subprocess, sys, time",
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)",
                "child = subprocess.Popen([sys.executable, '-c', "
                "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])",
                f"open({str(pid_file)!r}, 'w').write(str(child.pid))",
                "time.sleep(60)",
            ])
            handle = SubprocessLauncher().spawn((sys.executable, "-c", script), cwd=tmp, env=dict(os.environ))
            deadline = time.time() + 10
            while time.time() < deadline and not (pid_file.exists() and pid_file.read_text()):
                time.sleep(0.05)
            grandchild_pid = int(pid_file.read_text())
            handle.kill_tree()
            time.sleep(0.3)
            with self.assertRaises(ProcessLookupError):
                os.kill(grandchild_pid, 0)

    def test_a_task_that_exits_normally_leaves_no_background_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "background.pid"
            script = "\n".join([
                "import subprocess, sys",
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])",
                f"open({str(pid_file)!r}, 'w').write(str(child.pid))",
            ])
            handle = SubprocessLauncher().spawn((sys.executable, "-c", script), cwd=tmp, env=dict(os.environ))
            deadline = time.time() + 10
            while time.time() < deadline and handle.poll() is None:
                time.sleep(0.05)
            self.assertIsNotNone(handle.poll())
            time.sleep(0.3)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)


class QueueRaceTests(unittest.TestCase):
    def test_a_different_recipe_for_an_existing_task_id_is_reported_as_a_conflict(self):
        with DurableQueue(":memory:") as q:
            self.assertFalse(q.enqueue(_recipe(), "b", now=1000.0).conflict)
            self.assertFalse(q.enqueue(_recipe(), "b", now=1001.0).conflict)
            other = q.enqueue(_recipe(command=("pytest", "-x")), "b", now=1002.0)
            self.assertFalse(other.created)
            self.assertTrue(other.conflict)

    def test_a_result_from_a_worker_whose_lease_has_expired_is_rejected(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "b", now=1000.0)
            q.lease("w1", 30, now=1000.0)
            late = q.record_result("q-1", "w1", _Run(), "b", now=1100.0)
            self.assertFalse(late.accepted)
            self.assertEqual(q.entry("q-1").state, STATE_LEASED)

    def test_a_result_after_reconcile_and_a_new_lease_cannot_overwrite_the_new_worker(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "b", now=1000.0)
            q.lease("w1", 30, now=1000.0)
            q.reconcile(now=1100.0)
            q.lease("w2", 30, now=1101.0)
            stale = q.record_result("q-1", "w1", _Run(), "b", now=1102.0)
            self.assertFalse(stale.accepted)
            self.assertEqual(q.entry("q-1").leased_by, "w2")

    def test_a_task_that_keeps_losing_its_worker_is_parked_after_the_attempt_limit(self):
        with DurableQueue(":memory:", max_attempts=2) as q:
            q.enqueue(_recipe(), "b", now=1000.0)
            q.lease("w", 10, now=1000.0)
            q.reconcile(now=1100.0)
            self.assertEqual(q.entry("q-1").state, STATE_QUEUED)
            q.lease("w", 10, now=1101.0)
            q.reconcile(now=1200.0)
            self.assertEqual(q.entry("q-1").state, STATE_DEAD_LETTER)
            self.assertIsNone(q.lease("w", 10, now=1201.0))

    def test_two_connections_to_one_file_never_lease_the_same_task_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "queue.sqlite3")
            with DurableQueue(path) as seed:
                for number in range(20):
                    seed.enqueue(_recipe(f"t-{number:02d}"), "b", now=1000.0 + number)
            granted: list[str] = []
            lock = threading.Lock()

            def drain(name: str) -> None:
                with DurableQueue(path) as queue:  # each worker has its own connection
                    while True:
                        grant = queue.lease(name, 60, now=2000.0)
                        if grant is None:
                            return
                        with lock:
                            granted.append(grant.task_id)

            threads = [threading.Thread(target=drain, args=(name,)) for name in ("a", "b")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            self.assertEqual(len(granted), 20)
            self.assertEqual(len(set(granted)), 20)


class RepairCycleReplayTests(unittest.TestCase):
    def test_a_new_cycle_is_not_started_and_a_blocked_one_cannot_be_reopened(self):
        cycle = RepairCycle("INC", "base", "target", "case", allow_symmetric_keys=True, require_bound_approval=False)
        self.assertEqual(cycle.state, STATE_NOT_STARTED)
        self.assertFalse(cycle.confirm_repro({"reproduced": False, "repro_case_id": "case"}).ok)
        self.assertEqual(cycle.state, STATE_BLOCKED)
        reopened = cycle.confirm_repro({"reproduced": True, "repro_case_id": "case"})
        self.assertFalse(reopened.ok)
        self.assertEqual(cycle.state, STATE_BLOCKED)

    def test_a_truthy_string_is_not_a_reproduction(self):
        cycle = RepairCycle("INC", "base", "target", "case", allow_symmetric_keys=True, require_bound_approval=False)
        self.assertFalse(cycle.confirm_repro({"reproduced": "false", "repro_case_id": "case"}).ok)


class ApiContentLengthTests(unittest.TestCase):
    def test_a_negative_content_length_is_refused_at_once(self):
        from hydra_umc_dev_server.api import DevServer

        token = "t" * 40
        with tempfile.TemporaryDirectory() as tmp:
            server = DevServer(("127.0.0.1", 0), token=token, workspace_root=Path(tmp), plugins_root=Path(tmp) / "plugins")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with socket.create_connection(("127.0.0.1", port), timeout=3) as conn:
                    conn.sendall(
                        (
                            "POST /v1/plugins/rescan HTTP/1.1\r\nHost: x\r\n"
                            f"Authorization: Bearer {token}\r\nContent-Length: -1\r\n\r\n"
                        ).encode()
                    )
                    reply = conn.recv(4096).decode("latin-1")
                self.assertTrue(reply.startswith("HTTP/1.0 400") or reply.startswith("HTTP/1.1 400"), reply[:60])
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()


class RealGitMigrationTests(unittest.TestCase):
    """A real temporary repository: the classification of files git reports in
    unusual ways (a new directory, a rename) and of a source with no git at all."""

    def _git(self, root, *args):
        import subprocess

        subprocess.run(
            ("git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args),
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def setUp(self):
        import shutil

        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _inventory(self):
        from hydra_umc_dev_server.migration import SystemSourceInspector, build_repo_inventory

        return {e.relpath: e.classification for e in build_repo_inventory(str(self.root), SystemSourceInspector()).entries}

    def test_files_of_a_new_directory_and_a_renamed_file_are_classified_correctly(self):
        from hydra_umc_dev_server.migration import CLASS_TRACKED_CLEAN, CLASS_TRACKED_MODIFIED, CLASS_UNTRACKED

        self._git(self.root, "init", "-q")
        (self.root / "a.txt").write_text("one", encoding="utf-8")
        (self.root / "keep.txt").write_text("two", encoding="utf-8")
        self._git(self.root, "add", ".")
        self._git(self.root, "commit", "-q", "-m", "init")
        self._git(self.root, "mv", "a.txt", "b.txt")
        (self.root / "newdir").mkdir()
        (self.root / "newdir" / "notes.md").write_text("not published", encoding="utf-8")
        found = self._inventory()
        self.assertEqual(found["newdir/notes.md"], CLASS_UNTRACKED)
        self.assertEqual(found["keep.txt"], CLASS_TRACKED_CLEAN)
        self.assertEqual(found["b.txt"], CLASS_TRACKED_MODIFIED)
        self.assertNotIn("xt", found)

    def test_a_source_without_git_is_never_called_published(self):
        from hydra_umc_dev_server.migration import CLASS_PRIVATE, CLASS_UNTRACKED

        (self.root / "doc.md").write_text("x", encoding="utf-8")
        (self.root / "prod.env").write_text("SECRET=1", encoding="utf-8")
        found = self._inventory()
        self.assertEqual(found["doc.md"], CLASS_UNTRACKED)
        self.assertEqual(found["prod.env"], CLASS_PRIVATE)


class BackupPathTests(unittest.TestCase):
    def test_a_manifest_that_points_outside_the_backup_is_refused(self):
        from hydra_umc_dev_server.operations import BackupManifest

        for bad in ("../../etc/passwd", "/etc/passwd", "a//b", "a/../b", "back" + chr(92) + "slash"):
            with self.assertRaises(ConfigValidationError, msg=bad):
                BackupManifest.from_dict({
                    "backup_id": "b", "instance_id": "i", "schema_version": "1", "files": {bad: "0" * 64},
                })

    def test_the_real_filesystem_writes_whole_files_and_leaves_no_temporary_one(self):
        from hydra_umc_dev_server.operations import SystemBackupFs

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub" / "data.bin"
            SystemBackupFs().write_bytes(str(target), b"payload")
            self.assertEqual(target.read_bytes(), b"payload")
            self.assertEqual([p.name for p in target.parent.iterdir()], ["data.bin"])
