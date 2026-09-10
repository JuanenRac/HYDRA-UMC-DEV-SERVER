<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/ARCHITECTURE.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Architecture (DS01-DS08)

This document describes this project's purpose, working modes, initial
scope and disk layout, and the target design across all ten deliveries
(DS01-DS10). What actually runs today: DS01's configuration schema and
manifest discovery; DS02's remote-station profile, read-only host
preflight and dry-run provisioning plan (`station` - see
`REMOTE_STATION.md`); DS03's conservative-migration inventory and plan
(`migrate` - see `MIGRATION_FROM_PC.md`); DS04's bounded task recipe and isolated workspace runner (`task` - see
`WORKSPACE_AND_RUNNER.md`); DS05's durable SQLite queue and append-only execution journal (`queue`
- see `DURABLE_QUEUE.md`); and DS06's interchangeable AI provider behind
a safety contract (`provider` - see `AI_PROVIDER.md`), of which only the
deterministic fake ships; and DS07's authenticated incident transport
for the round trip with HYDRA-UMC-OPS-AGENT (`incident` - see
`INCIDENT_TRANSPORT.md`); and DS08's one fully controlled repair cycle
(`repair` - see `REPAIR_CYCLE.md`), gated at every step with rollback on
a failed post-install check.
DS01-DS03, DS05 and DS06 only read, describe and record. DS04 is the
only delivery that executes a subprocess - and only an allow-listed command, in a per-task
isolated workspace, with a scrubbed environment, under a bounded timeout
that kills the whole process group; it still deploys nothing.
Everything else on this page is a documented target, not a claim about
what runs today.

## Purpose and status

HYDRA-UMC-DEV-SERVER is development infrastructure: a remote-station
preparation and controlled execution environment for programming, testing
and build tasks - it is not a new AI to train, and not another operating
system. It exists so the user can move the HYDRA-UMC/URTC development
environment from a PC to a dedicated server (all source on a real NVMe),
keep programming/reviewing/instructing AI assistants from the PC, and
optionally serve the maintenance loop of the operational CM5 nodes too.

Target platforms: a Raspberry Pi 5 (8GB, Ethernet, 512GB NVMe) or a
Compute Module 5 (8GB, no eMMC/no Wi-Fi, with a compatible carrier board
and NVMe/Ethernet), on 64-bit Raspberry Pi OS. Before any hardware is
chosen or provisioned, NVMe boot, boot firmware, the carrier board,
adapters, power and cooling must all be confirmed - "CM5 without eMMC" is
never assumed to be a complete kit, and no adapter/board is assumed to
support the chosen combination without verification. 512GB is the
requested capacity, not a guarantee of unlimited space nor a substitute
for an external backup.

## Physical separation of responsibilities

- **The user's PC**: the remote work interface - instructions, diff
  review, approval. Kept as a backup during migration, and as a possible
  executor for work that cannot run properly on Linux ARM64.
- **DEV-SERVER**: code, tools, programming sessions, isolated tasks and
  test artifacts. It never shares its own build load with the CM5 that
  actually controls robots.
- **The operational CM5**: the ecosystem's real applications, devices and
  local diagnosis. It may add a Hailo-8 for vision and a Hailo-10H for AI
  once that integration is actually validated - the coordination this
  project proposes must also work without either accelerator. A local
  model is never assumed able to fix code or run any model on request -
  its capabilities must be measured and declared.

## Two ways of working, one core codebase

**Interactive mode.** The user opens the remote environment from VS Code
on their own PC and works on files stored on the server; the server side
provides tools and execution. No permanently-active graphical desktop is
needed on the Raspberry for this mode - a local desktop VS Code running
directly on the Raspberry would be a separate, optional profile. Remote
access, extension and native-binary compatibility must be checked against
the actual chosen architecture and versions - a plugin that works on
Windows is never assumed to work unchanged on ARM64.

**Controlled task mode.** The user or HYDRA-UMC-OPS-AGENT registers a
development task; an authorized executor prepares an isolated workspace,
uses an available AI provider/client, runs allowed tests, and delivers
results. Clicks on an editor UI are never automated as the basis for a
reliable service. People or assistants from different providers (Claude,
ChatGPT or others) may work this way, according to whichever integration
mechanism is actually available and authorized for each - an editor
extension, a CLI client and an API are treated as distinct options with
no assumed equivalence in capability, licensing or billing; ARM64
support, authentication, terms and cost are all verified before enabling
any one of them. Remote AI does not necessarily run inside the
Raspberry's own 8GB - when an external service is used, the server only
hosts tools and code. A local model on DEV-SERVER would be optional,
evaluated separately, and is not a condition for the first version, nor a
reason on its own to buy another accelerator.

## Initial scope

**In scope:**
- Idempotent provisioning of the development environment and prerequisite
  diagnosis.
- Inventory and verified migration of repositories, including HYDRA-UMC
  and URTC.
- Remote access gated by explicit identity and permissions.
- Per-language/platform toolchain profiles.
- Isolated sessions for people and agents.
- Reproducible tasks, tests, sanitized logs and identified results.
- Incremental integration with OPS-AGENT and UPDATER.
- Backup, restore, and disk/resource usage control.

**Explicitly not in the first delivery:**
- Writing directly into a CM5's live installation.
- Auto-authorizing a patch just because an AI claims it is correct.
- Compiling any platform on ARM64 without checking its toolchain first.
- Replacing GitHub, CI, SDK, OPS-AGENT or UPDATER.
- Deploying a change to every CM5 at once.
- Turning the development server into a motion controller.
- Giving the AI executor root access, deployment secrets, or machinery
  network access.

## Disk layout

Indicative paths under `/srv/hydra-umc-dev`; permissions and mount point
are validated before use - detecting this path is never a reason to erase
or reformat a disk.

| Path | Purpose |
| --- | --- |
| `repos/` | Reference copies with provenance/revision metadata. |
| `workspaces/` | Interactive work and per-task isolated copies - never one mutable copy shared by every agent. |
| `artifacts/` | Test packages, inventories, hashes and build results. |
| `state/` | Durable queue, IDs, leases and execution journal. |
| `logs/` | Bounded, sanitized logs. |
| `cache/` | Reusable downloads with limits and a cleanup policy. |
| `private/` | Migrated private documentation, kept separate from anything publishable. |
| `backups/` | Optional staging area - the real backup needs a separate location. |

Secrets stay outside repositories and artifacts, with per-service
restricted access. An agent is never automatically handed all of
`private/` to fix one specific file's failure - context is selected
minimally, and sending data to an external provider is a separate,
explicit authorization. The reference folder can be updated from GitHub
in a controlled way; a task is pinned to a specific revision and its base
is never swapped mid-run. Unpublished local changes are an explicit part
of migration (see `docs/MIGRATION_FROM_PC.md`).

## Ownership and cross-project relationships

See `docs/OPS_INTEGRATION.md` for the full ownership table and the
17-relationship map (necessary / optional / development-only) this
project does not reinterpret, only restates.
