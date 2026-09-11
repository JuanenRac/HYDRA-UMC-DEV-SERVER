# Changelog: HYDRA-UMC-DEV-SERVER 🖥️

All notable changes to this project will be documented in this file. The
version number follows this ecosystem's "odometer" scheme: PATCH +1 on
every real build, rolling into MINOR past 9 (`0.0.9` -> `0.1.0`); MAJOR is
bumped manually only. See `bump_version.py`.

## [0.1.1] - Honesty check section in every README

Added a "Honesty check" paragraph right after the intro badges in
`README.md` and all 6 translated READMEs, naming all sixteen real
`src/hydra_umc_dev_server/*.py` modules and the real test count (228
passing across `tests/test_*.py`). States plainly what none of that
real, tested code has ever touched: the target Raspberry Pi 5/CM5
hardware, a real remote host via `station preflight`/`station plan`,
a real AI provider behind `provider suggest` (only the deterministic
fake ships), or a running worker loop wiring the pieces together.
Documents the real, current state of what's implemented vs. planned;
no behavior changed.

## [0.1.0] - DS10: delivery package + honest maturity evaluation

Tenth and last delivery of ten. The plan closes the way it opened - by
describing, not claiming.

- `delivery.py`:
  - `build_delivery_manifest()` enumerates what this repository actually
    ships - every `src/hydra_umc_dev_server/*.py` module, every
    `docs/*.md`, every `configs/*.json`, plus `pyproject.toml`,
    `hydra-umc.project.json`, `CHANGELOG.md` and `README.md` - with a
    sha256 per file. It also reads back the real CLI surface (the
    `add_parser(...)` names in `cli.py`), the package version and the
    `tests/test_*.py` count.
  - `evaluate_maturity()` reports each of the ten deliveries as
    `shipped` / `partial` / `not-started` against real evidence (is the
    module actually in the tree). DS06 is reported **`partial`** on
    purpose - only the deterministic fake provider ships. The seven
    `known_limitations` are stated in plain words (no real AI provider,
    no real network transport, no container sandbox, no worker loop
    wiring the pieces together, nothing that provisions a host or
    deploys anything, no target hardware validated, every real-host
    contact behind an injectable seam).
  - `overall_maturity` is hard-coded `"scaffolding"`. This code has no
    branch that returns anything higher - the honesty guard is that the
    evaluation *cannot* over-claim.
- `cli.py` - new `deliver manifest` and `deliver evaluate` subcommands;
  `deliver evaluate` exits non-zero if the maturity is ever not
  `scaffolding`.
- `docs/DELIVERY.md`; `docs/ARCHITECTURE.md`, `docs/CLI_REFERENCE.md`,
  README x7 synced to DS01-DS10.
- 8 new tests (`test_delivery.py` + `deliver` cases in `test_cli.py`) -
  228 total.

The ten-delivery plan is complete. The maturity stays `scaffolding`:
what is here is contracts, limits and a verifiable skeleton. Nothing in
this repository provisions a host, runs a deploy, or has touched target
hardware - and `deliver evaluate` says exactly that.

## [0.0.9] - DS09: stable operation + verified state backup/restore

Ninth delivery of ten.

- `operations.py`:
  - `create_backup()` copies this host's named durable-state files into a
    backup dir and records a sha256 for each, with a `backup_id`, an
    `instance_id` and a `schema_version`. `verify_backup()` re-hashes
    every file and reports `mismatches` / `missing`. `restore_backup()`
    **refuses** a backup taken for a different `instance_id` or a
    different `schema_version`, or one whose files no longer match the
    manifest - otherwise it restores the exact bytes.
  - `check_operational_health(queue, ...)` reports a not-ok `HealthReport`
    with a named finding for: `orphaned-leases` (leased entries whose
    lease has expired but were not reconciled), `journal-over-cap`, and
    `low-disk` (free disk under the configured floor).
  - all filesystem contact is behind the injectable `BackupFs` seam.
