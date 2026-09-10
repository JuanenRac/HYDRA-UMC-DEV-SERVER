<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/CLI_REFERENCE.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# CLI reference (DS01 + DS02 + DS03 + DS04 + DS05 + DS06 + DS07 + DS08 + DS09 + DS10)

`hydra-umc-dev-server` (entry point installed by `pip install -e .`) or
`python -m hydra_umc_dev_server.cli` - both run the exact same code.

## `config validate <config_file> --kind {host-profile,toolchain,task-policy}`

Loads `<config_file>` as JSON and validates it against the named schema
(see `CONFIG_SCHEMA.md`). Prints `VALID: ...` and the parsed document on
success (exit code `0`), or `INVALID: ...` with every violation found on
stderr (exit code `1`) - never a raw Python traceback.

```
$ hydra-umc-dev-server config validate configs/task-policy.example.json --kind task-policy
VALID: configs/task-policy.example.json (task-policy)
{
  "allow_deploy": false,
  "max_concurrent_tasks": 2,
  "allowed_commands": ["pytest", "build.sh", "build-test.sh"]
}
```

## `inventory scan --root DIR [--out FILE]`

Scans the immediate subdirectories of `DIR` for a real
`hydra-umc.project.json` in each, and reports every one found (name,
version, maturity, path) plus every real issue hit along the way (a
present-but-unreadable/malformed/incomplete manifest - never silently
dropped). A subdirectory with no manifest at all is not an issue; most
directories under a workspace root are not HYDRA-UMC/URTC checkouts.

```
$ hydra-umc-dev-server inventory scan --root ..
{
  "root": "..",
  "projects": [
    {"name": "HYDRA-UMC-DEV-SERVER", "version": "0.1.0", "maturity": "scaffolding", "manifest_path": "../HYDRA-UMC-DEV-SERVER/hydra-umc.project.json"},
    ...
  ],
  "issues": []
}
```

Writes to `--out FILE` instead of stdout when given.

## `station validate <config_file>` (DS02)

Loads `<config_file>` as a remote-station profile and validates it (see
`REMOTE_STATION.md`). Prints `VALID: ...` and the parsed profile on
success (exit `0`), or `INVALID: ...` with every violation on stderr
(exit `1`). The two rules worth calling out: a routable/public
`bind_address` is refused unless the document sets `allow_public_bind`
to the literal boolean `true`, and `identity.user` may not be `root` or
a normal login user.

## `station preflight <config_file>` (DS02)

Reads the profile and checks whether **this** host is ready to become
that station: Python version, free disk at the workspace path, workspace
writable, each required tool on `PATH`, the remote port free, the bind
address private (or explicitly opted-in), and the identity being a real
dedicated system account. Prints the full `PreflightReport` as JSON,
then `PREFLIGHT=PASS` (exit `0`) or `PREFLIGHT=FAIL <check names>` on
stderr (exit `1`). **This command only reads the host - it creates no
user, installs nothing, opens no port.**

## `station plan <config_file> [--preflight]` (DS02)

Prints the dry-run provisioning plan for the profile as JSON: an ordered
list of steps (each with the exact argv a real installer would run,
captured as data) plus the systemd unit text that would be written.
With `--preflight`, the read-only host check runs first and the plan is
refused if the host is not ready. **Nothing in this command is ever
executed** - it is a document, not an action.

## `migrate inventory <source_root>` (DS03)

Walks a git checkout (or every checkout in the immediate subdirectories
of `source_root`), SHA-256s every file git considers part of the project,
and classifies each: `tracked-clean` / `tracked-modified` / `untracked` /
`private`. Also lists commits on the branch that were never pushed.
Prints the inventory as JSON. **Read-only** - it never writes to the
source or runs a mutating git command.

## `migrate plan <source_root> --destinations FILE` (DS03)

