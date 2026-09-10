# Changelog: HYDRA-UMC-DEV-SERVER 🖥️

All notable changes to this project will be documented in this file. The
version number follows this ecosystem's "odometer" scheme: PATCH +1 on
every real build, rolling into MINOR past 9 (`0.0.9` -> `0.1.0`); MAJOR is
bumped manually only. See `bump_version.py`.

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
