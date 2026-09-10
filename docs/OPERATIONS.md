<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/OPERATIONS.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Stable operation and restore (DS09)

## Verified backup / restore of this host's own durable state

`create_backup(source_root, relpaths, backup_root, fs, backup_id=,
instance_id=, schema_version=)` copies the named files (for example the
DS05 `queue.sqlite3` and the config directory) into `backup_root` and
returns a `BackupManifest` - `backup_id`, `instance_id`,
`schema_version` (`dev-server-state/1`), and a `relpath -> sha256` map.

`verify_backup(manifest, backup_root, fs)` re-hashes every file and
returns `{ ok, verified, mismatches, missing }`. `ops verify-backup`
runs it; exit `1` on any mismatch or missing file.

`restore_backup(manifest, backup_root, restore_root, fs,
expected_instance_id=, expected_schema_version=)` **refuses** and
restores nothing when:

- `manifest.instance_id` != `expected_instance_id` - a backup from
  another DEV-SERVER is not restored over this one
- `manifest.schema_version` != `expected_schema_version`
- the backup is not intact (`verify_backup` finds a mismatch or a
  missing file)

Otherwise it writes the exact bytes back.

The backup file list is operator-chosen; secrets stay out of it.

## Operational health

`check_operational_health(queue, free_disk_gb=, min_free_disk_gb=,
journal_row_cap=, now=)` returns a `HealthReport { ok, findings, stats }`.
It is not ok, with a named finding, when:

| Finding | Meaning |
| --- | --- |
| `orphaned-leases` | entries still `leased` whose lease has expired - run `queue reconcile` |
| `journal-over-cap` | more journal rows than the cap - run `prune_journal` |
| `low-disk` | observed free disk below `min_free_disk_gb` |

`ops health --db PATH [--min-free-gb F --free-disk-gb G --journal-cap N]`
prints the report; exit `1` if not ok. It is safe to run on a timer.

## What DS09 still does not do

- it does not schedule the backup or the health check - a systemd timer
  or cron does that
- the delivery package and the honest maturity evaluation are DS10
