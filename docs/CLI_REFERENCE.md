<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/CLI_REFERENCE.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0-or-later - see LICENSE
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
  "allowed_commands": ["pytest", "build.sh", "build-test.sh"],
  "allowed_arguments": {},
  "sandbox": "auto",
  "sandbox_required": false,
  "sandbox_network": false,
  "sandbox_read_only_paths": [],
  "workspace_retention": "delete-on-success",
  "repo_sources": {}
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
    {"name": "HYDRA-UMC-DEV-SERVER", "version": "0.1.5", "maturity": "functional", "manifest_path": "../HYDRA-UMC-DEV-SERVER/hydra-umc.project.json"},
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
dedicated system account. What the plan itself creates (the account and
its workspace, when they are not there yet) is not a failure: the check is
`ok` with `will_create: true` and the report lists them under
`will_create`. For `ssh-remote` the account must be able to log in (a
real shell and an `authorized_keys` file) instead of having no login
shell. Prints the full `PreflightReport` as JSON,
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

## `task run <recipe_file> --policy <file> --workspace-base <dir> [--replace-workspace]` (DS04)

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
Exits `0` only on `completed` with exit code `0`. A disallowed command,
a disallowed argument (see `allowed_arguments`) or an escaping input path
is `rejected` with **nothing spawned**. It deploys nothing.

Around the run: a task is refused when `max_concurrent_tasks` are already
running under the same workspace base; when the policy has a `repo_sources`
entry for the recipe's `repo`, the pinned revision is fetched into the
workspace with git first (`staged_commit` in the output, and a commit that is
not the pinned one is refused); the command runs inside the sandbox the host
has (`sandbox` in the output: `bubblewrap`, `systemd-run` or `none`, and a note
on stderr when it is `none`); a bare script name such as `build.sh` is
looked up in the workspace and `PATH` is fixed on a POSIX host; and the
workspace is removed afterwards according to `workspace_retention`
(`workspace_removed` in the output). `--replace-workspace` removes a leftover
workspace of the same task id first; it is never removed otherwise.

## `queue enqueue <recipe_file> --db PATH --base-fingerprint HEX` (DS05)

Adds one task recipe to a SQLite durable queue (created if absent). A
second call with the same `task_id` is a no-op - `created: false`, no
journal row, never a second job. `--base-fingerprint` is any opaque
string the caller derives from the source state the task is pinned to;
DS05 stores it and later compares it.

## `queue work --db PATH --policy FILE --workspace-base DIR [--worker-id ID] [--max-tasks N] [--lease-seconds S] [--follow]`

The worker loop. It returns the tasks of a dead worker to the queue, then
takes the oldest queued task and carries it through: lease, workspace,
`repo@revision` staged with git, the command run in the sandbox of the
policy while the lease is renewed every third of its length, the result
recorded, the workspace removed according to `workspace_retention`. A task
that cannot start (the policy no longer allows the command, staging fails,
the sandbox is required and missing) is recorded as failed, never left
leased; a lease that is lost cancels the run. The slot of
`max_concurrent_tasks` is taken before anything is leased, so a worker
without a free slot leaves the queue alone. It stops when the queue is empty
(`--follow` keeps waiting). Prints `{"tasks": [...]}`; exit `1` if any task
did not succeed. Never run against a real host yet.

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
`outcome`; a budget already reached stops the step before the call, and a call that goes past what was left is not used; the suggestion
is returned as data with `grants_no_permissions` / `triggers_no_deploy`
always true, and an instruction-like suggestion is `injection_flagged`,
never acted on. Exits `0` only on `outcome: "suggested"`.

## `incident verify <message_file> --policy FILE --registry FILE --authenticated-as NODE [--state-file FILE]` (DS07)

Checks one incident message against a transport policy and a node
registry (`node id -> HMAC secret`, operator-held, never committed; see
`INCIDENT_TRANSPORT.md`). `--authenticated-as` is the identity the
channel proved. Prints the `VerifyResult` JSON; exits `1` (never a
traceback) with a named `code` for a rejection: `unknown-identity` /
`bad-signature` / `impersonation` / `replay` / `stale` / `overloaded` /
`incompatible-version`. The command is started once per message, so on its
own it remembers nothing and a replayed message passes (it says so on
stderr); `--state-file` keeps the nonces and the rate log in a SQLite file
shared by every run, and the check and the update of one message are one
transaction, so two runs cannot both accept it.

## `repair check-candidate <candidate_file> --secret-file FILE --incident ID --base FP --target NAME` (DS08)

The candidate gate of the controlled repair cycle. Verifies the
candidate's signature (read from `--secret-file`, operator-held, never
committed: an HMAC secret, or the public key `ed25519-public:...` for a
candidate signed with a key pair; the two kinds never mix) and that it is pinned to THIS incident,
base fingerprint and target. Prints `{"accepted": bool, "reason":
str|null}`; exits `1` (never a traceback) on a block - a tampered
candidate, or one aimed at another incident / base / target.

## `ops health --db PATH [--min-free-gb F --free-disk-gb G --journal-cap N]` (DS09)

Operational health over the durable queue and disk. Prints a
`HealthReport`; exit `1` (never a traceback) with a named finding for
`orphaned-leases`, `journal-over-cap`, or `low-disk`. Safe on a timer.

## `ops verify-backup <manifest_file> --backup-root DIR [--public-key-file FILE --signature-file FILE]` (DS09)

Re-hashes every file in a state backup against its manifest. Prints
`{ ok, verified, mismatches, missing, signature_valid }`; exit `1` on any
mismatch or missing file. With `--public-key-file` the manifest must also
carry a valid signature (`--signature-file`) of that key, or the backup is
not ok: a manifest regenerated over replaced files is caught. A key without
a signature is not ok either. `restore_backup()` (tested, no CLI yet)
additionally refuses a backup for a different instance id or schema version,
and, given a public key, a manifest that is not signed by it.

