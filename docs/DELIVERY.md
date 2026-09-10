<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/DELIVERY.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Delivery package and honest maturity evaluation (DS10)

DS10 closes the ten-delivery plan the way DS01 opened it: by describing
what is here, not claiming what is not. It adds one module,
`delivery.py`, with two read-only functions and no side effects.

## `build_delivery_manifest(repo_root) -> DeliveryManifest`

Enumerates what this repository actually ships and records a sha256 for
each file:

- every `src/hydra_umc_dev_server/*.py` module
- every `docs/*.md`
- every `configs/*.json`
- `pyproject.toml`, `hydra-umc.project.json`, `CHANGELOG.md`, `README.md`

It also reads back, from the tree itself:

- `version` - the real package version (`hydra_umc_dev_server.__version__`)
- `cli_subcommands` - parsed from the `add_parser("...")` calls in
  `cli.py`, so the manifest lists the CLI surface that actually exists
- `test_files` - the count of `tests/test_*.py`

`deliver manifest` prints it as JSON. Nothing is hashed that is not in
the tree; nothing outside the repo is read.

## `evaluate_maturity(repo_root) -> MaturityEvaluation`

Reports each of the ten deliveries against real evidence - is the module
that carries it actually present in `src/hydra_umc_dev_server/`:

| Field | Meaning |
| --- | --- |
| `deliveries[]` | one entry per DS: `delivery_id`, `scope`, `module`, `status`, `module_present` |
| `status` | `shipped` / `partial` / `not-started` (forced to `not-started` if the module is missing) |
| `known_limitations` | seven plain-language statements of what is **not** here |
| `overall_maturity` | hard-coded `"scaffolding"` |
| `honest_summary` | one paragraph, repeats the limitation |

DS06 is reported **`partial`** on purpose: only the deterministic fake
provider ships, because a real provider and its authorization are a user
decision.

### The honesty guard

`overall_maturity` is a literal `"scaffolding"` in the source. There is
no branch, threshold or count that can return `"established"` or
anything higher. `deliver evaluate` exits non-zero if the value it reads
back is ever not `"scaffolding"`, and `test_delivery.py` asserts the
same. The evaluation is built so that it *cannot* over-claim.

## Known limitations (verbatim from `_KNOWN_LIMITATIONS`)

1. No real AI provider is wired - only the deterministic fake. The real
   provider, its authorization, cost and terms are a user decision (DS06).
2. The incident transport is a protocol object with an injectable
   channel; no real network transport (TLS/mTLS/a bus) is implemented
   (DS07).
3. `task run` isolates by a workspace directory and a scrubbed
   environment, not a container / namespace / cgroup sandbox (DS04).
4. There is no worker loop wiring the queue -> provider -> runner ->
   repair cycle together; each piece is exercised in isolation.
5. Provisioning, migration and repair install are all described or
   dry-run; nothing here creates a user, opens a port, copies a file to
   a real destination, or deploys anything.
6. No target hardware (Raspberry Pi 5 / CM5) has been provisioned or
   validated - platform choice and hardware verification are still open.
7. Every "real host" contact in the codebase is behind an injectable
   seam and is never touched in a test.

## What DS10 does not do

- it does not change any other module's behaviour - it only reads and
  reports
- it does not raise the maturity - the plan being complete does not make
  the skeleton a running system