Reads `FILE` (a migration-destinations JSON document - four absolute,
provably-separate roots plus an optional `privacy_policy` block; see
`CONFIG_SCHEMA.md` and `configs/migration-destinations.example.json`) and
prints the migration plan: every file mapped to exactly one destination
by class, a `<repo>.unpushed.bundle` under the work-in-progress root if
there are unpushed commits, and a full `relpath -> sha256` manifest.
Prints `REFUSED: ...` and exits `1` if a private file would ever resolve
under a shareable root. **Copies nothing; touches nothing in the source.**

## `task validate <recipe_file> --policy <task-policy_file>` (DS04)

Loads `<recipe_file>` as a task recipe and checks it against a task
policy (see `WORKSPACE_AND_RUNNER.md`): a pinned `revision` (commit hash
/ `vX.Y.Z` tag / `refs/tags/...` - a bare branch name is refused), a
bounded `timeout_seconds`, and a `command` whose `argv[0]` is in the
policy's own `allowed_commands`. Prints `VALID: ...` (exit `0`) or
`INVALID: ...` (exit `1`). **Runs nothing.**

## `task run <recipe_file> --policy <file> --workspace-base <dir>` (DS04)

Allocates `<workspace-base>/<task_id>/` (refusing one that already
exists - two tasks never share a workspace), validates the recipe
against the policy, then runs the recipe's allow-listed `command` in
that workspace with a **scrubbed environment** (only `PATH` / `HOME` /
`LANG` / `TZ`, plus non-secret OS basics on Windows - never an inherited
`*_TOKEN` / `*_KEY` / `*_SECRET` / `ANTHROPIC_*` / `GITHUB_*` /
`SSH_*`), under `timeout_seconds`. On timeout the **whole process
group** is killed, not just the direct child. Prints the `RunResult`
JSON (`outcome`: `completed` / `timed-out` / `cancelled` / `rejected`,
`exit_code`, bounded stdout/stderr tails, `killed_process_group`).
Exits `0` only on `completed` with exit code `0`. A disallowed command
or an escaping input path is `rejected` with **nothing spawned**. It
deploys nothing.

## `queue enqueue <recipe_file> --db PATH --base-fingerprint HEX` (DS05)

Adds one task recipe to a SQLite durable queue (created if absent). A
second call with the same `task_id` is a no-op - `created: false`, no
journal row, never a second job. `--base-fingerprint` is any opaque
string the caller derives from the source state the task is pinned to;
DS05 stores it and later compares it.

## `queue status --db PATH [--reconcile]` (DS05)

Prints entry counts by state and the journal row count. `--reconcile`
first returns every expired lease to `queued`.

## `queue reconcile --db PATH` (DS05)

Returns every entry whose lease has expired to `queued`. Safe on every
process start; idempotent. Prints `{"returned_to_queued": N}`.

## `queue journal <task_id> --db PATH` (DS05)

Prints the append-only execution journal for one task (`enqueued` /
`leased` / `lease-expired` / `completed` / `result-rejected` /
`cancelled`, each with its `attempt`, timestamp and JSON detail). Exits
`1` if the task has no journal.

## `provider suggest --config FILE --prompt-file FILE [--scenario ...]` (DS06)

Runs one step of the deterministic **fake** AI provider through the
safety contract (see `AI_PROVIDER.md`) and prints the inert
`ProviderResult` JSON. `--config` is an ai-provider document (`kind`
must be `"fake"` - a real provider is a user decision) with a
`timeout_seconds` and a `budget` (`max_calls` / `max_tokens` /
`max_cost_usd`). `--scenario` (default `ok`) picks which path to
exercise: `ok` / `timeout` / `malformed` / `quota` / `injection`. A
timeout, malformed output or quota exhaustion is a bounded named
`outcome`; the budget stops the step before it exceeds; the suggestion
is returned as data with `grants_no_permissions` / `triggers_no_deploy`
always true, and an instruction-like suggestion is `injection_flagged`,
never acted on. Exits `0` only on `outcome: "suggested"`.

