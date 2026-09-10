# Changelog: HYDRA-UMC-DEV-SERVER 🖥️

All notable changes to this project will be documented in this file. The
version number follows this ecosystem's "odometer" scheme: PATCH +1 on
every real build, rolling into MINOR past 9 (`0.0.9` -> `0.1.0`); MAJOR is
bumped manually only. See `bump_version.py`.

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