- `cli.py` - new `ops health` and `ops verify-backup` subcommands.
- `docs/OPERATIONS.md`, README x7 synced.
- 14 new tests (`test_operations.py` incl. the backup round-trip and each
  refusal, plus `ops` cases in `test_cli.py`) - 220 total.

## [0.0.8] - DS08: one fully controlled repair cycle

Eighth delivery of ten. `RepairCycle` chains the pieces already built
into a single gated sequence:

    repro-confirmed -> incident-raised -> candidate-received
      -> regression-passed -> build-test-passed -> approved
      -> installed -> verified   (or -> recovered / -> blocked)

- `confirm_repro()` needs an actually reproduced failure for **this**
  repro case, or the cycle never opens.
- `receive_candidate()` blocks a candidate whose HMAC signature does not
  verify (tampered / unsigned), or that is pinned to a different
  incident, a different **base fingerprint**, or a different **target**.
- `run_regression()` / `run_build_test()` need a real green `RunResult`
  (`completed`, exit `0`).
- `apply_approval()` needs an approval signed by a **registered**
  approver AND issued **for this exact base and target** - an approval
  for another base/target is blocked.
- `install_isolated()` goes through an injectable `IsolatedInstaller`
  seam (never the real target). `verify()` rolls back and ends the
  cycle `recovered` on a failed post-install check; the I60/T07
  "apparent success" control also voids the result (and rolls back) if
  the base fingerprint moved mid-cycle or the evidence is for a
  different repro case.
- `cli.py` - new `repair check-candidate` subcommand (the candidate
  gate, usable without a live cycle).
- `docs/REPAIR_CYCLE.md`, README x7 synced.
- 16 new tests (`test_repair_cycle.py` incl. the full happy path and
  each block/rollback, plus `repair` cases in `test_cli.py`) - 206
  total.

DS09 (stable operation + restore) does not exist yet.

## [0.0.7] - DS07: authenticated incident transport for the OPS-AGENT round trip

Seventh delivery of ten. A real protocol object - not a manual file
drop - for the incident round trip with HYDRA-UMC-OPS-AGENT.

- **`incident_transport.py`** - every message is HMAC-SHA256-signed by a
  registered node and carries a `nonce`, a `sent_at` and a
  `contract_version`. `verify_message()` rejects, each with a named code
  and a test:
  - `unknown-identity` (the channel is authenticated as a node not in
    the registry)
  - `bad-signature` (HMAC does not match the registered secret)
  - `impersonation` (`from_node` != the identity the channel proved)
  - `replay` (a nonce already accepted) / `stale` (a `sent_at` outside
    the replay window)
  - `overloaded` (more than `max_messages_per_minute` from one node)
  - `incompatible-version`
- **`IncidentSession`** runs the FULL round trip - `submit_incident` ->
  `diagnosis` -> `deploy-verification` - not just the submit. A dropped
  connection leaves the session in `pending-ack`; `reconcile()` re-sends
  the SAME incident with a fresh nonce, and the peer de-dupes on the
  stable `payload.incident_id` (re-ack, never re-process). A network
  blip loses nothing and double-counts nothing.
- **`cli.py`** - new `incident verify` subcommand.
- **`configs/incident-transport.example.json`** (the policy only -
  secrets are operator-held and never committed),
  **`docs/INCIDENT_TRANSPORT.md`**, README x7 synced.
- 17 new tests (`test_incident_transport.py` incl. the in-memory
  round-trip and the dropped-connection reconcile, plus `incident`
  cases in `test_cli.py`) - 190 total.

DS08 (a first fully controlled repair cycle) does not exist yet.

## [0.0.6] - DS06: interchangeable AI provider (deterministic fake) behind a safety contract

Sixth delivery of ten. Only the deterministic **fake** provider ships -
which real provider to use, and its authorization, is a user decision;
`ProviderConfig.kind` accepts `"fake"` and nothing else.

