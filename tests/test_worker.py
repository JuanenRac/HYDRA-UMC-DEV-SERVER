# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_worker.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The worker loop: lease, stage, run with a renewed lease, record, clean up. A fake launcher, a fake
git, a fake clock and an in-memory queue; nothing is spawned and nothing touches a network."""
import tempfile
import unittest

from hydra_umc_dev_server.config import ConfigValidationError, TaskPolicy
from hydra_umc_dev_server.durable_queue import STATE_FAILED, STATE_LEASED, STATE_QUEUED, STATE_SUCCEEDED, DurableQueue
from hydra_umc_dev_server.recipe import TaskRecipe
from hydra_umc_dev_server.taskflow import ConcurrencyGate, TooManyTasksError
from hydra_umc_dev_server.worker import work_loop, work_once


class FakeFs:
    def __init__(self):
        self.dirs = {"/ws"}

    def exists(self, path):
        return path in self.dirs

    def make_dir(self, path):
        self.dirs.add(path)

    def realpath(self, path):
        return path


class FakeClock:
    """Time that only moves when someone sleeps."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeHandle:
    def __init__(self, code, polls):
        self._code, self._left, self.killed = code, polls, False

    def poll(self):
        if self.killed:
            return -9
        if self._left <= 0:
            return self._code
        self._left -= 1
        return None

    def kill_tree(self):
        self.killed = True

    def stdout_tail(self):
        return "out"

    def stderr_tail(self):
        return ""


class FakeLauncher:
    def __init__(self, code=0, polls=1):
        self.code, self.polls, self.spawned = code, polls, []
        self.handles = []

    def spawn(self, argv, *, cwd, env):
        self.spawned.append((argv, cwd, env))
        handle = FakeHandle(self.code, self.polls)
        self.handles.append(handle)
        return handle


def _policy(**extra):
    data = {"allow_deploy": False, "max_concurrent_tasks": 1, "allowed_commands": ["pytest"], "repo_sources": {"REPO": "https://example.invalid/repo.git"}}
    data.update(extra)
    return TaskPolicy.from_dict(data)


def _recipe(task_id="w-0001", **extra):
    data = {"task_id": task_id, "repo": "REPO", "revision": "0123456789abcdef0123456789abcdef01234567", "command": ["pytest", "-q"], "timeout_seconds": 600, "input_paths": []}
    data.update(extra)
    return TaskRecipe.from_dict(data)


