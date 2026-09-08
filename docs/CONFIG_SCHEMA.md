<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/CONFIG_SCHEMA.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Configuration schema (DS01)

Three independent JSON documents, each validated by its own dataclass in
`src/hydra_umc_dev_server/config.py`. None of them is consumed by a
running workspace or task yet - DS04/DS05 own that. `config validate` (see
`CLI_REFERENCE.md`) is the only thing that reads them today.

## `HostProfile` - who this host is, where it keeps state

| JSON field | Type | Notes |
| --- | --- | --- |
| `hostname` | string | Required, non-empty. |
| `arch` | string | Required, non-empty (e.g. `aarch64`). Not yet checked against the running host. |
| `storage_root` | string | Required, must be an absolute path (starts with `/`). Real per-machine state - see `docs/ARCHITECTURE.md`'s disk layout. |
| `created_from` | string | Required, one of `fresh-image` or `migrated-from-pc`. |

Example: `configs/host-profile.example.json`.

## `ToolchainPolicy` - one expected language toolchain

| JSON field | Type | Notes |
| --- | --- | --- |
| `name` | string | Required, non-empty (e.g. `python`, `node`, `rust`, `go`). |
| `min_version` | string | Required, non-empty. Not yet parsed as a real version range. |
| `required` | boolean | Optional, defaults to `true`. |

Example: `configs/toolchains.example.json`. A host profile references one
or more toolchain documents - this delivery validates one at a time; a
directory-wide "all toolchains for this host" aggregate is DS02/DS04
work, not yet implemented here.

## `TaskPolicy` - the hard default-deny boundary

| JSON field | Type | Notes |
| --- | --- | --- |
| `allow_deploy` | boolean | Optional, **defaults to `false`**. Only a document that sets the literal JSON boolean `true` can ever produce a policy with it enabled - a missing, misspelled, or non-boolean value never grants it (see `tests/test_config.py`'s own `TaskPolicyTests` for the exact cases this is verified against). |
| `max_concurrent_tasks` | integer | Optional, defaults to `1`. Must be a real positive integer - a boolean (which Python treats as an `int` subclass) is explicitly rejected. |
| `allowed_commands` | array of strings | Optional, defaults to `[]`. Every entry must be a non-empty string. |

Example: `configs/task-policy.example.json` - the shipped example itself
sets `allow_deploy: false` explicitly and is asserted, by test, to still
resolve to a denying policy even if that line were removed.

This is DS01's own literal acceptance criterion: *"ninguna tarea tiene
permiso de despliegue por defecto"* (no task has deployment permission by
default). It is enforced by the dataclass's own default, not just stated
in prose, and that default is covered by a real automated test.

## Loading a document

`load_json_document(path)` (`config.py`) reads and parses one file,
raising `ConfigValidationError` - never a bare `json.JSONDecodeError` or
`OSError` - for a real, specific reason (file missing/unreadable, invalid
JSON, or a top-level value that is not a JSON object). Each dataclass's
own `from_dict()` then validates the fields above, collecting every
violation it finds before raising a single `ConfigValidationError` that
names all of them - not just the first.
