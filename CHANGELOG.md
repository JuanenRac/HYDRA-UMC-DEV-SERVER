# Changelog

## [Unreleased]

- **A seventh container bench drives the server:** `bench/docker-compose.server.yml` builds HYDRA-UMC-SERVER from its own Dockerfile in its sibling checkout and publishes it on the loopback interface only, the way a production start does: a user that is not root, and the signing key and the password of the first administrator made for the run (the stack refuses to start without them; nothing secret is in the image or in the file). `python -m hydra_umc_dev_server.server_bench` runs 7 scenarios against it: the version route answers without a token and nothing else does (settings, users and the robot command are refused with 401), a wrong token and a wrong password open nothing, the first administrator signs in and reads the settings tree, and a command to a robot that does not exist is refused by the client side and not a failure of the server. The workflow `Server bench` runs it by hand, once a week, on a pull request that changes the bench, and as a reusable workflow (`workflow_call`) for the pull requests of the server. It is a bench of Actions: how the server is installed on the CM5 does not change. 12 tests run the scenarios against a stand-in server that keeps the rules, and fail when it does not.
- **The documentation corpus is built in CI, the same bytes every time, and left unsigned for the release step:** `python -m hydra_umc_dev_server.corpus_build` clones the public repositories of `configs/corpus-repos.json` anonymously, builds the HYDRA-UMC-DOCS-QA bundle twice (two directories, two hash seeds) and stops unless both files are identical; it writes `corpus-<release>.sources.json` with the commit of every repository (`--pin` fetches exactly those commits again) and `"signed": false`. The manual workflow `Corpus bundle` runs it, uploads the bundle with `SHA256SUMS` and a build manifest under a build-provenance attestation and checks the artifact as a stranger would; a pull request that touches it runs the same build without the attestation. It holds no key: the release signature is made on the maintainer's machine. `docs/CORPUS_BUNDLE.md` describes the chain; `tests/test_corpus_build.py` (17 tests) covers the configuration, pins, clones, a build that depends on the hash seed or the place, and the sources file.
- **More tests for the signed tokens, the scenario sender, the staging of a repository and the host inspector, a simulation bench and a coverage floor:** 61 new tests try every way a signed token of the server can be wrong (including a fixed-seed mutation run), play a stand-in server that logs in, refuses, redirects and hangs up against the real scenario sender, stage a repository with a real git made on the runner, exercise the concurrency gate and the end of a workspace, and drive the real read-only host inspector. A `Simulation bench` workflow runs those scenarios without a container, and a coverage job fails when the statement coverage falls under its floor.

## [0.2.6] - More container benches and a rotated trust store

All notable changes to this project are documented here.

- **README: the platform statement:** a note says that where the README speaks of the CM5 it means the pilot bench that runs today, and that the target platform of HYDRA-UMC, an NVIDIA Jetson Orin NX 16 GB, is a design that has not been built or tested.
- **A sixth bench runs two machine bridges behind the real broker, each in front of an emulator:** `bench/docker-compose.bridges.yml` starts the MQTT broker as a container with a bridge identity, an operator identity and a topic rule (the bridge publishes under `hydra/bridges/` and reads its commands; the operator gives commands and reads everything). `python -m hydra_umc_dev_server.bridge_rig cnc` runs the CNC bridge in front of the GRBL emulator of its tests and `bridge_rig printer3d` runs the 3D-printer bridge in front of `fake_moonraker.py`, a Moonraker stand-in with the print state of a real Klipper (a pause only from a print, a resume only from a pause, an emergency stop that shuts the printer down); both serve a control side that lists what the machine received. `python -m hydra_umc_dev_server.bridge_bench cnc|printer3d` speaks MQTT as the operator and checks the whole way: the retained availability, a status query with the time it was read, a job that is not JSON and a payload over the limit refused with their reason, a verb the bridge does not know ignored, and, for the CNC, a feed hold that reaches the controller as the real-time byte, a resume that is refused while the machine is idle and sent only from a hold, a machine in alarm that is never published as idle; for the printer, a pause and a cancel that reach it, a resume refused while nothing is paused, an emergency stop that reaches it, and a start for a file it does not hold that never reaches it. The manual workflow `bridge-bench.yml` runs both on a CI runner; the scenarios, the stand-in and the control side are tested here against a broker that keeps retained messages and a stand-in bridge (16 tests).

- **A fifth bench runs a simulated URTC tool head on a virtual CAN bus:** `python -m hydra_umc_dev_server.urtc_bench` speaks raw SocketCAN to the head of `HYDRA-UMC-DOCS` (`tools/fake_urtc.py`) and compares its answers byte for byte with the frames of the firmware: the query of the active tool (`0x110`) is answered with `0x111` for the tool the head was started as, with no error and no boot in progress; the query of the version (`0x7F8`) is answered with `0x7F9` (application side, hardware id, version) and `0x7E9` (patch); a frame of the flashing range is ignored; twenty more queries get the same answer; two queries sent back to back are both answered. The manual workflow `urtc-bench.yml` creates `vcan0` on a CI runner, starts the head and runs the six scenarios, which is the first run of the head on a real SocketCAN interface; the scenarios are tested here against a stand-in head on an in-memory bus (14 tests).

- **A fourth container bench drives the voice gateway:** `bench/docker-compose.voice.yml` builds the speech-to-action gateway from its own Dockerfile in its sibling checkout and starts it the way a production start does (bound beyond loopback, so it refuses to run without a bearer token), published on the loopback interface only. `python -m hydra_umc_dev_server.voice_bench` speaks HTTP to it with the standard library and runs eight scenarios: `/health` answers without a token and says one is required, a turn with no token or a wrong token is refused, a turn with the token is answered with its request id and counted, a turn with no transcript is refused and the refusal is counted, a body over the limit is refused, a forged confirmation token confirms nothing, and `/metrics` is refused without the token and is valid Prometheus text with it. The manual workflow `voice-bench.yml` starts the container on a CI runner and runs them; the scenarios are tested here against a stand-in gateway (10 tests).

