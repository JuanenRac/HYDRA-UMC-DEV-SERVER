<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/REPAIR_CYCLE.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# One fully controlled repair cycle (DS08)

`RepairCycle` is a step-by-step state machine. Any gate failure sets
`state = "blocked"` (with a `reason`) and every later step is a no-op.
Nothing here touches a real service - the installer and the run results
are injected.

```
repro-confirmed -> incident-raised -> candidate-received
  -> regression-passed -> build-test-passed -> approved
  -> installed -> verified            (or -> recovered / -> blocked)
```

## The gates

| Step | Blocks when |
| --- | --- |
| `confirm_repro(evidence)` | `evidence.reproduced` is false, or `repro_case_id` is not this cycle's |
| `receive_candidate(candidate, secret)` | the HMAC signature does not verify (tampered / unsigned); the candidate is for a different incident, **base fingerprint**, or **target** |
| `run_regression(run_result)` / `run_build_test(run_result)` | the `RunResult` is not `completed` with exit code `0` |
| `apply_approval(approval, approver_secret)` | the approver is not registered; the signature does not verify; the approval was issued for a different candidate, **base**, or **target** |
| `install_isolated(installer)` | `installer.install()` returned false |
| `verify(evidence, installer, observed_base_fingerprint=)` | the base fingerprint moved mid-cycle (→ rollback, `blocked`); the evidence is for a different repro case (→ rollback, `blocked`); `evidence.verified` is false (→ rollback, `recovered`) |

A correct candidate that reproduces green, is approved for this exact
base and target, installs, and passes a same-case post-install
verification ends `verified`.

## The candidate gate on its own

`check_candidate(candidate, secret, incident_id=, base_fingerprint=,
target=)` applies exactly the `receive_candidate` checks without a live
cycle - it is what `repair check-candidate` runs. Prints
`{"accepted": bool, "reason": str|null}`; exits `1` on a block.

The candidate signer's secret and the approver's secret are
operator-held and **never committed**.

## What DS08 still does not do

- it does not run the real service, the real regression suite, or a
  real install - those are injected (`RunResult`, `IsolatedInstaller`)
- stable long-run operation and full restore are DS09
- the delivery package and maturity evaluation are DS10
