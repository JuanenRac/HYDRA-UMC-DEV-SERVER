# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/durable_queue.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS05 - a durable task queue with leases and an append-only execution
journal, backed by SQLite so it survives a process restart.

DS05's acceptance criteria, each defended by test:

  * a duplicate `enqueue` (same `task_id`) never creates a second job -
    the id is the primary key, `INSERT ... ON CONFLICT DO NOTHING`.
  * an interruption never produces a false success - a crashed worker's
    lease expires, `reconcile()` returns the entry to `queued`, and a
    late `record_result()` from a worker that no longer holds the lease
    is rejected, not accepted as done.
  * every result identifies the revision AND the exact recipe - the
    `completed` journal event carries `revision` and a `recipe_fingerprint`
    (sha256 of the canonical recipe JSON).
  * a base changed during the task invalidates promotion - if the base
    fingerprint observed at result time differs from the one recorded at
    enqueue time, the result is stored `failed` / `promotable=False`
    even when the command exited 0.
  * logs and disk stay bounded - the journal stores only truncated
    stdout/stderr tails, and `prune_journal()` caps rows per task.

Nothing here runs a task; DS04's runner does that. This module only
records what happened, durably.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from .recipe import TaskRecipe

_JOURNAL_TAIL_CAP = 2 * 1024
_DEFAULT_KEEP_PER_TASK = 50

