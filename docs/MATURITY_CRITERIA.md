<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - Maturity exit criteria
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Exit Criteria: Scaffolding to Functional

This project is labelled `scaffolding`. The label moves to `functional` only
when every item below is true and verifiable in the repository (a test, a
CI check or a reproducible command) - not when the code merely exists.

- [ ] The development API is documented: endpoints, request/response shapes and errors.
- [ ] Local authentication is defined and tested (what an unauthenticated request can and cannot do).
- [ ] The plugin lifecycle (load, start, stop, failure) is defined and covered by tests.
- [ ] The manifest example in each README shows the real current version (checked in CI).

Verified on real hardware or services is a separate, later step: a passing
software check does not certify physical behaviour.