- **`ai_provider.py`** - `AIProvider` protocol (`complete(prompt) ->
  RawCompletion`, or raise). `FakeProvider(scenario=...)` is fully
  deterministic: `ok` returns a stable prompt-derived suggestion;
  `timeout` / `quota` / `malformed` / `injection` exercise each adverse
  path.
- **`run_provider_step(config, provider, prompt, usage_so_far=None)`** -
  the contract:
  - a provider timeout, quota exhaustion or malformed output becomes a
    bounded named outcome (`timed-out` / `budget-exhausted` /
    `rejected`), never an exception that escalates.
  - a configured `ProviderBudget` (calls / tokens / cost) stops the
    step **before** it would exceed - `budget-exhausted`, no call made.
  - the provider's answer is **data, never instructions**. A suggestion
    that says "ignore previous instructions / deploy now / grant me
    root" is copied verbatim into `suggested_text` and `injection_flagged`
    is set, but `grants_no_permissions` and `triggers_no_deploy` are
    **always** true - for every outcome. The result is inert: DS06 wires
    it to nothing (not the runner, not the queue, not a deploy).
- **`cli.py`** - new `provider suggest --config --prompt-file
  [--scenario]` subcommand.
- **`configs/ai-provider.example.json`**, **`docs/AI_PROVIDER.md`**,
  README x7 synced.
- 19 new tests (`test_ai_provider.py` + `provider` cases in
  `test_cli.py`) - 173 total.

DS07 (coordinated incidents with HYDRA-UMC-OPS-AGENT over an
authenticated transport) does not exist yet.

## [0.0.5] - DS05: durable SQLite queue + append-only execution journal

Fifth delivery of ten. A task queue and its execution journal that
survive a process restart. Nothing here runs a task - DS04's runner does
that; this records, durably, what happened.

- **`durable_queue.py`** - `DurableQueue(path)` over SQLite (WAL,
  immediate transactions for the lease). Two tables: `entries` (one row
  per `task_id`, the primary key) and `journal` (append-only).
  - `enqueue(recipe, base_fingerprint)` is idempotent - a second call
    with the same `task_id` returns `created=False` and adds no journal
    row. **A duplicate never becomes a second job.**
  - `lease(worker_id, ttl)` atomically claims the oldest `queued` entry,
    bumps `attempt`, sets `lease_expires_at`. `reconcile()` returns every
    entry whose lease has expired to `queued` (safe on every startup,
    idempotent).
  - `record_result(task_id, worker_id, run_result, observed_base_fingerprint)`
    is **rejected** (not accepted as done) if that worker no longer
    holds the lease - **an interruption never produces a false
    success**. If the observed base fingerprint differs from the one
    recorded at enqueue, the result is stored `failed` / `promotable=False`
    even on exit code `0` - **a base that moved invalidates promotion**.
    The `completed` journal event always carries `revision` and the
    `recipe_fingerprint` (sha256 of the canonical recipe).
  - the journal stores only truncated (2 KiB) stdout/stderr tails, and
    `prune_journal(keep_last_n_per_task)` caps rows - **logs and disk
    stay bounded** regardless of retry churn.
- **`cli.py`** - new `queue enqueue` / `queue status` / `queue reconcile`
  / `queue journal` subcommands.
- **`docs/DURABLE_QUEUE.md`**, README x7 synced.
- 15 new tests (`test_durable_queue.py` incl. a real tmp-file
  restart-survival case, plus `queue` cases in `test_cli.py`) - 156
  total.

DS06 (interchangeable AI provider - a deterministic fake first) does not
exist yet.

## [0.0.4] - DS04: bounded task recipe + isolated workspace runner

Fourth delivery of ten. This is the first delivery that actually
executes something - and it stays tightly gated. `task run` runs one
allow-listed command, in a per-task isolated workspace, with a scrubbed
environment, under a bounded timeout; it deploys nothing.

