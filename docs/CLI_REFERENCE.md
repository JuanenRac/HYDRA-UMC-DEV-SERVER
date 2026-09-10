<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/CLI_REFERENCE.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# CLI reference (DS01 + DS02)

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
    {"name": "HYDRA-UMC-DEV-SERVER", "version": "0.0.2", "maturity": "scaffolding", "manifest_path": "../HYDRA-UMC-DEV-SERVER/hydra-umc.project.json"},
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

## `--version`

Prints the installed package version (mirrors `pyproject.toml`'s own
`version`, kept in sync by `bump_version.py`) and exits `0`.

## Not yet implemented

No `workspace`, `task`, `queue` or `provider` subcommand exists yet - DS04
(workspace/runner), DS05 (durable queue) and DS06 (AI provider) are later
deliveries. Running this CLI today cannot start, cancel, or observe any
task, and cannot deploy anything under any circumstance. `station plan`
describes a provisioning it never carries out; there is no command that
actually creates a user, writes a unit file, or opens a port.
