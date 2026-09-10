<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/MIGRATION_FROM_PC.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Conservative migration from the PC (DS03)

Moving the development environment off a personal PC and onto DEV-SERVER
must never risk the PC. DS03 is deliberately split into an inventory step
and a plan step, both **read-only**: nothing in this repository copies a
file, deletes a file, or runs a mutating `git` command. The plan is a
document; carrying it out is a separate, deliberate act (a later
delivery, or a person following the plan by hand).

## What gets classified

`migrate inventory <source>` walks a checkout - exactly the files git
considers part of the project, so a local `.venv`, `node_modules`,
`build/` or `__pycache__` is git-ignored and never inventoried - hashes
every file with SHA-256, and puts each into one class:

| Class | Meaning | Where it goes |
| --- | --- | --- |
| `tracked-clean` | committed and matches origin | **reference root** - a clean mirror, safe to re-clone or share |
| `tracked-modified` | committed file with uncommitted local edits | **local-changes root** - kept apart from the clean mirror |
| `untracked` | a working file git does not track (and is not ignored) | **local-changes root** |
| `private` | a private document or secret (`PrivacyPolicy`) | **private root** - never a Git-backed or shareable location |

Commits that exist on the local branch but were never pushed are recorded
separately and planned as a `git bundle` under the **work-in-progress
root** - they are real work, not lost, and not silently folded into the
clean mirror.

## The privacy policy

`private` is defined explicitly, not by feel. The defaults cover this
ecosystem's own cases:

- any path under this ecosystem's private-planning / audit folder (a
  built-in `PrivacyPolicy.path_prefixes` default - it is not named in any
  public file, this one included)
- file names matching `.env`, `.env.*`, `*.pem`, `*.key`, `id_ed25519*`,
  `id_rsa*`, `*.secret`, `refresh_tokens.json`, `*.p12`, `*.keystore`

A `privacy_policy` block in the destinations document can **widen** this
(extra prefixes, extra globs, exact extra paths). It cannot silently
narrow it below the shipped defaults.

## The four destinations

`migrate plan <source> --destinations <file>` needs a JSON document with
four absolute roots. `MigrationDestinations.from_dict` refuses any pair
that is equal or nested one inside the other - the whole point of DS03 is
that the classes land **separately**. See
`configs/migration-destinations.example.json`.

```
migrate plan /pc/checkouts --destinations destinations.json
```

The plan prints, per repo: every `PlannedCopy` (`source_relpath`,
`sha256`, `size`, `classification`, `destination`, `reason`), the
`commit_bundle` path if there are unpushed commits, a full `manifest`
(relpath -> sha256), and any `warnings`. If a private file would ever
resolve under the reference or work-in-progress root, `migrate plan`
prints `REFUSED: ...` and exits non-zero instead of emitting a plan.

## What DS03 will never do

- delete, move, rename or rewrite anything in the source
- copy a credential or a private-planning document into a Git-backed
  destination
- "clean up" or decommission the PC as a side effect
- treat a manual file copy as a completed migration

Executing an approved plan, verifying each destination file's hash
against the manifest, and the rollback path all belong to a later
delivery.
