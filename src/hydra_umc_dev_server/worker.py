# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/worker.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The worker loop that joins the pieces of a task's life.

`work_once` takes the oldest queued task of the durable queue and carries it through:

  lease -> allocate the workspace -> stage `repo@revision` -> run (renewing the lease while it
  runs) -> record the result -> apply the retention of the workspace

Every step is the one the single-shot `task run` already uses; what is new is that the lease is
renewed during the run (a task longer than the lease no longer loses it half-way), that a lease
lost anyway cancels the run instead of letting it finish unseen, and that whatever happens to a
task ends in a recorded result: a refusal to stage, a policy that no longer allows the command, a
sandbox that is not there. A task that cannot even start is recorded as failed, never left leased.

The process launcher, the git runner, the clock and the filesystem are injectable, so the loop is
tested without a process, a network or a real git. The slot of the concurrency gate is taken by the
worker, before it leases anything: a worker that has no free slot leaves the queue untouched.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from .config import ConfigValidationError, TaskPolicy
from .durable_queue import DurableQueue, LeaseGrant
from .runner import CancelToken, ProcessLauncher, RunResult, run_task
from .taskflow import ConcurrencyGate, GitRunner, remove_workspace, should_remove, stage_repo, _system_git
from .workspace import SystemWorkspaceFs, WorkspaceFs, _require_safe_id, allocate_workspace

DEFAULT_LEASE_SECONDS = 120.0


@dataclass(frozen=True)
class WorkResult:
    """What one pass of the worker did."""

    task_id: str | None
    outcome: str  # "idle", "succeeded", "failed", "lease-lost"
    detail: str = ""
    staged_commit: str | None = None
    run: RunResult | None = None
    workspace_removed: bool = False
    recorded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "outcome": self.outcome,
            "detail": self.detail,
            "staged_commit": self.staged_commit,
            "run": self.run.to_dict() if self.run else None,
            "workspace_removed": self.workspace_removed,
            "recorded": self.recorded,
        }


class _RenewingClock:
    """The clock `run_task` polls with: every sleep is a chance to renew the lease, and a lease
    that cannot be renewed cancels the run."""

    def __init__(
        self, queue: DurableQueue, grant: LeaseGrant, lease_seconds: float, token: CancelToken, clock: Any,
    ) -> None:
        self._queue = queue
        self._grant = grant
        self._lease_seconds = lease_seconds
        self._token = token
        self._clock = clock
        self._next_renewal = clock.monotonic() + lease_seconds / 3
        self.lost = False
        self.renewals = 0

    def monotonic(self) -> float:
        return float(self._clock.monotonic())

    def sleep(self, seconds: float) -> None:
        self._clock.sleep(seconds)
        if self.lost or self._clock.monotonic() < self._next_renewal:
            return
        self._next_renewal = self._clock.monotonic() + self._lease_seconds / 3
        if self._queue.renew_lease(self._grant.task_id, self._grant.worker_id, self._lease_seconds):
            self.renewals += 1
        else:
            self.lost = True
            self._token.cancel()


def _failed_run(grant: LeaseGrant, reason: str) -> RunResult:
    return RunResult(task_id=grant.task_id, outcome="rejected", exit_code=None, duration_seconds=0.0, rejection_reason=reason)


def work_once(
    queue: DurableQueue,
    worker_id: str,
    policy: TaskPolicy,
    workspace_base: str,
    launcher: ProcessLauncher,
    *,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
    fs: WorkspaceFs | None = None,
    git: GitRunner = _system_git,
    clock: Any = time,
    observe_base: Callable[[LeaseGrant], str] | None = None,
    poll_interval: float = 0.05,
    gate: ConcurrencyGate | None = None,
) -> WorkResult:
    """One pass: lease the oldest queued task and carry it to a recorded result.

    `observe_base` answers what the base is NOW (the same kind of fingerprint given at enqueue);
    without it the base is taken as unchanged, so only a caller that can observe the base gets the
    "base moved" refusal of the queue."""
    _require_safe_id(worker_id)
    filesystem = fs if fs is not None else SystemWorkspaceFs()
    gate = gate if gate is not None else ConcurrencyGate(workspace_base, policy.max_concurrent_tasks)
    # the slot of this worker is taken before anything is leased
    with gate.hold(f"worker-{worker_id}"):
        grant = queue.lease(worker_id, lease_seconds)
        if grant is None:
            return WorkResult(task_id=None, outcome="idle")
        recipe = grant.recipe
        staged: str | None = None
        removed = False
        token = CancelToken()
        renewing = _RenewingClock(queue, grant, lease_seconds, token, clock)
        workspace = None
        try:
            workspace = allocate_workspace(workspace_base, recipe.task_id, filesystem)
            source = policy.repo_sources.get(recipe.repo)
            if source is not None:
                staged = stage_repo(workspace.root, source, recipe.revision, run=git)
            result = run_task(
                recipe, policy, workspace, launcher, cancel_token=token, poll_interval=poll_interval, clock=renewing, fs=filesystem,
            )
        except ConfigValidationError as exc:
            # a refusal before or while starting (collision, staging, sandbox required but absent)
            result = _failed_run(grant, str(exc))
        observed = observe_base(grant) if observe_base is not None else grant.base_fingerprint
        recorded = queue.record_result(grant.task_id, worker_id, result, observed)
        ok = result.outcome == "completed" and result.exit_code == 0
        if workspace is not None and should_remove(policy.workspace_retention, completed_ok=ok):
            removed = remove_workspace(workspace_base, recipe.task_id)
        if renewing.lost:
            outcome = "lease-lost"
        else:
            outcome = "succeeded" if recorded.accepted and recorded.final_state == "succeeded" else "failed"
        detail = result.rejection_reason or recorded.reason or ""
        return WorkResult(
            task_id=grant.task_id, outcome=outcome, detail=detail or "", staged_commit=staged, run=result,
            workspace_removed=removed, recorded=recorded.accepted,
        )


def work_loop(
    queue: DurableQueue,
    worker_id: str,
    policy: TaskPolicy,
    workspace_base: str,
    launcher: ProcessLauncher,
    *,
    max_tasks: int | None = None,
    stop_when_idle: bool = True,
    idle_sleep: float = 2.0,
    clock: Any = time,
    **kwargs: Any,
) -> list[WorkResult]:
    """Run `work_once` until the queue is empty (`stop_when_idle`) or `max_tasks` were taken.
    A reconcile first returns the tasks of a worker that died to the queue."""
    queue.reconcile()
    results: list[WorkResult] = []
    while max_tasks is None or len(results) < max_tasks:
        result = work_once(queue, worker_id, policy, workspace_base, launcher, clock=clock, **kwargs)
        if result.outcome == "idle":
            if stop_when_idle:
                break
            clock.sleep(idle_sleep)
            queue.reconcile()
            continue
        results.append(result)
    return results