- **`workspace.py`** - `Workspace.resolve()` / `resolve_with()` refuse a
  path that escapes the workspace: a `..` that climbs past the root, an
  absolute path, or (via the real, symlink-followed path) a symlink
  whose target lands outside. `allocate_workspace()` gives each task id
  its own directory and refuses one that already exists - two tasks
  never share a workspace. All filesystem contact is behind the
  injectable `WorkspaceFs` seam.
- **`recipe.py`** - `TaskRecipe.from_dict()` (DS01-style error
  accumulation): a pinned `revision` (commit hash / vX.Y.Z tag /
  `refs/tags/...` - a bare branch name is rejected), a `command`, a
  bounded `timeout_seconds` (<= 1h). `validate_against(policy)` refuses
  any command whose `argv[0]` is not in the task policy's own
  `allowed_commands` (DS01 schema). `resolved_input_paths(workspace)`
  refuses a declared path that escapes the workspace.
- **`runner.py`** - `run_task()` rejects (spawning nothing) a
  disallowed command or an escaping input path; otherwise it spawns the
  child with a SCRUBBED environment - only `PATH` / `HOME` / `LANG` /
  `TZ` (plus non-secret OS basics on Windows), never an inherited
  `*_TOKEN` / `*_KEY` / `*_SECRET` / `ANTHROPIC_*` / `GITHUB_*` /
  `SSH_*`. On timeout or cancel the WHOLE process group is killed, not
  just the direct child. The `ProcessLauncher` seam lets the control
  tests prove all of this against a fake; `SubprocessLauncher` is the
  real one (POSIX `start_new_session` + `killpg`, Windows
  `CREATE_NEW_PROCESS_GROUP` + `taskkill /T`).
- **`cli.py`** - new `task validate` (recipe vs policy, runs nothing)
  and `task run --workspace-base` (the real, gated execution).
- **`configs/task-recipe.example.json`**,
  **`docs/WORKSPACE_AND_RUNNER.md`**, README x7 synced.
- 34 new tests (`test_workspace.py`, `test_recipe.py`, `test_runner.py`
  incl. one real test that spawns a child-of-a-child and confirms both
  are gone after a cancel, plus `task` cases in `test_cli.py`) - 141
  total.

DS05 (durable queue + traceable results) and DS06 (interchangeable AI
provider) do not exist yet.

## [0.0.3] - DS03: conservative migration (inventory + classification + separate-destination plan)

Third delivery of ten. Still read-and-describe only: nothing here copies a
file, deletes a file, runs a mutating `git` command, or touches the
source in any way.

- **`migration.py`** - `build_repo_inventory()` walks a source checkout
  (exactly the files git considers part of the project - a local
  virtualenv / build output / `__pycache__` is git-ignored and never
  inventoried), SHA-256s every file, and classifies each one:
  `tracked-clean` (published, matches origin), `tracked-modified`
  (uncommitted local edits), `untracked` (working files git does not
  track), `private` (a `PrivacyPolicy` - the private-planning folder, `.env*`, `*.pem`,
  `id_ed25519*`, ... - widenable by a document, never silently
  narrowed). It also records commits on the branch that were never
  pushed.
- **`build_migration_plan()`** - maps every file to exactly one
  destination by class, into four provably-separate roots
  (`MigrationDestinations.from_dict` refuses any pair that is equal or
  nested), plus a `<repo>.unpushed.bundle` under the work-in-progress
  root for the local commits. It refuses outright if a private file
  would ever resolve under a shareable root. The plan is JSON data with
  a full hash manifest; a later delivery (or a person) carries it out.
- **`SourceInspector`** protocol - every real disk/git read goes through
  it, so the whole suite runs against a fake tree; `SystemSourceInspector`
  is the one real, read-only implementation.
- **`cli.py`** - new `migrate inventory` and `migrate plan
  --destinations` subcommands. Accepts a single checkout or a directory
  of them.
- **`configs/migration-destinations.example.json`**,
  **`docs/MIGRATION_FROM_PC.md`** (the guide `docs/ARCHITECTURE.md`
  already referenced), README x7 synced.