## `incident verify <message_file> --policy FILE --registry FILE --authenticated-as NODE` (DS07)

Checks one incident message against a transport policy and a node
registry (`node id -> HMAC secret`, operator-held, never committed; see
`INCIDENT_TRANSPORT.md`). `--authenticated-as` is the identity the
channel proved. Prints the `VerifyResult` JSON; exits `1` (never a
traceback) with a named `code` for a rejection: `unknown-identity` /
`bad-signature` / `impersonation` / `replay` / `stale` / `overloaded` /
`incompatible-version`.

## `repair check-candidate <candidate_file> --secret-file FILE --incident ID --base FP --target NAME` (DS08)

The candidate gate of the controlled repair cycle. Verifies the
candidate's HMAC signature (secret read from `--secret-file`,
operator-held, never committed) and that it is pinned to THIS incident,
base fingerprint and target. Prints `{"accepted": bool, "reason":
str|null}`; exits `1` (never a traceback) on a block - a tampered
candidate, or one aimed at another incident / base / target.

## `ops health --db PATH [--min-free-gb F --free-disk-gb G --journal-cap N]` (DS09)

Operational health over the durable queue and disk. Prints a
`HealthReport`; exit `1` (never a traceback) with a named finding for
`orphaned-leases`, `journal-over-cap`, or `low-disk`. Safe on a timer.

## `ops verify-backup <manifest_file> --backup-root DIR` (DS09)

Re-hashes every file in a state backup against its manifest. Prints
`{ ok, verified, mismatches, missing }`; exit `1` on any mismatch or
missing file. `restore_backup()` (tested, no CLI yet) additionally
refuses a backup for a different instance id or schema version.

## `deliver manifest [--repo-root DIR]` (DS10)

Prints the delivery manifest for this repository as JSON: a sha256 for
every shipped file (`src/*.py`, `docs/*.md`, `configs/*.json`, plus
`pyproject.toml` / `hydra-umc.project.json` / `CHANGELOG.md` /
`README.md`), the real CLI subcommand list read from `cli.py`, the
package version, and the `tests/test_*.py` count. `--repo-root` defaults
to this checkout. **Read-only.**

## `deliver evaluate [--repo-root DIR]` (DS10)

Prints the honest maturity evaluation as JSON (see `DELIVERY.md`): each
of the ten deliveries as `shipped` / `partial` / `not-started` against
whether its module is actually in the tree (DS06 is `partial` on purpose
- only the deterministic fake ships), seven plain-language
`known_limitations`, and `overall_maturity`, which is hard-coded
`"scaffolding"`. Exits `1` if the maturity it reads back is ever not
`"scaffolding"` - the guard is that the evaluation cannot over-claim.

```
$ hydra-umc-dev-server deliver evaluate
{
  "project": "HYDRA-UMC-DEV-SERVER",
  "version": "0.1.0",
  "overall_maturity": "scaffolding",
  "deliveries": [ ... ten entries ... ],
  "known_limitations": [ ... seven statements ... ],
  "honest_summary": "All ten deliveries are in the repository ..."
}
```

## `--version`

Prints the installed package version (mirrors `pyproject.toml`'s own
`version`, kept in sync by `bump_version.py`) and exits `0`.

## Not yet implemented

The ten-delivery plan is complete, but it is scaffolding by design -
`deliver evaluate` reports exactly this. There is still no worker loop
that feeds a queued task's context to `provider suggest` and then runs
the result through `task run` and the DS08 repair cycle; each piece is
exercised in isolation. No real AI provider is wired - which one, and
its authorization, is a user decision. `station plan` describes a
provisioning it never carries out; `migrate plan` describes a migration
it never carries out; there is no command that creates a user, writes a
unit file, opens a port, or copies a single file. `task run` is the only
command that executes anything, and only an allow-listed command in an
isolated workspace with no inherited secrets - it deploys nothing. No
target hardware has been provisioned or validated.
