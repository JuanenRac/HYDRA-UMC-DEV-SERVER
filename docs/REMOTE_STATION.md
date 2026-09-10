<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/REMOTE_STATION.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Remote station (DS02)

DS02 makes "a reproducible remote station" a document you can diff and
review, plus two tools that read it. Nothing here changes a host: the
preflight only reads, and the provisioning plan is rendered, never run.
Real provisioning and real task execution are DS03+ and DS04.

## The profile document

One JSON object, loaded by `station validate` / `station preflight` /
`station plan`. A shipped example lives at
`configs/remote-station.example.json`.

| Field | Meaning |
| --- | --- |
| `identity.user` | The dedicated system account the station runs as. Never `root`; never a normal login user (`admin`, the CM5 login user `hydra-umc`). |
| `identity.home` | Absolute path to that account's home. |
| `identity.workspace_subdir` | Relative path under `home` for the work tree (no `..`). `workspace_path()` = `home` + this. |
| `remote_access.kind` | `code-server` (a user service, gets a systemd unit) or `ssh-remote` (reuses the host's existing sshd, no unit). |
| `remote_access.port` | Unprivileged TCP port (1024-65535) the editor endpoint listens on. |
| `remote_access.bind_address` | IP the endpoint binds. Loopback or RFC-1918 private by default. |
| `remote_access.allow_public_bind` | Must be the literal boolean `true` to allow a routable/public `bind_address`. A missing, misspelled or non-boolean value never grants it. |
| `required_tools[]` | `{ "name", "min_version", "required" }` entries - same shape as DS01's `toolchain` schema. |
| `min_free_disk_gb` | Minimum free space (default `10.0`) the preflight enforces at the workspace path. |

Validation accumulates every error into one `ConfigValidationError`
message (`identity: ...; remote_access: ...; required_tools[1]: ...`),
the same behaviour as DS01's `config.py`.

## `station preflight` - the read-only checks

`run_preflight(profile, inspector)` returns a `PreflightReport`
(`{ ok, checks: [{ name, ok, detail }], failures: [name] }`). Checks:

- `python-version` - host Python >= 3.11.
- `free-disk` - `min_free_disk_gb` available at the workspace path; a
  missing parent directory is a real reported failure, not a crash.
- `workspace-writable` - the nearest existing ancestor of the workspace
  path is writable.
- `tool:<name>` - one per `required_tools` entry; an absent **optional**
  tool is not a failure.
- `remote-port-free` - `bind_address:port` is bindable.
- `bind-address-is-private` - loopback/private, or `allow_public_bind`
  is set.
- `identity-user` - the account exists and is a real system account
  (uid < 1000, `nologin`/`false` shell, never uid 0). A missing account
  is reported as "not created yet", not silently passed.

Every host query goes through the `HostInspector` protocol.
`SystemHostInspector` is the only implementation that touches the real
host; the test suite uses a fake, so nothing contacts a real machine in
a test.

## `station plan` - the dry-run plan

`build_provision_plan(profile, preflight=None)` returns a `ProvisionPlan`:

- `steps[]` - ordered `{ kind, description, command_preview }`. Steps:
  `create-system-user` (a `useradd --system` argv), `create-workspace`
  (`install -d -o <user> -m 0750`), one `ensure-tool` per required tool
  (`apt-get install --yes <name>`), and either `write-systemd-unit`
  (for `code-server`) or `reuse-sshd` (for `ssh-remote`).
- `command_preview` is the argv a real installer **would** run, carried
  as data. This module never spawns it.
- `systemd_unit_text` - the full unit for a `code-server` station:
  `User=<identity.user>`, `ExecStart=/usr/bin/code-server --bind-addr
  <bind>:<port> --auth password`, `WorkingDirectory` and `ReadWritePaths`
  at the workspace path, and hardening lines. `RestrictAddressFamilies`
  deliberately keeps `AF_NETLINK` - a too-tight family list has caused a
  real crash-loop elsewhere in this ecosystem, and a real deploy still
  confirms with a live check, not `systemd-analyze verify` alone.

If a **failed** `PreflightReport` is passed, `build_provision_plan`
raises `ConfigValidationError` naming the failed checks instead of
returning a plan - "the host isn't ready" can never be one step of a
plan that then half-runs.
