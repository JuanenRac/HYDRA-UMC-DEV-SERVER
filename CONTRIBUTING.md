# Contributing to HYDRA-UMC-DEV-SERVER 🦾

We welcome contributions to the reproducible development host of the
HYDRA-UMC platform.

## Technology Stack

- **Language**: Python 3.11+.
- **Dependencies**: stdlib only, deliberately, for this delivery - this
  host coordinates other real projects rather than reimplementing them,
  and a dependency is added only once a specific later delivery's own
  code genuinely needs it (e.g. a durable-queue driver for DS05, an AI
  provider SDK for DS06), never speculatively.

## Guidelines

1. **`TaskPolicy.allow_deploy` defaults to `False`, always.** DS01's own
   acceptance criterion is literal: "ninguna tarea tiene permiso de
   despliegue por defecto". Do not add a code path, default argument, or
   example configuration file that grants it implicitly - only a real
   document that sets the literal JSON boolean `true` may ever produce a
   `TaskPolicy` with it enabled, and that must stay covered by a test the
   same way `test_config.py`'s own `allow_deploy` tests already are.
2. **A collector reports a real, honest failure - it never guesses.**
   `scan_project_manifests()` returning a `ManifestScanIssue` instead of
   silently dropping a broken manifest is the established pattern (same
   one HYDRA-UMC-OPS-AGENT's own inventory.py already uses) - follow the
   same shape for a new collector rather than inventing a second one.
3. **This delivery (DS01) only ever defines contracts and validates
   configuration - it does not yet run anything.** Do not add a workspace,
   task execution, queue, or AI-provider call without first checking which
   later delivery (DS02/DS04/DS05/DS06 - see this project's own private
   development plan, section 13.13, for the full list) actually owns that
   piece, and updating this repository's own README Roadmap section to
   match.
4. **State ownership is not this repository's to redecide.**
   `docs/ARCHITECTURE.md`'s ownership table is copied, not reinterpreted,
   from that same private plan's own section 13.2.2 - an incident/approval/closure stays owned
   by HYDRA-UMC-OPS-AGENT even once this host exists; do not add code here
   that makes that decision instead.