- 34 new tests (`test_migration.py` + `migrate` cases in
  `test_cli.py`), 107 total, all offline.

DS04 (workspace + bounded runner), DS05 (durable queue) and DS06
(interchangeable AI provider) do not exist yet.

## [0.0.2] - DS02: reproducible remote station (profile, read-only preflight, dry-run plan)

Second delivery of ten. Still "validate and describe, never act" - no
host is touched, no user created, no port opened, no step executed. All
three new pieces live under the new `station` subcommand.

- **`remote_station.py`** - `RemoteStationProfile` (`RemoteIdentity` +
  `RemoteAccess` + required `ToolchainPolicy` entries), the same
  error-accumulating `from_dict()` shape as DS01's `config.py`. Two
  invariants defended by test, not just prose: the remote-editing
  endpoint binds a loopback/RFC-1918 address, and a routable one is
  refused unless the document sets the literal boolean
  `allow_public_bind: true` (same "a missing/misspelled field never
  grants it" shape as `TaskPolicy.allow_deploy`); the identity is a
  dedicated system account, never `root` and never the CM5 login user.
  Ships `configs/remote-station.example.json`, which binds `127.0.0.1`
  and is tested to.
- **`preflight.py`** - `run_preflight(profile, inspector)` turns a
  profile plus an injectable `HostInspector` into a structured
  `PreflightReport` (Python version, free disk, workspace writable,
  required tools on `PATH`, remote port free, bind address private,
  identity is a real system account). Every real host query goes
  through the inspector seam, so the whole suite runs against a fake and
  nothing contacts a real machine. `SystemHostInspector` is the one
  object that reads the real host - and still only reads.
- **`provision.py`** - `build_provision_plan(profile, preflight=None)`
  returns a `ProvisionPlan`: an ordered list of `ProvisionStep`s with
  each step's argv captured as data, plus the full systemd unit text
  that would be written. It refuses to return a plan at all when built
  over a failed preflight. The unit template keeps `AF_NETLINK` in
  `RestrictAddressFamilies` on purpose - a too-tight family list has
  caused a real crash-loop elsewhere in this ecosystem.
- **`cli.py`** - new `station validate` / `station preflight` /
  `station plan` subcommands. `station preflight` is the only command
  that inspects the real host; it changes nothing and exits non-zero
  when the host is not ready.
- 30 new tests (`test_remote_station.py`, `test_preflight.py`,
  `test_provision.py`, plus `station` cases in `test_cli.py`) - 85
  total, all offline.

DS04 (workspace + bounded runner), DS05 (durable queue) and DS06
(interchangeable AI provider) do not exist yet.

## [0.0.1] - DS01: contracts, limits and a verifiable skeleton

First delivery of ten (DS01-DS10, see the README's own Roadmap section).
This one only: a real, tested configuration schema
(`HostProfile`/`ToolchainPolicy`/`TaskPolicy`, `src/hydra_umc_dev_server/
config.py`) whose default policy grants no task deployment permission
(`TaskPolicy.allow_deploy` defaults to `False` and is only ever `True`
when a document sets the literal JSON boolean `true` - verified by test,
including that a non-boolean value never grants it), and read-only
manifest discovery (`inventory.py`, the same real, tested pattern
HYDRA-UMC-OPS-AGENT's own edge role already uses) that can find and
validate this ecosystem's own `hydra-umc.project.json` files - including
this repository's own, which is exactly this delivery's own acceptance
criterion: the catalog recognizes a new manifest in its own fixtures.

No remote host, workspace, task runner, durable queue or AI provider
integration exists yet - those are DS02, DS04, DS05 and DS06, later
deliveries. This repository does not yet decide that a machine is safe,
does not yet run a task, and does not yet talk to HYDRA-UMC-OPS-AGENT.

`docs/ARCHITECTURE.md` and `docs/OPS_INTEGRATION.md` document this
repository's own state-ownership table and its grouping of the 17
cross-project relationships into necessary/optional/development-only.