def fake_git(commit="0123456789abcdef0123456789abcdef01234567", fail_on=None):
    calls = []

    def run(argv, *, cwd, env, timeout):
        calls.append(argv)
        if fail_on and argv[1] == fail_on:
            return 1, "boom"
        if argv[1] == "rev-parse":
            return 0, commit
        return 0, ""

    run.calls = calls
    return run


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.gate = ConcurrencyGate(self._tmp.name, 1)
        self.queue = DurableQueue(":memory:")
        self.addCleanup(self.queue.close)
        self.fs, self.clock = FakeFs(), FakeClock()

    def work(self, launcher, policy=None, **kwargs):
        return work_once(
            self.queue, "worker-1", policy or _policy(), "/ws", launcher,
            fs=self.fs, git=kwargs.pop("git", fake_git()), clock=self.clock, gate=self.gate, **kwargs,
        )

    def test_an_empty_queue_is_idle_and_takes_nothing(self):
        launcher = FakeLauncher()
        result = self.work(launcher)
        self.assertEqual((result.outcome, result.task_id), ("idle", None))
        self.assertEqual(launcher.spawned, [])

    def test_a_task_goes_from_queued_to_succeeded_with_the_staged_commit_in_the_journal(self):
        self.queue.enqueue(_recipe(), "base-1")
        launcher = FakeLauncher(code=0)
        result = self.work(launcher)
        self.assertEqual(result.outcome, "succeeded", result.to_dict())
        self.assertEqual(result.staged_commit, "0123456789abcdef0123456789abcdef01234567")
        self.assertTrue(result.recorded)
        self.assertEqual(self.queue.entry("w-0001").state, STATE_SUCCEEDED)
        self.assertEqual(launcher.spawned[0][1], "/ws/w-0001")
        self.assertEqual(launcher.spawned[0][2]["HOME"], "/ws/w-0001")
        events = [row["event"] for row in self.queue.journal_for("w-0001")]
        self.assertEqual(events, ["enqueued", "leased", "completed"])

    def test_a_failing_command_is_recorded_as_failed_not_promotable(self):
        self.queue.enqueue(_recipe(), "base-1")
        result = self.work(FakeLauncher(code=3))
        self.assertEqual(result.outcome, "failed")
        self.assertEqual(self.queue.entry("w-0001").state, STATE_FAILED)

    def test_a_base_that_moved_makes_a_good_run_not_promotable(self):
        self.queue.enqueue(_recipe(), "base-1")
        result = self.work(FakeLauncher(code=0), observe_base=lambda grant: "base-2")
        self.assertEqual(result.outcome, "failed")
        self.assertIn("base changed", result.detail)

    def test_the_lease_is_renewed_while_a_long_task_runs(self):
        self.queue.enqueue(_recipe(), "base-1")
        launcher = FakeLauncher(code=0, polls=400)
        result = self.work(launcher, lease_seconds=3.0, poll_interval=0.5)
        self.assertEqual(result.outcome, "succeeded", result.to_dict())
        renewals = [row for row in self.queue.journal_for("w-0001") if row["event"] == "leased"]
        self.assertEqual(len(renewals), 1)  # one lease; the renewals extend it without a new one
        self.assertGreater(self.clock.now, 1000.0 + 3.0)  # the run outlived the first lease

    def test_a_lease_that_is_lost_cancels_the_run_and_records_nothing(self):
        self.queue.enqueue(_recipe(), "base-1")
        launcher = FakeLauncher(code=0, polls=400)
        original = self.queue.renew_lease

        def lose(task_id, worker_id, ttl, **kwargs):
            self.queue.cancel(task_id)  # someone took the task away
            return original(task_id, worker_id, ttl, **kwargs)

        self.queue.renew_lease = lose
        result = self.work(launcher, lease_seconds=3.0, poll_interval=0.5)
        self.assertEqual(result.outcome, "lease-lost")
        self.assertTrue(launcher.handles[0].killed)
        self.assertFalse(result.recorded)

    def test_a_staging_failure_is_recorded_as_a_failed_task_and_the_task_is_not_left_leased(self):
        self.queue.enqueue(_recipe(), "base-1")
        launcher = FakeLauncher()
        result = self.work(launcher, git=fake_git(fail_on="fetch"))
        self.assertEqual(result.outcome, "failed")
        self.assertIn("fetch", result.detail)
        self.assertEqual(self.queue.entry("w-0001").state, STATE_FAILED)
        self.assertEqual(launcher.spawned, [])

    def test_a_command_the_policy_does_not_allow_is_recorded_as_failed(self):
        self.queue.enqueue(_recipe(command=["make"]), "base-1")
        result = self.work(FakeLauncher())
        self.assertEqual(result.outcome, "failed")
        self.assertIn("allowed_commands", result.detail)
        self.assertEqual(self.queue.entry("w-0001").state, STATE_FAILED)

    def test_a_workspace_that_already_exists_is_recorded_as_failed(self):
        self.queue.enqueue(_recipe(), "base-1")
        self.fs.dirs.add("/ws/w-0001")
        result = self.work(FakeLauncher())
        self.assertEqual(result.outcome, "failed")
        self.assertIn("already exists", result.detail)

    def test_a_worker_with_no_free_slot_leaves_the_queue_untouched(self):
        self.queue.enqueue(_recipe(), "base-1")
        with self.gate.hold("someone-else"):
            with self.assertRaises(TooManyTasksError):
                self.work(FakeLauncher())
        self.assertEqual(self.queue.entry("w-0001").state, STATE_QUEUED)

    def test_the_loop_takes_every_task_in_order_and_stops_when_idle(self):
        for number in (1, 2, 3):
            self.queue.enqueue(_recipe(task_id=f"w-000{number}"), "base-1", now=float(number))
        launcher = FakeLauncher()
        results = work_loop(
            self.queue, "worker-1", _policy(), "/ws", launcher, fs=self.fs, git=fake_git(), clock=self.clock, gate=self.gate,
        )
        self.assertEqual([r.task_id for r in results], ["w-0001", "w-0002", "w-0003"])
        self.assertEqual({r.outcome for r in results}, {"succeeded"})

    def test_the_loop_respects_max_tasks_and_returns_a_dead_workers_task_first(self):
        self.queue.enqueue(_recipe(task_id="w-0001"), "base-1", now=1.0)
        self.queue.enqueue(_recipe(task_id="w-0002"), "base-1", now=2.0)
        self.queue.lease("dead-worker", 1.0, now=1.0)  # a worker that took w-0001 and died
        self.assertEqual(self.queue.entry("w-0001").state, STATE_LEASED)
        results = work_loop(
            self.queue, "worker-1", _policy(), "/ws", FakeLauncher(), fs=self.fs, git=fake_git(), clock=self.clock, gate=self.gate,
            max_tasks=1,
        )
        self.assertEqual([r.task_id for r in results], ["w-0001"])
        self.assertEqual(self.queue.entry("w-0002").state, STATE_QUEUED)

    def test_an_unsafe_worker_id_is_refused(self):
        with self.assertRaises(ConfigValidationError):
            work_once(self.queue, "../evil", _policy(), "/ws", FakeLauncher(), fs=self.fs, gate=self.gate)


class WorkCommandTests(unittest.TestCase):
    def run_main(self, argv):
        import contextlib
        import io

        from hydra_umc_dev_server.cli import main

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_queue_work_on_an_empty_queue_stops_at_once(self):
        import json
        from pathlib import Path

        policy = Path(__file__).resolve().parent.parent / "configs" / "task-policy.example.json"
        with tempfile.TemporaryDirectory() as t:
            base = str(Path(t) / "ws")  # created by the command
            code, out, _ = self.run_main(["queue", "work", "--db", str(Path(t) / "q.sqlite3"), "--policy", str(policy), "--workspace-base", base])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"tasks": []})

    def test_queue_work_refuses_a_policy_that_is_not_there(self):
        from pathlib import Path

        with tempfile.TemporaryDirectory() as t:
            code, _, err = self.run_main(["queue", "work", "--db", str(Path(t) / "q.sqlite3"), "--policy", str(Path(t) / "nope.json"), "--workspace-base", Path(t).as_posix()])
        self.assertEqual(code, 1)
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()