## `ops keygen --private-key-file FILE --public-key-file FILE`

Makes an Ed25519 key pair for signing backups and repair candidates. It
refuses to overwrite a file; the private key (`ed25519-seed:...`) is written
readable by its owner only. Sign on the machine of the operator, not on a
shared host (the implementation is not constant-time).

## `ops sign-backup <manifest_file> --private-key-file FILE [--output FILE]`

Prints the signature (`ed25519:...`) of a backup manifest, and writes it to
`--output` (a new file) when given.

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
`"functional"`. Exits `1` if the maturity it reads back is ever not
`"functional"` - the guard is that the evaluation cannot over-claim.

```
$ hydra-umc-dev-server deliver evaluate
{
  "project": "HYDRA-UMC-DEV-SERVER",
  "version": "0.1.0",
  "overall_maturity": "functional",
  "deliveries": [ ... ten entries ... ],
  "known_limitations": [ ... seven statements ... ],
  "honest_summary": "All ten deliveries are in the repository ..."
}
```

## `plugin list --plugins-root DIR`

Discovers plugins (each immediate subdirectory holding a `plugin.json`) and
prints their state as JSON. Nothing is imported. Exits `1` if any plugin
directory is broken; the good ones are still listed.

A plugin is `plugin.json` (`name`, `version`, `api_version` = 1, `entry` and
an optional `provides`) plus one Python module defining `register(registry)`.
`provides` lists the kinds it offers: `checks` (the default), `reports` and
`generators`; `register` may call `registry.add_check`, `registry.add_report`
and `registry.add_generator` for the kinds it declared and for no other. It
stays `discovered` until enabled
against the SHA-256 of its manifest and module together (shown by this
command); a plugin whose files changed since that digest was approved is
refused. States: `discovered`, `enabled`, `disabled`, `failed`. An item
returns a JSON dict (a generator returns `{"filename", "content"}`), is cut off
after 10 s, may not answer with more than 256 KiB, and an error is reported as
an error, never as a result. The manifest, the lifecycle and the limits are
described in [PLUGINS.md](PLUGINS.md).

## `plugin run --plugins-root DIR --plugin NAME --sha256 HEX --kind check|report|generator --item NAME [--params JSON]`

Enables one plugin for this process only, against the digest you name, runs
one of its items and prints the answer as JSON. `--params` is the generator's
parameters (a JSON object of at most 4096 bytes). Exits `0` when the answer is
`ok`, `1` when the digest does not match, the plugin or item does not exist,
the parameters are not valid or the item reports an error. A generator's text
is only printed; nothing is written to disk.

## `serve --workspace-root DIR --plugins-root DIR [--host 127.0.0.1] [--port 8790] [--token-file FILE]`

Runs the local HTTP API. It binds only to a loopback address, and the bearer
token (at least 24 characters) comes from `--token-file` or the
`HYDRA_UMC_DEV_SERVER_TOKEN` environment variable, never from the command
line. Every route except `GET /v1/health` needs `Authorization: Bearer
<token>`; bodies are capped at 4096 bytes, a connection that goes quiet for 15 seconds is closed,
and at most 32 requests are served at once (the next gets `503` with `Retry-After: 1`). The status codes are fixed: `401` (with `WWW-Authenticate: Bearer`) for a missing or wrong token, `404` for a route or plugin that does not exist, `405` (with `Allow`) for a known route called with the wrong method and for any method other than `GET` and `POST`, `409` for a plugin that is not in a state that allows the call, `413` for a body over the limit, `500` (no trace in the body) for a failure inside the server and `503` when busy.
`docs/openapi.json` describes the routes; a test keeps it equal to the handler.

| Route | Purpose |
|---|---|
| `GET /v1/health` | version and plugin count (no token) |
| `GET /v1/inventory` | manifests found under the workspace |
| `GET /v1/audit` | the last 500 requests (time, method, path without query, status, client); never a body or a token |
| `GET /v1/plugins` | every plugin, its state, digest, kinds and the checks, reports and generators it registered |
| `POST /v1/plugins/rescan` | discover again from disk |
| `POST /v1/plugins/<name>/enable` | body `{"sha256": "..."}`; `409` if refused |
| `POST /v1/plugins/<name>/disable` | disable |
| `POST /v1/plugins/<name>/checks/<check>` | run one check |
| `POST /v1/plugins/<name>/reports/<report>` | run one report |
| `POST /v1/plugins/<name>/generators/<generator>` | run one generator; optional body `{"params": {...}}`; the answer carries the file name and text |

The API runs no task and deploys nothing.

## `--version`

Prints the installed package version (mirrors `pyproject.toml`'s own
`version`, kept in sync by `bump_version.py`) and exits `0`.

## Not yet implemented

The ten-delivery plan is complete, but it is only `functional` (not verified on real hardware) -
`deliver evaluate` reports exactly this. `queue work` joins the queue, the staging, the sandboxed run and the recording of
the result, but only against fakes; there is still nothing that feeds a queued
task's context to `provider suggest` and then runs the result through the DS08
repair cycle, and each of those pieces is exercised in isolation. No real AI provider is wired - which one, and
its authorization, is a user decision. `station plan` describes a
provisioning it never carries out; `migrate plan` describes a migration
it never carries out; there is no command that creates a user, writes a
unit file, opens a port, or copies a single file. `task run` is the only
command that executes anything, and only an allow-listed command in an
isolated workspace with no inherited secrets - it deploys nothing. No
target hardware has been provisioned or validated.
