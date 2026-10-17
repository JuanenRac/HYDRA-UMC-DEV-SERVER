<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - Maturity exit criteria
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Exit Criteria: Scaffolding to Functional (met in 0.1.5)

This project was labelled `scaffolding`. The label moved to `functional` only
when every item below is true and verifiable in the repository (a test, a
CI check or a reproducible command) - not when the code merely exists.

- [x] The development API is documented: endpoints, request/response shapes and errors.
- [x] Local authentication is defined and tested (what an unauthenticated request can and cannot do).
- [x] The plugin lifecycle (load, start, stop, failure) is defined and covered by tests.
- [x] The manifest example in each README shows the real current version (checked in CI).

The move to `functional` happened in 0.1.5. Verified on real hardware or
services is a separate, later step and has not happened: a passing
software check does not certify physical behaviour.
