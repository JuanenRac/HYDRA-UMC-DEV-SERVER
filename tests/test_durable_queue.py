# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_durable_queue.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS05. Every DS05 acceptance criterion, against an in-memory or
tmp-file SQLite queue - nothing external, nothing that runs a task."""
import tempfile
import unittest
from pathlib import Path

from hydra_umc_dev_server.durable_queue import (
    STATE_CANCELLED,
    STATE_FAILED,
    STATE_LEASED,
    STATE_QUEUED,
    STATE_SUCCEEDED,
    DurableQueue,
    recipe_fingerprint,
)
from hydra_umc_dev_server.recipe import TaskRecipe
from hydra_umc_dev_server.runner import RunResult


def _recipe(task_id="q-0001", revision="0.0.5", command=("pytest", "-q")) -> TaskRecipe:
    return TaskRecipe.from_dict({
        "task_id": task_id, "repo": "HYDRA-UMC-DEV-SERVER", "revision": revision,
        "command": list(command), "timeout_seconds": 60, "input_paths": [],
    })


def _run_result(outcome="completed", exit_code=0) -> RunResult:
    return RunResult(task_id="q-0001", outcome=outcome, exit_code=exit_code, duration_seconds=0.5,
                     stdout_tail="ok", stderr_tail="")


class EnqueueIdempotencyTests(unittest.TestCase):
    def test_a_duplicate_task_id_is_never_a_second_job(self):
        with DurableQueue(":memory:") as q:
            first = q.enqueue(_recipe(), "base-1", now=1000.0)
            second = q.enqueue(_recipe(), "base-1", now=1001.0)
            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual(q.stats()["by_state"], {STATE_QUEUED: 1})
            enqueued_events = [e for e in q.journal_for("q-0001") if e["event"] == "enqueued"]
            self.assertEqual(len(enqueued_events), 1)


class LeaseTests(unittest.TestCase):
    def test_lease_claims_the_oldest_queued_entry(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe("a"), "b", now=1000.0)
            q.enqueue(_recipe("b"), "b", now=1001.0)
            first = q.lease("w1", 30, now=1002.0)
            self.assertEqual(first.task_id, "a")
            self.assertEqual(first.attempt, 1)
            self.assertEqual(q.entry("a").state, STATE_LEASED)
            self.assertEqual(q.entry("a").leased_by, "w1")
            self.assertEqual(q.lease("w1", 30, now=1003.0).task_id, "b")
            self.assertIsNone(q.lease("w1", 30, now=1004.0))


class ReconcileTests(unittest.TestCase):
    def test_an_expired_lease_returns_the_task_to_queued(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "b", now=1000.0)
            q.lease("w1", 10, now=1000.0)
            self.assertEqual(q.reconcile(now=1005.0), 0)   # not expired yet
            self.assertEqual(q.reconcile(now=1011.0), 1)   # expired
            entry = q.entry("q-0001")
            self.assertEqual(entry.state, STATE_QUEUED)
            self.assertIsNone(entry.leased_by)
            self.assertIn("lease-expired", [e["event"] for e in q.journal_for("q-0001")])

    def test_reconcile_is_idempotent(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "b", now=1000.0)
            q.lease("w1", 10, now=1000.0)
            self.assertEqual(q.reconcile(now=1020.0), 1)
            self.assertEqual(q.reconcile(now=1030.0), 0)


class FalseSuccessTests(unittest.TestCase):
    def test_a_result_from_a_worker_that_lost_its_lease_is_rejected_not_marked_done(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "b", now=1000.0)
            q.lease("w1", 10, now=1000.0)
            q.reconcile(now=1020.0)  # w1's lease expired; task is back to queued
            outcome = q.record_result("q-0001", "w1", _run_result(), "b", now=1021.0)
            self.assertFalse(outcome.accepted)
            self.assertNotEqual(q.entry("q-0001").state, STATE_SUCCEEDED)
            self.assertIn("result-rejected", [e["event"] for e in q.journal_for("q-0001")])

    def test_a_result_from_a_different_worker_while_one_holds_the_lease_is_rejected(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "b", now=1000.0)
            q.lease("w1", 30, now=1000.0)
            self.assertFalse(q.record_result("q-0001", "w2", _run_result(), "b", now=1001.0).accepted)


class ResultRecordingTests(unittest.TestCase):
    def test_a_clean_run_on_an_unchanged_base_is_succeeded_and_promotable(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "base-1", now=1000.0)
            q.lease("w1", 30, now=1000.0)
            outcome = q.record_result("q-0001", "w1", _run_result(), "base-1", now=1005.0)
            self.assertTrue(outcome.accepted)
            self.assertEqual(outcome.final_state, STATE_SUCCEEDED)
            self.assertTrue(outcome.promotable)
            self.assertEqual(q.entry("q-0001").state, STATE_SUCCEEDED)
            completed = next(e for e in q.journal_for("q-0001") if e["event"] == "completed")
            self.assertEqual(completed["detail"]["revision"], "0.0.5")
            self.assertEqual(completed["detail"]["recipe_fingerprint"], recipe_fingerprint(_recipe()))

    def test_a_base_that_moved_since_enqueue_blocks_promotion_even_on_exit_zero(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "base-1", now=1000.0)
            q.lease("w1", 30, now=1000.0)
            outcome = q.record_result("q-0001", "w1", _run_result(outcome="completed", exit_code=0), "base-2", now=1005.0)
            self.assertTrue(outcome.accepted)
            self.assertEqual(outcome.final_state, STATE_FAILED)
            self.assertFalse(outcome.promotable)
            self.assertIn("base changed", outcome.reason or "")
            self.assertEqual(q.entry("q-0001").state, STATE_FAILED)

    def test_a_nonzero_exit_is_recorded_failed_and_not_promotable(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "base-1", now=1000.0)
            q.lease("w1", 30, now=1000.0)
            outcome = q.record_result("q-0001", "w1", _run_result(outcome="completed", exit_code=1), "base-1", now=1005.0)
            self.assertEqual(outcome.final_state, STATE_FAILED)
            self.assertFalse(outcome.promotable)


class RestartAndBoundsTests(unittest.TestCase):
    def test_the_queue_and_journal_survive_a_process_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "queue.sqlite3")
            q1 = DurableQueue(db)
            q1.enqueue(_recipe(), "base-1", now=1000.0)
            q1.lease("w1", 10, now=1000.0)
            q1.close()

            q2 = DurableQueue(db)  # "restart"
            self.assertEqual(q2.entry("q-0001").state, STATE_LEASED)
            self.assertEqual(q2.reconcile(now=1020.0), 1)
            self.assertEqual(q2.entry("q-0001").state, STATE_QUEUED)
            self.assertGreaterEqual(len(q2.journal_for("q-0001")), 3)
            q2.close()

    def test_prune_journal_bounds_rows_per_task(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "b", now=0.0)
            for i in range(5):  # 5 lease/expire cycles => 10 more journal rows
                q.lease("w1", 1, now=100.0 + i * 10)
                q.reconcile(now=105.0 + i * 10)
            self.assertGreater(len(q.journal_for("q-0001")), 5)
            deleted = q.prune_journal(keep_last_n_per_task=5)
            self.assertGreater(deleted, 0)
            self.assertEqual(len(q.journal_for("q-0001")), 5)


class CancelAndFingerprintTests(unittest.TestCase):
    def test_cancel_moves_a_queued_task_to_cancelled(self):
        with DurableQueue(":memory:") as q:
            q.enqueue(_recipe(), "b", now=1000.0)
            self.assertTrue(q.cancel("q-0001", now=1001.0))
            self.assertEqual(q.entry("q-0001").state, STATE_CANCELLED)
            self.assertFalse(q.cancel("q-0001", now=1002.0))

    def test_the_recipe_fingerprint_changes_with_the_recipe(self):
        a = recipe_fingerprint(_recipe(command=("pytest", "-q")))
        b = recipe_fingerprint(_recipe(command=("pytest", "-x")))
        self.assertNotEqual(a, b)
        self.assertEqual(a, recipe_fingerprint(_recipe(command=("pytest", "-q"))))


if __name__ == "__main__":
    unittest.main()
