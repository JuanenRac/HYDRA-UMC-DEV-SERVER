<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/DURABLE_QUEUE.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Durable queue and execution journal (DS05)

A SQLite-backed task queue with leases and an append-only journal. It
survives a process restart: reopen the same `.sqlite3` file and every
entry and journal row is still there. Nothing here runs a task - DS04's
`task run` does that; DS05 records, durably, what happened.

## Tables

- **`entries`** - one row per `task_id` (the primary key): the recipe
  JSON, its `recipe_fingerprint` (sha256 of the canonical recipe), the
  pinned `revision`, the `base_fingerprint` recorded at enqueue, the
  `state` (`queued` / `leased` / `succeeded` / `failed` / `cancelled`),
  the `attempt` counter, and the current lease (`leased_by`,
  `lease_expires_at`).
- **`journal`** - append-only. One row per state transition:
  `enqueued`, `leased`, `lease-expired`, `completed`, `result-rejected`,
  `cancelled`. Each row carries `task_id`, `attempt`, `at`, and a JSON
  `detail`.

## The invariants

| DS05 acceptance criterion | How it holds |
| --- | --- |
| a duplicate never creates a second job | `enqueue()` is `INSERT ... ON CONFLICT(task_id) DO NOTHING`; a repeat returns `created=False` and writes no journal row |
| an interruption never produces a false success | `lease()` sets `lease_expires_at`; `reconcile()` returns an expired lease to `queued`; `record_result()` from a worker that is no longer the `leased_by` holder is **rejected**, journal `result-rejected`, state untouched |
| every result identifies revision and recipe | the `completed` journal event always carries `revision` and `recipe_fingerprint` |
| a base that moved invalidates promotion | if the `observed_base_fingerprint` passed to `record_result()` differs from the entry's own, the result is stored `failed` / `promotable=False` even when the run exited `0` |
| logs and disk stay bounded | the journal stores stdout/stderr tails truncated to 2 KiB; `prune_journal(keep_last_n_per_task)` keeps only the newest N rows per task |

## CLI

```
queue enqueue <recipe> --db queue.sqlite3 --base-fingerprint <hex>
queue status   --db queue.sqlite3 [--reconcile]
queue reconcile --db queue.sqlite3
queue journal  <task_id> --db queue.sqlite3
```

`queue reconcile` is safe to run on every process start - it only
returns expired leases to `queued` and is idempotent. `--base-fingerprint`
is any opaque string the caller derives from the source state the task
is pinned to (for example `git rev-parse HEAD` plus a hash of `git
status --porcelain`); DS05 stores it and compares it, it does not
compute it.

## What DS05 still does not do

- it does not run a task or hand one to a worker loop - that glue is
  DS06/DS07
- no AI provider (DS06)
- no cross-host transport - the queue is one local SQLite file
