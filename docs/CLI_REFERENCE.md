<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/CLI_REFERENCE.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# CLI reference (DS01)

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
    {"name": "HYDRA-UMC-DEV-SERVER", "version": "0.0.1", "maturity": "scaffolding", "manifest_path": "../HYDRA-UMC-DEV-SERVER/hydra-umc.project.json"},
    ...
  ],
  "issues": []
}
```

Writes to `--out FILE` instead of stdout when given.

## `--version`

Prints the installed package version (mirrors `pyproject.toml`'s own
`version`, kept in sync by `bump_version.py`) and exits `0`.

## Not yet implemented

No `workspace`, `task`, `queue` or `provider` subcommand exists yet - DS04
(workspace/runner), DS05 (durable queue) and DS06 (AI provider) are later
deliveries. Running this CLI today cannot start, cancel, or observe any
task, and cannot deploy anything under any circumstance.