STATE_QUEUED = "queued"
STATE_LEASED = "leased"
STATE_SUCCEEDED = "succeeded"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    task_id            TEXT PRIMARY KEY,
    recipe_json        TEXT NOT NULL,
    recipe_fingerprint TEXT NOT NULL,
    revision           TEXT NOT NULL,
    base_fingerprint   TEXT NOT NULL,
    state              TEXT NOT NULL,
    attempt            INTEGER NOT NULL DEFAULT 0,
    leased_by          TEXT,
    lease_expires_at   REAL,
    enqueued_at        REAL NOT NULL,
    updated_at         REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS journal (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id  TEXT NOT NULL,
    attempt  INTEGER NOT NULL,
    event    TEXT NOT NULL,
    at       REAL NOT NULL,
    detail   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS journal_by_task ON journal(task_id, id);
CREATE INDEX IF NOT EXISTS entries_by_state ON entries(state, enqueued_at);
"""


def recipe_fingerprint(recipe: TaskRecipe) -> str:
    canonical = json.dumps(recipe.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QueueEntry:
    task_id: str
    recipe: TaskRecipe
    recipe_fingerprint: str
    revision: str
    base_fingerprint: str
    state: str
    attempt: int
    leased_by: str | None
    lease_expires_at: float | None
    enqueued_at: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "recipe": self.recipe.to_dict(),
            "recipe_fingerprint": self.recipe_fingerprint,
            "revision": self.revision,
            "base_fingerprint": self.base_fingerprint,
            "state": self.state,
            "attempt": self.attempt,
            "leased_by": self.leased_by,
            "lease_expires_at": self.lease_expires_at,
            "enqueued_at": self.enqueued_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class EnqueueOutcome:
    created: bool
    entry: QueueEntry


@dataclass(frozen=True)
class LeaseGrant:
    task_id: str
    worker_id: str
    attempt: int
    lease_expires_at: float
    recipe: TaskRecipe
    revision: str
    base_fingerprint: str


@dataclass(frozen=True)
class RecordOutcome:
    accepted: bool
    final_state: str
    promotable: bool
    reason: str | None = None


class DurableQueueError(RuntimeError):
    pass


def _row_to_entry(row: sqlite3.Row) -> QueueEntry:
    return QueueEntry(
        task_id=row["task_id"],
        recipe=TaskRecipe.from_dict(json.loads(row["recipe_json"])),
        recipe_fingerprint=row["recipe_fingerprint"],
        revision=row["revision"],
        base_fingerprint=row["base_fingerprint"],
        state=row["state"],
        attempt=row["attempt"],
        leased_by=row["leased_by"],
        lease_expires_at=row["lease_expires_at"],
        enqueued_at=row["enqueued_at"],
        updated_at=row["updated_at"],
    )


class DurableQueue:
    """A SQLite-backed durable queue. `path=":memory:"` for a test; a real
    file for a real host. One instance per process; safe for several
    processes over the same file (WAL + immediate transactions for the
    lease)."""

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, timeout=30, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DurableQueue":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- write path -----------------------------------------------------
    def _journal(self, task_id: str, attempt: int, event: str, at: float, detail: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO journal(task_id, attempt, event, at, detail) VALUES (?, ?, ?, ?, ?)",
            (task_id, attempt, event, at, json.dumps(detail, sort_keys=True)),
        )

    def enqueue(
        self, recipe: TaskRecipe, base_fingerprint: str, *, now: float | None = None
    ) -> EnqueueOutcome:
        """Add one task. A second call with the same `recipe.task_id` is a
        no-op (returns `created=False`) - never a second job."""
        at = time.time() if now is None else now
        fp = recipe_fingerprint(recipe)
        cur = self._conn.execute(
            """
            INSERT INTO entries(task_id, recipe_json, recipe_fingerprint, revision,
                                base_fingerprint, state, attempt, enqueued_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(task_id) DO NOTHING
            """,
            (
                recipe.task_id, json.dumps(recipe.to_dict()), fp, recipe.revision,
                base_fingerprint, STATE_QUEUED, at, at,
            ),
        )
        created = cur.rowcount == 1
        if created:
            self._journal(recipe.task_id, 0, "enqueued", at, {"revision": recipe.revision, "recipe_fingerprint": fp})
        entry = self.entry(recipe.task_id)
        assert entry is not None
        return EnqueueOutcome(created=created, entry=entry)

    def lease(self, worker_id: str, ttl_seconds: float, *, now: float | None = None) -> LeaseGrant | None:
        """Atomically claim the oldest `queued` entry for `worker_id` for
        `ttl_seconds`. Returns None if the queue has nothing runnable."""
        if ttl_seconds <= 0:
            raise DurableQueueError("lease ttl must be positive")
        at = time.time() if now is None else now
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                f"SELECT * FROM entries WHERE state = '{STATE_QUEUED}' ORDER BY enqueued_at, task_id LIMIT 1"
            ).fetchone()
            if row is None:
                self._conn.execute("COMMIT")
                return None
            attempt = row["attempt"] + 1
            expires = at + ttl_seconds
            self._conn.execute(
                "UPDATE entries SET state=?, leased_by=?, lease_expires_at=?, attempt=?, updated_at=? WHERE task_id=?",
                (STATE_LEASED, worker_id, expires, attempt, at, row["task_id"]),
            )
            self._journal(row["task_id"], attempt, "leased", at, {"worker_id": worker_id, "lease_expires_at": expires})
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        entry = _row_to_entry(row)
        return LeaseGrant(
            task_id=entry.task_id, worker_id=worker_id, attempt=attempt, lease_expires_at=expires,
            recipe=entry.recipe, revision=entry.revision, base_fingerprint=entry.base_fingerprint,
        )

    def renew_lease(self, task_id: str, worker_id: str, ttl_seconds: float, *, now: float | None = None) -> bool:
        at = time.time() if now is None else now
        cur = self._conn.execute(
            "UPDATE entries SET lease_expires_at=?, updated_at=? WHERE task_id=? AND state=? AND leased_by=?",
            (at + ttl_seconds, at, task_id, STATE_LEASED, worker_id),
        )
        return cur.rowcount == 1

    def record_result(
        self,
        task_id: str,
        worker_id: str,
        run_result: Any,
        observed_base_fingerprint: str,
        *,
        now: float | None = None,
    ) -> RecordOutcome:
        """Record the outcome of one run. Rejected (not accepted as done)
        if this worker no longer holds the lease - an interruption never
        becomes a false success. If the base moved since enqueue, the
        result is stored `failed` / not promotable even on exit code 0."""
        at = time.time() if now is None else now
        entry = self.entry(task_id)
        if entry is None:
            raise DurableQueueError(f"no such task {task_id!r}")
        if entry.state != STATE_LEASED or entry.leased_by != worker_id:
            self._journal(task_id, entry.attempt, "result-rejected", at, {
                "reason": "worker does not hold a valid lease",
                "worker_id": worker_id, "entry_state": entry.state,
            })
            return RecordOutcome(accepted=False, final_state=entry.state, promotable=False,
                                 reason="worker does not hold a valid lease")

        outcome = getattr(run_result, "outcome", "unknown")
        exit_code = getattr(run_result, "exit_code", None)
        ran_ok = outcome == "completed" and exit_code == 0
        base_moved = observed_base_fingerprint != entry.base_fingerprint

        final_state = STATE_SUCCEEDED if (ran_ok and not base_moved) else STATE_FAILED
        promotable = ran_ok and not base_moved
        reason = None
        if base_moved:
            reason = "base changed during the task - candidate not promotable"
        elif not ran_ok:
            reason = f"run outcome {outcome!r} exit_code {exit_code!r}"

        self._conn.execute(
            "UPDATE entries SET state=?, leased_by=NULL, lease_expires_at=NULL, updated_at=? WHERE task_id=?",
            (final_state, at, task_id),
        )
        self._journal(task_id, entry.attempt, "completed", at, {
            "final_state": final_state,
            "promotable": promotable,
            "revision": entry.revision,
            "recipe_fingerprint": entry.recipe_fingerprint,
            "outcome": outcome,
            "exit_code": exit_code,
            "base_moved": base_moved,
            "stdout_tail": str(getattr(run_result, "stdout_tail", ""))[-_JOURNAL_TAIL_CAP:],
            "stderr_tail": str(getattr(run_result, "stderr_tail", ""))[-_JOURNAL_TAIL_CAP:],
            "reason": reason,
        })
        return RecordOutcome(accepted=True, final_state=final_state, promotable=promotable, reason=reason)

    def cancel(self, task_id: str, *, now: float | None = None) -> bool:
        at = time.time() if now is None else now
        cur = self._conn.execute(
            f"UPDATE entries SET state=?, leased_by=NULL, lease_expires_at=NULL, updated_at=? "
            f"WHERE task_id=? AND state IN ('{STATE_QUEUED}', '{STATE_LEASED}')",
            (STATE_CANCELLED, at, task_id),
        )
        if cur.rowcount == 1:
            self._journal(task_id, self.entry(task_id).attempt, "cancelled", at, {})  # type: ignore[union-attr]
        return cur.rowcount == 1

    def reconcile(self, *, now: float | None = None) -> int:
        """Return every entry whose lease has expired to `queued`. Safe to
        call on every startup and any time; idempotent."""
        at = time.time() if now is None else now
        rows = self._conn.execute(
            f"SELECT task_id, attempt FROM entries WHERE state='{STATE_LEASED}' AND lease_expires_at < ?",
            (at,),
        ).fetchall()
        for row in rows:
            self._conn.execute(
                "UPDATE entries SET state=?, leased_by=NULL, lease_expires_at=NULL, updated_at=? WHERE task_id=?",
                (STATE_QUEUED, at, row["task_id"]),
            )
            self._journal(row["task_id"], row["attempt"], "lease-expired", at, {"note": "returned to queued by reconcile"})
        return len(rows)

    def prune_journal(self, *, keep_last_n_per_task: int = _DEFAULT_KEEP_PER_TASK) -> int:
        """Keep only the newest N journal rows per task; return how many
        were deleted. Bounds disk regardless of retry churn."""
        cur = self._conn.execute(
            """
            DELETE FROM journal WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (PARTITION BY task_id ORDER BY id DESC) AS rn FROM journal
                ) WHERE rn > ?
            )
            """,
            (keep_last_n_per_task,),
        )
        return cur.rowcount

    # -- read path ----------------------------------------------------
    def entry(self, task_id: str) -> QueueEntry | None:
        row = self._conn.execute("SELECT * FROM entries WHERE task_id=?", (task_id,)).fetchone()
        return _row_to_entry(row) if row is not None else None

    def journal_for(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT attempt, event, at, detail FROM journal WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
        return [
            {"attempt": r["attempt"], "event": r["event"], "at": r["at"], "detail": json.loads(r["detail"])}
            for r in rows
        ]

    def stats(self) -> dict[str, Any]:
        by_state = {
            row["state"]: row["n"]
            for row in self._conn.execute("SELECT state, COUNT(*) AS n FROM entries GROUP BY state")
        }
        journal_rows = self._conn.execute("SELECT COUNT(*) AS n FROM journal").fetchone()["n"]
        return {"by_state": by_state, "journal_rows": journal_rows}