- **The trust store of a CM5 lives in a root-only directory and its keys are replaced by a signed rotation:** `trust_rotation.py` fixes the place (`/etc/hydra-umc/trust`, owned by root, mode 0700, outside the data of any application: `trust check-dir` names what is wrong, and lists a link, another owner, an open mode, a store or log that others can write, or a place inside the data of an application) and the way a key is replaced: the statement names the old alias and key, the new alias and key, the sequence number and the hash of the previous record, and only the key being replaced can sign it (`trust rotation-body`, `trust sign-rotation` on the approver's machine, which prints only the signature, and `trust rotate`). Applying it adds the new alias and revokes the old one in one step and appends a hash-chained record to `rotation.log`; a replayed, reordered, cut or tampered statement, a new key or alias already in the store, a statement of a revoked alias and a damaged log are refused and leave the store and the log as they were. `trust log` checks the chain, the signatures and that the log agrees with the store. The rotation is off unless `HYDRA_UMC_TRUST_ROTATION=1` (or `--enable-rotation` for one call). Tested with generated keys and fake file modes; not run on a CM5, where the installer has still to create the directory as root.

- **A third container bench drives the MQTT broker:** `bench/docker-compose.broker.yml` builds the broker from its own Dockerfile in its sibling checkout and starts it the way a production start does (two identities with passwords of 16 characters or more, a topic ACL, the plain listener allowed on the internal network), published on the loopback interface only. `python -m hydra_umc_dev_server.broker_bench` speaks MQTT 3.1.1 to it with the standard library and runs seven scenarios: `/metrics` is valid Prometheus text, a client with no credentials or a wrong password is refused, a state published by a robot reaches the operator, a command published by the operator reaches the robot, a robot that asks for the whole swarm is refused and hears nothing, and a command a robot is not allowed to give is not delivered (both refusals must be counted in `/metrics`). The manual workflow `broker-bench.yml` starts the container on a CI runner and runs them; the scenarios are tested here against a stand-in broker (12 tests).

## [0.2.5] - A second container bench drives the data lake: `bench/docker-compose.data.yml` builds the data lake from its sibling checkout and publishes it on the loopback interface only; `compose_bench.py --suite data` (the swarm suite stays the default) runs five scenari

- **A second container bench drives the data lake:** `bench/docker-compose.data.yml` builds the data lake from its sibling checkout and publishes it on the loopback interface only; `compose_bench.py --suite data` (the swarm suite stays the default) runs five scenarios against it: the health route, a write refused without the token or with a wrong one, three samples written with the token and read back, the average of two samples, and malformed samples answered with a client error and never a server fault. The manual workflow `data-bench.yml` starts the container on a CI runner and runs them; the scenarios are tested here against a stand-in of the data lake (11 tests).

- **The code-server station can speak TLS, and it was tried with the real code-server:** `remote_access.tls_cert_file` and `tls_key_file` (both or neither, absolute plain paths, `code-server` kind only, off by default) add `--cert` and `--cert-key` to the unit. The manual workflow "Real code-server over TLS" installs a fixed release, makes a throw-away certificate, starts code-server with the arguments of that unit and checks health over HTTPS with only that certificate trusted, that plain HTTP is only sent to HTTPS, that an untrusting client is refused and that `/` goes to the login page. 6 new tests.
- **The real source inspector is tested with a real `git` and a bare repository acting as the remote:** `tests/test_migration_real_git.py` (7 tests) covers a clean clone, a commit never pushed (with its files), modified, untracked and ignored files, a rename, a branch without an upstream, a folder that is not a repository and that the inspector writes nothing.
- **A container bench runs the swarm cell as real containers:** `bench/docker-compose.yml` reuses the compose file of the orchestrator (orchestrator, job dispatcher, node healer, state replicator) and `compose_bench.py` drives it over HTTP with six scenarios (health, closed without the token, mission lifecycle, malformed input, the dispatcher reached through the orchestrator, recovery of an unknown node); every scenario reports PASS or FAIL and the run fails at the end, never at the first failure. The manual and weekly workflow `Container bench` starts the containers on a runner and runs it. The scenarios are tested here against a stand-in orchestrator (16 tests). The broker, voice, datalake and bridge containers are not part of the cell yet.
- **The sandbox is tested on a real kernel by a manual workflow:** `sandbox-real-host.yml` runs the real-host sandbox tests with bubblewrap as an ordinary user and with `systemd-run` as root on the Linux kernel of a CI runner, and fails when a test of the mode under test is skipped. It is a CI kernel, not the device: the run on the CM5 stays pending.

## [0.2.4] - A repair cycle can hand its runs to HYDRA-UMC-SERVER (off by default): RepairCycle(..., outcomesink=...) sends the run before the fix (when the failure is confirmed) and the run after it (when the check ends) as... (and 1 more changes)

- **A repair cycle can hand its runs to HYDRA-UMC-SERVER (off by default):** `RepairCycle(..., outcome_sink=...)` sends the run before the fix (when the failure is confirmed) and the run after it (when the check ends) as `ScenarioOutcome` 1.0 documents, and `repair report-outcome FILE --config FILE` sends one document by hand, to `POST /api/ingest/scenario-outcome`. The settings are a document (`configs/scenario-ingest.example.json`); the credential is a file (a token the server issued, or an account whose password is in a file) and never appears in a log or a result; it only goes over HTTPS or to this machine; a redirect is not followed; a sink that fails never changes the cycle.

- **The build test of the repository compiles only on CI or when allowed:** for the stacks that compile (`rust`, `go`, `android`, `flutter`, `firmware-c`), `tools/build_test.py` prints `BUILD_TEST=SKIPPED` with exit status 2 on a plain PC, never a pass; `ALLOW_LOCAL_BUILD=1` allows it and a CI runner always may. The `python` and `node` stacks are not locked.

## [0.2.3] - The identity of HYDRA-UMC-SERVER, off by default (serve --identity-key-file FILE, or HYDRAUMCDEVSERVERIDENTITYKEYFILE): the service verifies the signed token (HS256 JWT with exp, username and role) that the server issues at... (and 3 more changes)

- **The identity of HYDRA-UMC-SERVER, off by default (`serve --identity-key-file FILE`, or `HYDRA_UMC_DEV_SERVER_IDENTITY_KEY_FILE`):** the service verifies the signed token (HS256 JWT with `exp`, `username` and `role`) that the server issues at login and accepts it next to its own token. A viewer may read but not change, and a request with no credential is refused even on loopback, `GET /health` and `GET /stats` included: nothing is open. An address that is not loopback no longer needs a token of the service. The key is the signing key of the server, read from a file that only the group of the service may read, at least 32 characters; without the switch nothing changes. `server_identity.py` is the canonical copy of the SDK, and `python -m hydra_umc_dev_server.server_identity probe --port PORT` is the probe of a container, which signs a short-lived token of its own with the same key file.

- **A channel for the nodes with one token per node, off by default (`serve --node-channel FILE`):** `POST /v1/incident-transport` takes an `incident-transport/1` message from a node and answers `{"ok": true}` once it is stored, which is what the escalation outbox of the local technician waits for. Each node has its own token: `node-token issue NODE --tokens-file F --out FILE` writes it to a new private file (never printed) and the server keeps only its hash, issuing again replaces it, `node-token revoke NODE` stops it from the next request. The token only opens this route (the API token is not accepted there) and the message behind it is still verified: sender equal to the node of the token, HMAC of the node, time window, nonce and rate, so a stolen token alone forges nothing. A retry of the same escalation is acknowledged as a duplicate and stored once. Without the channel file the route answers `404`.

- **The common `GET /health` of the family, closed by default:** `serve --health-open` (or `HYDRA_UMC_DEV_SERVER_HEALTH_OPEN=1`) makes the server answer `GET /health` with `{"status": "ok", "service": "hydra-umc-dev-server", "version": ...}` to a caller on loopback and, to any other caller, only with the bearer token; closed (the default) it answers `404`. It is the route the other services of the family offer, written once (`health_route.py`, kept identical to the copy of the SDK), and it is described in `docs/openapi.json`.
- **Deprecation notice:** `GET /v1/health` is unchanged in this version (open, `{"status": "ok"}`, with the version and the plugin count for the token). It is deprecated in favor of `GET /health` and will be closed by default, like the common route, in a later version.
## [0.2.2] - A trust store of public keys with aliases, the bubblewrap sandbox run on a real host and the unit of the code-server station checked against a real systemd

- **A trust store of public keys with aliases** (`trust_store.py`, `configs/trust-store.example.json`): a JSON document `{"trusted_keys": {alias: "ed25519-public:..."}, "revoked": [alias]}` says whose signatures a host accepts. It holds public keys only: a private key found in it is refused with the alias named (never the value) and left out, a malformed entry is left out and named, a revoked alias never verifies, and an alias that already holds another key cannot be re-pointed (revoke it and use a new alias). A signature is attributed to the alias whose key made it, so the answer says "signed by <alias>" and an unknown signer is a refusal. `trust list`, `trust add` and `trust revoke` manage the file; `repair check-candidate --trust-store` and `ops verify-backup --trust-store` (each with an optional `--signer`) use it and name the signer; `RepairCycle.receive_candidate_trusted` and `apply_approval_trusted` take the candidate's key and the approver's key (by `approved_by`) from it; `restore_backup(trust_store=)` refuses a manifest nobody trusted signed. The private key never leaves the approver: the store has no function that reads one. Tested (21 tests).
- **The bubblewrap sandbox was run on a real host too** (the same `tests/test_sandbox_real_host.py`, now with `bwrap` installed): a task writes in its workspace and nowhere else, cannot read the home of the service user, sees an empty `/tmp` and has no network. Together with the `systemd-run` runs, both sandboxes of the runner have now been run on a real kernel.
- **The unit of the code-server station against a real systemd** (`tests/test_code_server_unit_real_host.py`): `systemd-analyze verify` accepts the text the plan writes, and, with a stand-in for the program, a unit started as root does not start without the password file, starts with it, reads the hash from the environment file, writes in the two directories code-server writes to and cannot write anywhere else in the home. Skipped, saying why, where there is no systemd as init or the tests are not root. The real code-server under these restrictions, with its TLS, still has to be tried on a station.

## [0.2.1] - A local bench that runs the services of the ecosystem against each other, without Docker and without a robot

- **A local bench that runs the services of the ecosystem against each other, without Docker and without a robot** (`python -m hydra_umc_dev_server.bench`). A goal is planned (a proposal that needs an approval), the safety zones say whether the cell is clear, the twin signs the risk of the first movement and only then the dispatcher gets the job; a person in the cell stops the chain before any certificate or job. With the real bridge and the twin's simulated robot, a certified command also moves a simulated joint over time and the twin follows it as measured. Each service is one you give (`--planner URL` ...), one the bench starts (`--real`: the planner and the safety zones as Python processes, the twin and the bridge from their built binaries, on loopback ports, with throw-away keys and folders) or a simulated stand-in that speaks the documented contract (the default, which is what lets CI run it anywhere). The report says which is which; a scenario that cannot run says why instead of passing. The dispatcher (a Go program) and the server are given by URL or simulated.

## [0.2.0] - A health route that no longer shows the exact version, consistent HTTP status codes and the universal README

- **The health route no longer shows the exact version to anybody:** `GET /v1/health` answers `{"status": "ok"}` without the token and adds the version and the plugin count only with it; `serve --public-health-detail` restores the old open answer. A check, report or generator that ran and failed now answers `502` (and `504` when it ran out of time) instead of `200` with an error body; the body is the same.
- **The HTTP status codes of the local API are consistent:** a missing token is answered `401` with `WWW-Authenticate: Bearer`; a known route called with the wrong method, and any method other than `GET` and `POST`, is `405` with an `Allow` header and a JSON body (it was `404` or the standard library's `501` HTML page); a failure inside the server is a `500` with a JSON body and no trace instead of a dropped connection. The OpenAPI document names the new answers. Tested.
- **README in the universal layout:** the README and its seven translations follow the layout that the four families share (22 sections in a fixed order), with an architecture picture and a repository-structure picture drawn from `docs/architecture.json` and `docs/structure.json`; the CI validator checks both pictures and the file tree.

- **The layout of the README is checked in the CI:** the validator runs `tools/universal_readme_check.py` and lists, as a warning, what differs from the universal layout of the README.

## [0.1.9] - More CI and the `systemd-run` sandbox was run on a real systemd host

### Firmware and protocol

- **Asymmetric signatures** (`signing.py`, Ed25519 of RFC 8032, no dependency, checked against its test vectors): repair candidates, approvals and backup manifests can be signed with a private key and checked with the public key alone; a public key never accepts an HMAC signature. `ops keygen`, `ops sign-backup` and `ops verify-backup --public-key-file/--signature-file` (and `restore_backup(public_key=, signature=)`) refuse a manifest regenerated over replaced files. Not constant-time: sign on the operator's own machine.
- **Preflight and plan agree**: a host without the dedicated account passes the preflight with `will_create` instead of failing, so `station plan --preflight` can be used on a new host; the workspace is checked as the account of the station, not as the user running the check; and for `ssh-remote` the account must have a real shell and an `authorized_keys` file instead of no login shell.
- **The code-server unit can start**: it may write where code-server writes (`ReadWritePaths`, `HOME` and the XDG directories), reads the password hash from an environment file and does not start without it, and code-server is installed from its official installer instead of `apt-get`. The dedicated account is created with an empty home closed to other users (no skeleton files). Not run under a real systemd.
- **The incident verifier can remember**: `SqliteVerifierState` keeps the nonces and the per-node rate log in a SQLite file (WAL), purged by their windows, and the check and update of one message are one transaction. `incident verify --state-file` uses it, so a replayed message is caught by the next run; without the option the command says that it remembers nothing.

### Tests, builds and checks

- **More CI**: a second workflow (`checks.yml`) runs the tests on Python 3.11, 3.12 and 3.13, `ruff check --select F,E9,B` (the findings it had are fixed: a `raise ... from None`, a loop variable captured by a class, unused names and imports, and `assertRaises(Exception)` replaced by the exact error) and the runner, workspace and sandbox tests on Windows.
- **The `systemd-run` sandbox was run on a real systemd host** (`tests/test_sandbox_real_host.py`: write only in the workspace, no home, no network, `MemoryMax` and `TasksMax` enforced by the kernel; skipped with the reason where there is no usable sandbox; bubblewrap has not been run). It found two faults, now fixed: a workspace under `/tmp` or `/var/tmp` made the unit fail to start, so the workspace is bound into the unit (`BindPaths`); and a workspace under `/home`, `/root` or `/run/user` cannot be reached under `ProtectHome`, so it is refused with the reason before anything runs. **Signing uses the `cryptography` package when it is installed** (optional `signing` extra, constant-time) for the public key and the signature, and the pure RFC 8032 code otherwise or with `HYDRA_UMC_DEV_SERVER_PURE_ED25519=1`; `signing_backend()` says which, and a test checks that both give the same bytes.
- **The local API limits and records itself**: at most 32 requests at once (the next gets 503), `GET /v1/audit` with the last 500 requests (never a body or a token), and `docs/openapi.json`, kept equal to the handler by a test.
- `bump_version.py` carries MINOR into MAJOR like the shared utility, its header says so, and a test keeps both equal.
- The READMEs name the twenty-two modules; the test counters follow the suite (418).
- **The AI budget holds for one call too**: a provider whose `complete()` takes `max_tokens` / `max_cost_usd` is told what is left; a call whose own tokens or cost go past it is `budget-exhausted` and its answer is not used (the usage it burned is counted); negative, non-finite or non-numeric usage is `rejected`; any other exception of a real SDK is `rejected` instead of escalating; and the step itself waits at most `timeout_seconds`, whatever the provider does. 11 new tests.
- The READMEs name the twenty modules that exist (they listed sixteen) and no longer say that this repository runs nothing; the test counters follow the suite (347).
- **Arguments are allow-listed, not only the command**: new `allowed_arguments` per command, and always no absolute, home or `..` path (also in `--option=value`), no NUL byte and none of the options that load code of well-known tools (`pytest -p/-c/-o/--rootdir`, `python -c`, `bash -c`, `node -e`, ...) unless the policy lists that option. `./build.sh` and `build.sh` are the same script.
- **`task run` stages, limits and cleans up**: `repo_sources` maps a repository to its source and the pinned revision is fetched with git (scrubbed environment, no prompts, no user configuration, file and https only) and checked against the pinned commit; `max_concurrent_tasks` is enforced across processes with one lock file per task (a dead lock is taken over); `workspace_retention` (`delete-on-success` by default) removes the workspace afterwards and `--replace-workspace` replaces a leftover one.
- 35 new tests (339 in all, also run on Linux).
- Building no longer changes the version; raising it is the explicit `bump` command (`python tools/hydra_project_tool.py bump`). The build scripts only report the version they built, and CI fails if a build script runs a bump.
- The build and run scripts use the Python of the `.venv` directly instead of an activate script, and create the venv with the `py` launcher when there is one; CI fails if a script activates a venv.
- **The READMEs name the real test command** (`python -m unittest discover -s tests`, the suite is `unittest` and needs no pytest), in the eight languages.
- Added `tools/hydra_project_tool.py`: the same `validate`, `test`, `version`, `status` and `bump` commands in every repository. The checks run with `HYDRA_UMC_CI=1` and fail if the version changes; only `bump` changes it.

### Other changes

- **Approvals are asymmetric and bound to the patch.** A repair cycle verifies candidates and approvals with Ed25519 public keys only; a shared HMAC secret is refused unless `allow_symmetric_keys` is set. An approval now carries the patch it approves (`approved_patch_ref`) and an expiry (`expires_at`, UTC), both part of the signature, and a cycle refuses an approval for another patch, without them, or expired (`require_bound_approval`, on by default). An approval signed before these fields existed still verifies when the cycle does not require them.
- **A worker loop** (`src/hydra_umc_dev_server/worker.py`, `queue work`): it leases the oldest queued task, stages `repo@revision`, runs it in the sandbox while it renews the lease every third of its length, records the result and removes the workspace according to the retention. A task that cannot start is recorded as failed instead of staying leased, a lease that is lost cancels the run, and the slot of `max_concurrent_tasks` is taken before anything is leased. Tested with fakes of the launcher, git and the clock; it has not run on a real host.
- **Resource limits for the sandboxed task**: the task policy gets `sandbox_memory_max`, `sandbox_cpu_quota` and `sandbox_tasks_max`, which the `systemd-run` sandbox turns into `MemoryMax` (no swap), `CPUQuota` and `TasksMax` of the task's cgroup; bubblewrap has no cgroup and does not enforce them. The command lines are tested; no limit has been enforced on a real host.
- **One list of what a name may look like** (`identifiers.py`): account names, path text and task/worker ids are checked by the same allow-list in the remote-station profile, the workspace and the worker. Side effects: a `..` segment is refused in the profile paths, and an id with a trailing newline (accepted by the old pattern) is refused.
- **A real sandbox for the task runner** (`src/hydra_umc_dev_server/sandbox.py`): the command runs inside bubblewrap (system read-only, no home, empty `/tmp`, only the workspace writable, no network) or a transient systemd-run unit (`ProtectHome`, `ProtectSystem=strict`, `PrivateTmp`, `PrivateNetwork`, `NoNewPrivileges`) when the host has one. The task policy gets `sandbox` (`auto` by default), `sandbox_required`, `sandbox_network` and `sandbox_read_only_paths`; the result says which sandbox was used and `task run` warns when there is none. The command lines are tested; the isolation itself has not run on a real host.
- The task `PATH` is fixed on a POSIX host, and a bare script name is looked up in the workspace (a missing `./script` is a clean rejection).
- **Plugins run in their own process by default**: every call starts a `python -I` process in an empty temporary directory with a scrubbed environment, CPU and file-size limits and the process group killed on timeout; the module is handed over as the approved bytes (no second read of the file, no import of neighbouring files), the answer follows a marker so printed output cannot be mistaken for it, at most four calls run at once, and the registry is locked against parallel rescan, enable and disable. `HYDRA_DEV_SERVER_PLUGIN_ISOLATION=thread` keeps the in-process mode, which now also executes the approved bytes and counts overrunning calls so they cannot pile up.
- The banner follows the animated style of the ecosystem banners, with the name, the kind and the technologies of the project.

## [0.1.8]

- Build version synchronized with `hydra-umc.project.json` and the repository-native version source.
- The licence is written as GPL-3.0-or-later in every header and in the package metadata.

## [0.1.7] - Plugins can provide reports and generators

- **New plugin kinds:** besides checks, a plugin can now offer **reports** (read-only descriptions of a state) and **generators** (a function that takes a small parameter object and returns one text file). The manifest declares them with a new optional `provides` list (`checks`, `reports`, `generators`; it defaults to `["checks"]`, so existing plugins need no change), and `register` may only use the registration methods of the kinds it declared. A plugin that registers an undeclared kind, or whose `register` raises halfway, ends `failed` with nothing registered.
- **Same sandbox for all three kinds:** a 10 second timeout, an answer that must be JSON of the right shape and at most 256 KiB, generator parameters of at most 4096 bytes handed over as a copy, and a generator filename that must be a plain file name. An exception (even `SystemExit`), an overrun or a malformed answer is an error entry; it never changes the plugin's state or touches another plugin. A generator's text is returned to the caller and never written to disk.
- **CLI and HTTP:** new `plugin run` enables one plugin for a single process against the approved SHA-256 and runs one check, report or generator; new `POST /v1/plugins/<name>/reports/<report>` and `POST /v1/plugins/<name>/generators/<generator>` behave like the check route (bearer token, bodies capped at 4096 bytes); `GET /v1/plugins` lists the kinds and the registered items.
- **Documentation and examples:** new `docs/PLUGINS.md` (manifest, lifecycle, limits, CLI, HTTP) linked from the README in all eight languages, and two example plugins under `examples/plugins/` (`host-report`, `readme-generator`) that the tests run.
- 306 tests (30 new): the manifest field, the lifecycle of each kind, every sandbox limit, failure isolation between plugins, the HTTP routes with and without the token, the CLI and both example plugins.

## [0.1.6] - Safer remote station and runner, verified incident sessions, race-safe queue

- **Remote station:** `0.0.0.0`, `::` and link-local addresses were accepted as "private" binds (Python counts them as private), so a code-server with a terminal could be planned on every network interface; they are now refused unless public binds are explicitly allowed. The user, home and workspace names are restricted to plain characters because they are written into a generated systemd unit (a newline in `home` used to add a root-run `ExecStartPre=`).
- **Task runner:** stopping a task now always sends SIGKILL to the whole process group after the grace period (a grandchild that ignored SIGTERM used to survive because the reaped child made the second signal a no-op), a task that exits normally no longer leaves background processes behind, the pipes are closed, the task's `HOME` is its own workspace, the Windows environment basics the documentation promised are passed on Windows, a command that cannot be started is a rejection instead of a traceback, and a symlink in `input_paths` that points out of the workspace is refused when a file system is supplied (`task run` does).
- **Incident transport:** a session used to trust anything its channel delivered; every inbound message must now verify (signature of the peer, recipient, version, freshness, nonce, rate), belong to the session's incident, and cannot move a finished session back. Nonces are random instead of a counter that restarts at 1 and old ones are forgotten after the replay window; a non-finite timestamp is refused. `IncidentSession` takes the peer's secret (`peer_secret`).
- **Repair cycle:** a new cycle is `not-started` and a blocked one is final (calling the first step again reopened it); a string such as "false" is no longer a truthy proof of reproduction or verification, and the asserts used as checks are real blocks.
- **Durable queue:** every read-then-write runs in one immediate transaction, a result is accepted only from the worker that still holds an unexpired lease, a task that keeps losing its worker is parked as `dead-letter` after five attempts, and enqueueing an existing task id with a different recipe is reported as a conflict.
- **Migration and backup:** files of a new directory and renamed files are classified correctly, a source with no git history is never called "published", files of unpushed commits are not "matching origin", symbolic links are never followed, more private names are recognized (`*.env`, `.git-credentials`, `.npmrc`, keys files), git runs with `--no-optional-locks`; a backup manifest with a path outside its root is refused and files are restored by atomic rename.
- **API and CLI:** a negative `Content-Length` is a 400 instead of an unbounded read, unreadable prompt, secret and output files are one-line errors, and the delivery summary names deliveries that are missing.
- **Docs and scripts:** the security policy describes what exists today, the plugin documentation says plugins run in the API process and are trusted code, the package description and the deployment-target note are current, `run.bat` keeps the exit code, the build compiles the whole package, and the git-dependent tests skip without a checkout (276 tests).

## [0.1.5] - Maturity moves to functional

- The project maturity moves from `scaffolding` to `functional`: the development API (with its 401 behaviour for unauthenticated requests), the plugin lifecycle over HTTP and the manifest version check are all covered by tests, and the exit criteria in `docs/MATURITY_CRITERIA.md` are ticked.
- `deliver evaluate` now reports `overall_maturity` as the literal `"functional"` (still no branch that can return anything higher) and exits `1` if the value is ever different; the honest summary and the known limitations still state that nothing has been verified on real hardware or services and that only the deterministic fake AI provider ships.
- Updated the delivery, architecture and CLI reference documents and the tests to match.
- Updated the badge, status block, manifest example and maturity paragraph in every README (English, Spanish, German, French, Italian, Japanese, Chinese and Portuguese).

## [0.1.4] - Runner output handling and idle connections

- Fixed the bounded task runner deadlocking on a child that prints more than a pipe holds (64 KiB on Linux): the child's stdout and stderr were read only after it exited, so such a task blocked on its own write until the timeout killed it and its output was lost. Both streams are now read continuously by background readers and only the last 8 KiB of each is kept, so a verbose build or test run completes normally and memory stays bounded; invalid UTF-8 is replaced instead of failing.
- The local API handler now drops a connection that stays idle for 15 seconds instead of holding a thread forever, with a test that stalls a connection and checks the server keeps answering.
- Added tests for the runner with large output and for the idle connection (252 tests in total).
- Documented the output handling in the workspace and runner guide and the idle timeout in the CLI reference.
- Added the Portuguese README (README_por.md) and corrected the item 7 description and the test count in every README.

## [0.1.3] - Stable cancel test

- The cancel test now cancels only once both the child and the grandchild have written their pid, instead of after a fixed two seconds that was too short on a slow host.

## [0.1.2] - Local API and plugin lifecycle

- Added a plugin lifecycle: plugins are discovered without being imported, stay inert until enabled against the approved SHA-256 of their manifest and module, can only add named checks, and run under a timeout; a plugin that changed since approval, raises or overruns is reported, never loaded or trusted.
- Added serve, an HTTP API bound to loopback only with a bearer token (from a file or the environment, at least 24 characters, compared in constant time), capped request bodies, an inventory route and the plugin routes; it runs no task and deploys nothing.

## [0.1.1] - Honesty check section in every README

Added a "Honesty check" paragraph right after the intro badges in
`README.md` and all 6 translated READMEs, naming all sixteen real
`src/hydra_umc_dev_server/*.py` modules and the real test count (228
passing across `tests/test_*.py`). States plainly what none of that
real, tested code has ever touched: the target Raspberry Pi 5/CM5
hardware, a real remote host via `station preflight`/`station plan`,
a real AI provider behind `provider suggest` (only the deterministic
fake ships), or a running worker loop wiring the pieces together.
Documents the real, current state of what's implemented vs. planned;
no behavior changed.

## [0.1.0] - DS10: delivery package + honest maturity evaluation

Tenth and last delivery of ten. The plan closes the way it opened - by
describing, not claiming.

- `delivery.py`:
  - `build_delivery_manifest()` enumerates what this repository actually
    ships - every `src/hydra_umc_dev_server/*.py` module, every
    `docs/*.md`, every `configs/*.json`, plus `pyproject.toml`,
    `hydra-umc.project.json`, `CHANGELOG.md` and `README.md` - with a
    sha256 per file. It also reads back the real CLI surface (the
    `add_parser(...)` names in `cli.py`), the package version and the
    `tests/test_*.py` count.
  - `evaluate_maturity()` reports each of the ten deliveries as
    `shipped` / `partial` / `not-started` against real evidence (is the
    module actually in the tree). DS06 is reported **`partial`** on
    purpose - only the deterministic fake provider ships. The seven
    `known_limitations` are stated in plain words (no real AI provider,
    no real network transport, no container sandbox, no worker loop
    wiring the pieces together, nothing that provisions a host or
    deploys anything, no target hardware validated, every real-host
    contact behind an injectable seam).
  - `overall_maturity` is hard-coded `"scaffolding"`. This code has no
    branch that returns anything higher - the honesty guard is that the
    evaluation *cannot* over-claim.
- `cli.py` - new `deliver manifest` and `deliver evaluate` subcommands;
  `deliver evaluate` exits non-zero if the maturity is ever not
  `scaffolding`.
- `docs/DELIVERY.md`; `docs/ARCHITECTURE.md`, `docs/CLI_REFERENCE.md`,
  README x7 synced to DS01-DS10.
- 8 new tests (`test_delivery.py` + `deliver` cases in `test_cli.py`) -
  228 total.

The ten-delivery plan is complete. The maturity stays `scaffolding`:
what is here is contracts, limits and a verifiable skeleton. Nothing in
this repository provisions a host, runs a deploy, or has touched target
hardware - and `deliver evaluate` says exactly that.

## [0.0.9] - DS09: stable operation + verified state backup/restore

Ninth delivery of ten.

- `operations.py`:
  - `create_backup()` copies this host's named durable-state files into a
    backup dir and records a sha256 for each, with a `backup_id`, an
    `instance_id` and a `schema_version`. `verify_backup()` re-hashes
    every file and reports `mismatches` / `missing`. `restore_backup()`
    **refuses** a backup taken for a different `instance_id` or a
    different `schema_version`, or one whose files no longer match the
    manifest - otherwise it restores the exact bytes.
  - `check_operational_health(queue, ...)` reports a not-ok `HealthReport`
    with a named finding for: `orphaned-leases` (leased entries whose
    lease has expired but were not reconciled), `journal-over-cap`, and
    `low-disk` (free disk under the configured floor).
  - all filesystem contact is behind the injectable `BackupFs` seam.
- `cli.py` - new `ops health` and `ops verify-backup` subcommands.
- `docs/OPERATIONS.md`, README x7 synced.
- 14 new tests (`test_operations.py` incl. the backup round-trip and each
  refusal, plus `ops` cases in `test_cli.py`) - 220 total.

## [0.0.8] - DS08: one fully controlled repair cycle

Eighth delivery of ten. `RepairCycle` chains the pieces already built
into a single gated sequence:

    repro-confirmed -> incident-raised -> candidate-received
      -> regression-passed -> build-test-passed -> approved
      -> installed -> verified   (or -> recovered / -> blocked)

- `confirm_repro()` needs an actually reproduced failure for **this**
  repro case, or the cycle never opens.
- `receive_candidate()` blocks a candidate whose HMAC signature does not
  verify (tampered / unsigned), or that is pinned to a different
  incident, a different **base fingerprint**, or a different **target**.
- `run_regression()` / `run_build_test()` need a real green `RunResult`
  (`completed`, exit `0`).
- `apply_approval()` needs an approval signed by a **registered**
  approver AND issued **for this exact base and target** - an approval
  for another base/target is blocked.
- `install_isolated()` goes through an injectable `IsolatedInstaller`
  seam (never the real target). `verify()` rolls back and ends the
  cycle `recovered` on a failed post-install check; the
  "apparent success" control also voids the result (and rolls back) if
  the base fingerprint moved mid-cycle or the evidence is for a
  different repro case.
- `cli.py` - new `repair check-candidate` subcommand (the candidate
  gate, usable without a live cycle).
- `docs/REPAIR_CYCLE.md`, README x7 synced.
- 16 new tests (`test_repair_cycle.py` incl. the full happy path and
  each block/rollback, plus `repair` cases in `test_cli.py`) - 206
  total.

DS09 (stable operation + restore) does not exist yet.

## [0.0.7] - DS07: authenticated incident transport for the OPS-AGENT round trip

Seventh delivery of ten. A real protocol object - not a manual file
drop - for the incident round trip with HYDRA-UMC-OPS-AGENT.

- **`incident_transport.py`** - every message is HMAC-SHA256-signed by a
  registered node and carries a `nonce`, a `sent_at` and a
  `contract_version`. `verify_message()` rejects, each with a named code
  and a test:
  - `unknown-identity` (the channel is authenticated as a node not in
    the registry)
  - `bad-signature` (HMAC does not match the registered secret)
  - `impersonation` (`from_node` != the identity the channel proved)
  - `replay` (a nonce already accepted) / `stale` (a `sent_at` outside
    the replay window)
  - `overloaded` (more than `max_messages_per_minute` from one node)
  - `incompatible-version`
- **`IncidentSession`** runs the FULL round trip - `submit_incident` ->
  `diagnosis` -> `deploy-verification` - not just the submit. A dropped
  connection leaves the session in `pending-ack`; `reconcile()` re-sends
  the SAME incident with a fresh nonce, and the peer de-dupes on the
  stable `payload.incident_id` (re-ack, never re-process). A network
  blip loses nothing and double-counts nothing.
- **`cli.py`** - new `incident verify` subcommand.
- **`configs/incident-transport.example.json`** (the policy only -
  secrets are operator-held and never committed),
  **`docs/INCIDENT_TRANSPORT.md`**, README x7 synced.
- 17 new tests (`test_incident_transport.py` incl. the in-memory
  round-trip and the dropped-connection reconcile, plus `incident`
  cases in `test_cli.py`) - 190 total.

DS08 (a first fully controlled repair cycle) does not exist yet.

## [0.0.6] - DS06: interchangeable AI provider (deterministic fake) behind a safety contract

Sixth delivery of ten. Only the deterministic **fake** provider ships -
which real provider to use, and its authorization, is a user decision;
`ProviderConfig.kind` accepts `"fake"` and nothing else.

- **`ai_provider.py`** - `AIProvider` protocol (`complete(prompt) ->
  RawCompletion`, or raise). `FakeProvider(scenario=...)` is fully
  deterministic: `ok` returns a stable prompt-derived suggestion;
  `timeout` / `quota` / `malformed` / `injection` exercise each adverse
  path.
- **`run_provider_step(config, provider, prompt, usage_so_far=None)`** -
  the contract:
  - a provider timeout, quota exhaustion or malformed output becomes a
    bounded named outcome (`timed-out` / `budget-exhausted` /
    `rejected`), never an exception that escalates.
  - a configured `ProviderBudget` (calls / tokens / cost) stops the
    step **before** it would exceed - `budget-exhausted`, no call made.
  - the provider's answer is **data, never instructions**. A suggestion
    that says "ignore previous instructions / deploy now / grant me
    root" is copied verbatim into `suggested_text` and `injection_flagged`
    is set, but `grants_no_permissions` and `triggers_no_deploy` are
    **always** true - for every outcome. The result is inert: DS06 wires
    it to nothing (not the runner, not the queue, not a deploy).
- **`cli.py`** - new `provider suggest --config --prompt-file
  [--scenario]` subcommand.
- **`configs/ai-provider.example.json`**, **`docs/AI_PROVIDER.md`**,
  README x7 synced.
- 19 new tests (`test_ai_provider.py` + `provider` cases in
  `test_cli.py`) - 173 total.

DS07 (coordinated incidents with HYDRA-UMC-OPS-AGENT over an
authenticated transport) does not exist yet.

## [0.0.5] - DS05: durable SQLite queue + append-only execution journal

Fifth delivery of ten. A task queue and its execution journal that
survive a process restart. Nothing here runs a task - DS04's runner does
that; this records, durably, what happened.

- **`durable_queue.py`** - `DurableQueue(path)` over SQLite (WAL,
  immediate transactions for the lease). Two tables: `entries` (one row
  per `task_id`, the primary key) and `journal` (append-only).
  - `enqueue(recipe, base_fingerprint)` is idempotent - a second call
    with the same `task_id` returns `created=False` and adds no journal
    row. **A duplicate never becomes a second job.**
  - `lease(worker_id, ttl)` atomically claims the oldest `queued` entry,
    bumps `attempt`, sets `lease_expires_at`. `reconcile()` returns every
    entry whose lease has expired to `queued` (safe on every startup,
    idempotent).
  - `record_result(task_id, worker_id, run_result, observed_base_fingerprint)`
    is **rejected** (not accepted as done) if that worker no longer
    holds the lease - **an interruption never produces a false
    success**. If the observed base fingerprint differs from the one
    recorded at enqueue, the result is stored `failed` / `promotable=False`
    even on exit code `0` - **a base that moved invalidates promotion**.
    The `completed` journal event always carries `revision` and the
    `recipe_fingerprint` (sha256 of the canonical recipe).
  - the journal stores only truncated (2 KiB) stdout/stderr tails, and
    `prune_journal(keep_last_n_per_task)` caps rows - **logs and disk
    stay bounded** regardless of retry churn.
- **`cli.py`** - new `queue enqueue` / `queue status` / `queue reconcile`
  / `queue journal` subcommands.
- **`docs/DURABLE_QUEUE.md`**, README x7 synced.
- 15 new tests (`test_durable_queue.py` incl. a real tmp-file
  restart-survival case, plus `queue` cases in `test_cli.py`) - 156
  total.

DS06 (interchangeable AI provider - a deterministic fake first) does not
exist yet.

## [0.0.4] - DS04: bounded task recipe + isolated workspace runner

Fourth delivery of ten. This is the first delivery that actually
executes something - and it stays tightly gated. `task run` runs one
allow-listed command, in a per-task isolated workspace, with a scrubbed
environment, under a bounded timeout; it deploys nothing.

- **`workspace.py`** - `Workspace.resolve()` / `resolve_with()` refuse a
  path that escapes the workspace: a `..` that climbs past the root, an
  absolute path, or (via the real, symlink-followed path) a symlink
  whose target lands outside. `allocate_workspace()` gives each task id
  its own directory and refuses one that already exists - two tasks
  never share a workspace. All filesystem contact is behind the
  injectable `WorkspaceFs` seam.
- **`recipe.py`** - `TaskRecipe.from_dict()` (DS01-style error
  accumulation): a pinned `revision` (commit hash / vX.Y.Z tag /
  `refs/tags/...` - a bare branch name is rejected), a `command`, a
  bounded `timeout_seconds` (<= 1h). `validate_against(policy)` refuses
  any command whose `argv[0]` is not in the task policy's own
  `allowed_commands` (DS01 schema). `resolved_input_paths(workspace)`
  refuses a declared path that escapes the workspace.
- **`runner.py`** - `run_task()` rejects (spawning nothing) a
  disallowed command or an escaping input path; otherwise it spawns the
  child with a SCRUBBED environment - only `PATH` / `HOME` / `LANG` /
  `TZ` (plus non-secret OS basics on Windows), never an inherited
  `*_TOKEN` / `*_KEY` / `*_SECRET` / `ANTHROPIC_*` / `GITHUB_*` /
  `SSH_*`. On timeout or cancel the WHOLE process group is killed, not
  just the direct child. The `ProcessLauncher` seam lets the control
  tests prove all of this against a fake; `SubprocessLauncher` is the
  real one (POSIX `start_new_session` + `killpg`, Windows
  `CREATE_NEW_PROCESS_GROUP` + `taskkill /T`).
- **`cli.py`** - new `task validate` (recipe vs policy, runs nothing)
  and `task run --workspace-base` (the real, gated execution).
- **`configs/task-recipe.example.json`**,
  **`docs/WORKSPACE_AND_RUNNER.md`**, README x7 synced.
- 34 new tests (`test_workspace.py`, `test_recipe.py`, `test_runner.py`
  incl. one real test that spawns a child-of-a-child and confirms both
  are gone after a cancel, plus `task` cases in `test_cli.py`) - 141
  total.

DS05 (durable queue + traceable results) and DS06 (interchangeable AI
provider) do not exist yet.

## [0.0.3] - DS03: conservative migration (inventory + classification + separate-destination plan)

Third delivery of ten. Still read-and-describe only: nothing here copies a
file, deletes a file, runs a mutating `git` command, or touches the
source in any way.

- **`migration.py`** - `build_repo_inventory()` walks a source checkout
  (exactly the files git considers part of the project - a local
  virtualenv / build output / `__pycache__` is git-ignored and never
  inventoried), SHA-256s every file, and classifies each one:
  `tracked-clean` (published, matches origin), `tracked-modified`
  (uncommitted local edits), `untracked` (working files git does not
  track), `private` (a `PrivacyPolicy` - the private-planning folder, `.env*`, `*.pem`,
  `id_ed25519*`, ... - widenable by a document, never silently
  narrowed). It also records commits on the branch that were never
  pushed.
- **`build_migration_plan()`** - maps every file to exactly one
  destination by class, into four provably-separate roots
  (`MigrationDestinations.from_dict` refuses any pair that is equal or
  nested), plus a `<repo>.unpushed.bundle` under the work-in-progress
  root for the local commits. It refuses outright if a private file
  would ever resolve under a shareable root. The plan is JSON data with
  a full hash manifest; a later delivery (or a person) carries it out.
- **`SourceInspector`** protocol - every real disk/git read goes through
  it, so the whole suite runs against a fake tree; `SystemSourceInspector`
  is the one real, read-only implementation.
- **`cli.py`** - new `migrate inventory` and `migrate plan
  --destinations` subcommands. Accepts a single checkout or a directory
  of them.
- **`configs/migration-destinations.example.json`**,
  **`docs/MIGRATION_FROM_PC.md`** (the guide `docs/ARCHITECTURE.md`
  already referenced), README x7 synced.
- 34 new tests (`test_migration.py` + `migrate` cases in
  `test_cli.py`), 107 total, all offline.

DS04 (workspace + bounded runner), DS05 (durable queue) and DS06
(interchangeable AI provider) do not exist yet.

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
