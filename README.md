<p align="center">
  <img src="images/HYDRA_UMC_BANNER.svg" alt="HYDRA-UMC-DEV-SERVER banner" width="100%">
</p>

# 🖥️ HYDRA-UMC-DEV-SERVER

<p align="center">🇺🇸 <b>English</b> | <a href="README_spa.md">🇪🇸 Español</a> | <a href="README_fra.md">🇫🇷 Français</a> | <a href="README_ita.md">🇮🇹 Italiano</a> | <a href="README_deu.md">🇩🇪 Deutsch</a> | <a href="README_zho.md">🇨🇳 简体中文</a> | <a href="README_jpn.md">🇯🇵 日本語</a></p>

### 🏗️ Reproducible Development Host for the Whole Ecosystem

<p align="center">
  <img src="https://img.shields.io/badge/Licencia-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/Core-stdlib%20only-brightgreen.svg" alt="stdlib-only core">
  <img src="https://img.shields.io/badge/Delivery-DS01%20of%2010-367BF5.svg" alt="DS01 of 10">
</p>

> **Status: v0.0.1, scaffolding - DS01 of 10 (contracts, limits and a
> verifiable skeleton).** A real, tested configuration schema
> (`config validate`) whose default policy grants **no task deployment
> permission**, and read-only manifest discovery (`inventory scan`) that
> can find this ecosystem's own `hydra-umc.project.json` files -
> including this repository's own. No remote host, workspace, task
> runner, durable queue, or AI provider integration exists yet - those
> are DS02, DS04, DS05 and DS06, later deliveries. See
> [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) for the exact command
> surface that exists today.

---

## 1. 🛠️ TECHNICAL OVERVIEW

HYDRA-UMC-DEV-SERVER is development infrastructure for the HYDRA-UMC/URTC
ecosystem: a reproducible host (target: a Raspberry Pi 5 or Compute
Module 5, 8GB, NVMe-booted) that will host this ecosystem's own source
code and run bounded, policy-gated programming/build/test tasks - people
and AI assistants alike. It is **not** a new AI to train, **not** a
replacement operating system, and it never decides on its own that a
machine is safe to change.

This delivery (DS01) ships two real, independently useful pieces:

1. **Configuration schema** (`config validate`) - three JSON documents
   (`HostProfile`, `ToolchainPolicy`, `TaskPolicy`), each with real
   validation and a real negative test for every rejected shape. The one
   invariant that matters most from day one: `TaskPolicy.allow_deploy`
   defaults to `False`, and only a document that sets the literal JSON
   boolean `true` can ever produce a policy with it enabled.
2. **Manifest discovery** (`inventory scan`) - the same real, tested
   pattern HYDRA-UMC-OPS-AGENT's own edge role already uses to find and
   validate a `hydra-umc.project.json`, reused here rather than
   reimplemented.

```
$ hydra-umc-dev-server config validate configs/task-policy.example.json --kind task-policy
VALID: configs/task-policy.example.json (task-policy)
{
  "allow_deploy": false,
  "max_concurrent_tasks": 2,
  "allowed_commands": ["pytest", "build.sh", "build-test.sh"]
}

$ hydra-umc-dev-server inventory scan --root ..
{
  "root": "..",
  "projects": [
    {"name": "HYDRA-UMC-DEV-SERVER", "version": "0.0.1", "maturity": "scaffolding", "manifest_path": "../HYDRA-UMC-DEV-SERVER/hydra-umc.project.json"},
    ...
  ],
  "issues": []
}
```

There is no default/bare invocation beyond the demo `run.sh` performs,
and no GUI in this delivery - see
[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md) for the full, real command
surface.

## 2. 🧱 ARCHITECTURE & DESIGN DECISIONS

- **No task has deployment permission by default.** This is DS01's own
  literal acceptance criterion, enforced by `TaskPolicy`'s own dataclass
  default - not just stated in prose - and covered by a dedicated test
  for every way a document could try to smuggle it in (a missing field,
  a misspelled one, a non-boolean value).
- **A collector reports a real, honest failure - it never guesses.**
  `scan_project_manifests()` returning a `ManifestScanIssue` for a
  present-but-broken manifest, rather than silently dropping it, is the
  established pattern this ecosystem already uses elsewhere (see
  HYDRA-UMC-OPS-AGENT's own `inventory.py`) - reused here, not
  reinvented.
- **Ownership and cross-project relationships are not this repository's
  to redecide.** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
  [docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md) document this
  repository's own state-ownership table and its grouping of 17
  cross-project relationships into necessary/optional/development-only.
- **stdlib only for this delivery.** `config validate` and `inventory
  scan` need no third-party dependency at all - a later delivery adds
  one only once that delivery's own code genuinely needs it (a durable-
  queue driver for DS05, an AI-provider SDK for DS06), never
  speculatively.
- **This delivery only ever validates and discovers - it does not run
  anything.** There is no workspace, no task execution, no queue, and no
  network call anywhere in this repository yet.

## 📂 DIRECTORY STRUCTURE

```
HYDRA-UMC-DEV-SERVER/
├── src/hydra_umc_dev_server/
│   ├── config.py        # HostProfile/ToolchainPolicy/TaskPolicy schema + validation
│   ├── inventory.py     # Real, read-only hydra-umc.project.json discovery
│   └── cli.py            # config/inventory subcommand entry point
├── configs/
│   ├── host-profile.example.json
│   ├── toolchains.example.json
│   └── task-policy.example.json   # allow_deploy: false, shipped and tested that way
├── tests/                # Real tests for every module above, incl. the shipped example configs
├── docs/
│   ├── CLI_REFERENCE.md    # Every subcommand, flags, exit codes
│   ├── CONFIG_SCHEMA.md    # The real JSON shape of all three configuration documents
│   ├── ARCHITECTURE.md     # Purpose, working modes, initial scope, disk layout
│   └── OPS_INTEGRATION.md  # The 17-relationship map + state-ownership table
├── images/                # Media and app icons
├── tools/
│   ├── build_test.py      # Non-versioning build/compile check
│   └── ci_validate.py     # Manifest/CHANGELOG/docs validation used by CI
├── build.sh / build.bat   # venv + editable install + compile-check + tests
├── build-test.sh / .bat   # Non-mutating build validation only
├── run.sh / run.bat       # Real inventory scan + config validate demo (no arguments), or forwards a real CLI command
├── bump_version.py        # Ecosystem-wide odometer bump (pyproject.toml + __init__.py)
└── bump_manifest_version.py # Syncs hydra-umc.project.json's version to the native one (--sync)
```

## ⚙️ BUILD & RUN GUIDE

```bash
chmod +x build.sh   # one-time
./build.sh          # creates .venv, pip install -e ".[dev]", compile-checks + tests
./run.sh                                  # real demo: inventory scan against this
                                           # GitHub workspace, then config validate
./run.sh inventory scan --root DIR
./run.sh config validate configs/task-policy.example.json --kind task-policy
```

On Windows: `build.bat`, then `run.bat` (same demo with no arguments) /
`run.bat inventory scan ...` / `run.bat config validate ...`.
`build-test.sh`/`.bat` performs the same non-mutating Python-syntax
compile check this project's own CI workflow performs, without touching
the project version or CHANGELOG - it does NOT run the test suite itself;
run `./build.sh`/`build.bat` (or `pytest tests/` directly) for the full
local test suite.

**Troubleshooting**

- `config validate` exits `1` with `INVALID: ...`: read the message - it
  lists every field that failed, not just the first. Check
  [docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md) for the exact expected
  shape.
- `inventory scan` reports an issue for a directory you expected to be
  clean: that directory has a `hydra-umc.project.json` that is present
  but unreadable, malformed, or missing a required field - a directory
  with no manifest at all is never reported as an issue.

## 🚀 ROADMAP

This version ships DS01 only. What remains, in delivery order:

- **DS02 - Reproducible remote station.** Preflight checks, a minimal
  tool profile, remote VS Code access under a real identity.
- **DS03 - Conservative migration.** Inventory and batch-copy from the
  user's PC with hashes, local changes and privacy handled explicitly.
- **DS04 - Workspace and bounded runner.** Real per-task isolation: two
  tasks never collide, a path outside the workspace is rejected.
- **DS05 - Durable queue and traceable results.** IDs, leases, a real
  execution journal that survives a restart.
- **DS06 - Interchangeable AI provider.** A deterministic fake provider
  first, a real authorized one after.
- **DS07-DS10** - coordinated incidents with HYDRA-UMC-OPS-AGENT, a first
  fully controlled repair cycle, stable operation/restoration, and a
  delivery package with an honest maturity evaluation.

None of the above exists in this repository yet - see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for what each delivery is
scoped to include and explicitly exclude.

## 🔗 Related Projects

This project is part of the HYDRA-UMC robotics ecosystem by the same author (JuanenRac / Electro Hobby 3D). Worth knowing about, since a request might actually be about one of these rather than this repository.

**Directly Related**
- **[HYDRA-UMC-OPS-AGENT](https://github.com/JuanenRac/HYDRA-UMC-OPS-AGENT)** — owns the maintenance-incident lifecycle (evidence, diagnosis, human-approved change, canary deploy, verification); DEV-SERVER coordinates with it rather than replacing it, and never approves its own tasks.
- **[HYDRA-UMC-SDK](https://github.com/JuanenRac/HYDRA-UMC-SDK)** — the shared JSON-Schema contract every task/result exchange between DEV-SERVER and the rest of the ecosystem will validate against, once that contract exists.
- **[HYDRA-UMC-UPDATER](https://github.com/JuanenRac/HYDRA-UMC-UPDATER)** — the real consumer of a DEV-SERVER-built, OPS-AGENT-approved candidate; delivery to a node always goes through UPDATER's own atomic-by-verification path, never a direct copy from a runner.
- **[HYDRA-UMC-OS-REBUILDER](https://github.com/JuanenRac/HYDRA-UMC-OS-REBUILDER)** — another "Ecosystem Operations" sibling: builds a fresh CM5 image rather than hosting development work.

**Also Part of the Ecosystem**

*Core Hardware & Platform*
- **[HYDRA-UMC](https://github.com/JuanenRac/HYDRA-UMC)** — the physical robot-arm motherboard: CM5 host + dual-core STM32H745, orchestrating up to 8 tool arms over CAN-OTA/SPI-OTA.
- **[HYDRA-UMC-OS](https://github.com/JuanenRac/HYDRA-UMC-OS)** — reproducible Raspberry Pi OS product layer for the CM5: read-only agent, validated config/profiles, WiFi first-contact provisioning.

*Core Backend & Clients*
- **[HYDRA-UMC-SERVER](https://github.com/JuanenRac/HYDRA-UMC-SERVER)** — the real headless backend (REST/WebSocket) every control client actually talks to.
- **[HYDRA-UMC-STUDIO](https://github.com/JuanenRac/HYDRA-UMC-STUDIO)** — web control dashboard with real-time multi-robot 3D visualization.
- **[HYDRA-UMC-SUITE](https://github.com/JuanenRac/HYDRA-UMC-SUITE)** — desktop (PySide6) swarm command center for multiple servers at once.
- **[HYDRA-UMC-ANDROID-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-ANDROID-CONTROL)** — native Android control app with biometric login and a paired Wear OS companion.
- **[HYDRA-UMC-IOS-CONTROL](https://github.com/JuanenRac/HYDRA-UMC-IOS-CONTROL)** — iOS/iPadOS control app (Flutter) with real-time WebSocket sync.
- **[HYDRA-UMC-DSI](https://github.com/JuanenRac/HYDRA-UMC-DSI)** — native touch UI for the onboard 7" DSI touchscreen, embedded on the CM5 itself.
- **[HYDRA-UMC-EDITOR-URDF](https://github.com/JuanenRac/HYDRA-UMC-EDITOR-URDF)** — desktop graphical URDF creator/editor that pushes finished models into STUDIO's own catalog.
- **[HYDRA-UMC-BRIDGE-AMR](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-AMR)** — coordination boundary for AGV/AMR fleets via a real VDA 5050 MQTT publisher.
- **[HYDRA-UMC-BRIDGE-CNC](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-CNC)** — high-level CNC-cell coordinator with real GRBL status/control-byte access.
- **[HYDRA-UMC-BRIDGE-DROIDS](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-DROIDS)** — coordination boundary for legged/humanoid droids, with a real Boston Dynamics Spot command sender.
- **[HYDRA-UMC-BRIDGE-LASER](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-LASER)** — laser-cell safety coordinator reading 3 real key/enclosure/interlock GPIO safeguards.
- **[HYDRA-UMC-BRIDGE-OPENPNP](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-OPENPNP)** — safe high-level board-flow coordinator for OpenPnP pick-and-place.
- **[HYDRA-UMC-BRIDGE-PRINTER3D](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-PRINTER3D)** — safe coordination boundary for Moonraker/Klipper 3D printers, with real gated job commands.
- **[HYDRA-UMC-BRIDGE-ROS2](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-ROS2)** — safety coordinator with a real, lazily-imported rclpy ROS 2 transport.
- **[HYDRA-UMC-BRIDGE-UAV](https://github.com/JuanenRac/HYDRA-UMC-BRIDGE-UAV)** — coordination boundary for camera-equipped UAVs, with a real MAVLink command sender.

*URTC Tool Platform*
- **[URTC](https://github.com/JuanenRac/URTC)** — firmware for the physical Universal Robot Tool Controller PCB, 25+ tool profiles over CAN bus.
- **[URTC-FLASHER](https://github.com/JuanenRac/URTC-FLASHER)** — desktop GUI flashing tool for URTC boards, CAN-OTA plus full-chip SWD/JTAG.
- **[URTC-TESTER](https://github.com/JuanenRac/URTC-TESTER)** — desktop live CAN-bus diagnostic tool for URTC boards, one panel per tool profile.
- **[URTC-WEB-STUDIO](https://github.com/JuanenRac/URTC-WEB-STUDIO)** — browser-based alternative to URTC-TESTER via the Web Serial API, no local install needed.

*Vision AI Node (Hailo-8)*
- **[HYDRA-UMC-VISION-NODE](https://github.com/JuanenRac/HYDRA-UMC-VISION-NODE)** — integration hub for the Hailo-8 vision pipeline, with a real per-stage hardware-readiness check.
- **[HYDRA-UMC-DETECTION-HEF](https://github.com/JuanenRac/HYDRA-UMC-DETECTION-HEF)** — real compiled-model registry with Hailo-architecture/checksum safe-load verification.
- **[HYDRA-UMC-VISION-STREAMER](https://github.com/JuanenRac/HYDRA-UMC-VISION-STREAMER)** — real GStreamer pipeline + MediaMTX config generator with a real HailoRT integration boundary.
- **[HYDRA-UMC-VISUAL-SERVOING-API](https://github.com/JuanenRac/HYDRA-UMC-VISUAL-SERVOING-API)** — real Position-Based Visual Servoing correction law, safety-gated on upstream zone state.
- **[HYDRA-UMC-SAFETY-ZONES](https://github.com/JuanenRac/HYDRA-UMC-SAFETY-ZONES)** — real zone-breach checking and E-STOP requesting, with calibration-freshness enforcement.

*Cognitive AI Node (Hailo-10)*
- **[HYDRA-UMC-COGNITIVE-NODE](https://github.com/JuanenRac/HYDRA-UMC-COGNITIVE-NODE)** — integration hub for the Hailo-10 cognitive pipeline (LLM/VLA/voice orchestration).
- **[HYDRA-UMC-VLA-ENGINE](https://github.com/JuanenRac/HYDRA-UMC-VLA-ENGINE)** — real action-token encoding/decoding and trajectory generation for a Vision-Language-Action model.
- **[HYDRA-UMC-VOICE-UI](https://github.com/JuanenRac/HYDRA-UMC-VOICE-UI)** — real voice front-end (VAD + intent parser) with a bounded, confirmation-gated Watch relay.
- **[HYDRA-UMC-SEMANTIC-PLANNER](https://github.com/JuanenRac/HYDRA-UMC-SEMANTIC-PLANNER)** — real rule-based task decomposition and semantic error recovery over MCU error codes.
- **[HYDRA-UMC-DOCS-QA](https://github.com/JuanenRac/HYDRA-UMC-DOCS-QA)** — real stdlib-only TF-IDF document search over this ecosystem's own Markdown docs.

*Orchestration & Swarm*
- **[HYDRA-UMC-ORCHESTRATOR](https://github.com/JuanenRac/HYDRA-UMC-ORCHESTRATOR)** — integration hub with a real gRPC/Protobuf health-report contract and mission state machine.
- **[HYDRA-UMC-JOB-DISPATCHER](https://github.com/JuanenRac/HYDRA-UMC-JOB-DISPATCHER)** — real priority-based job queue with deduplication, over a real HTTP API.
- **[HYDRA-UMC-NODE-HEALING](https://github.com/JuanenRac/HYDRA-UMC-NODE-HEALING)** — a real gRPC-based fleet health watchdog with its own retry/backoff and identity-mismatch detection.
- **[HYDRA-UMC-PATH-PLANNER-3D](https://github.com/JuanenRac/HYDRA-UMC-PATH-PLANNER-3D)** — real RRT-based 3D path planner with real obstacle/workspace collision validation.
- **[HYDRA-UMC-SWARM-SYNC](https://github.com/JuanenRac/HYDRA-UMC-SWARM-SYNC)** — real CRDT LWW-Element-Map state sync, property-tested for multi-cell convergence.

*Digital Twin & Simulation*
- **[HYDRA-UMC-TWIN](https://github.com/JuanenRac/HYDRA-UMC-TWIN)** — integration hub for the digital-twin engine, with a real version-compatibility sync contract.
- **[HYDRA-UMC-HIL-BRIDGE](https://github.com/JuanenRac/HYDRA-UMC-HIL-BRIDGE)** — real hardware-in-the-loop safety interlock routing commands between simulation and real hardware.
- **[HYDRA-UMC-PHYSICS-REPLICA](https://github.com/JuanenRac/HYDRA-UMC-PHYSICS-REPLICA)** — real forward kinematics and joint-limit validation over a real URDF subset.
- **[HYDRA-UMC-SYNTHETIC-DATA-GEN](https://github.com/JuanenRac/HYDRA-UMC-SYNTHETIC-DATA-GEN)** — real procedural 2D scene generator with YOLO/COCO annotation export.

*Data & Analytics*
- **[HYDRA-UMC-DATALAKE](https://github.com/JuanenRac/HYDRA-UMC-DATALAKE)** — real sqlite3-backed time-series store with a real ingest/query HTTP API.
- **[HYDRA-UMC-ANOMALY-DETECTOR](https://github.com/JuanenRac/HYDRA-UMC-ANOMALY-DETECTOR)** — real FFT + statistical baseline anomaly detector with drift monitoring.
- **[HYDRA-UMC-PRODUCTION-REPORTS](https://github.com/JuanenRac/HYDRA-UMC-PRODUCTION-REPORTS)** — real OEE/availability calculation over DATALAKE history, with reproducible CSV export.
- **[HYDRA-UMC-TELEMETRY-COLLECTOR](https://github.com/JuanenRac/HYDRA-UMC-TELEMETRY-COLLECTOR)** — real CAN/WebSocket ingestion pipeline into DATALAKE, with sequence deduplication.

*Industrial Gateway*
- **[HYDRA-UMC-GATEWAY-INDUSTRIAL](https://github.com/JuanenRac/HYDRA-UMC-GATEWAY-INDUSTRIAL)** — integration hub relaying to industrial protocols, with a real command allowlist/backpressure layer.
- **[HYDRA-UMC-OPCUA-SERVER](https://github.com/JuanenRac/HYDRA-UMC-OPCUA-SERVER)** — real OPC-UA address space, verified with a real binary-protocol client session.
- **[HYDRA-UMC-MQTT-BROKER](https://github.com/JuanenRac/HYDRA-UMC-MQTT-BROKER)** — real MQTT broker with optional per-client authentication and topic ACLs.
- **[HYDRA-UMC-MTCONNECT-ADAPTER](https://github.com/JuanenRac/HYDRA-UMC-MTCONNECT-ADAPTER)** — real MTConnect `/probe` and `/current` XML endpoints with degraded-mode output.

*Complementary Tools*
- **[HYDRA-UMC-DASHBOARD-AI](https://github.com/JuanenRac/HYDRA-UMC-DASHBOARD-AI)** — Smart Summaries and Anomaly Highlighting panels over DATALAKE/ANOMALY-DETECTOR, with an honest statistical fallback.
- **[HYDRA-UMC-TOOL-CLI](https://github.com/JuanenRac/HYDRA-UMC-TOOL-CLI)** — fleet CLI with a real, stable exit-code contract, a genuine live client of HYDRA-UMC-SERVER's own API.
- **[HYDRA-UMC-WATCH](https://github.com/JuanenRac/HYDRA-UMC-WATCH)** — WearOS companion app with real haptic alerts and a paired-phone voice relay.
- **[HYDRA-UMC-CONNECTOR-HUB](https://github.com/JuanenRac/HYDRA-UMC-CONNECTOR-HUB)** — external adapter capability catalog, GET-only by design.
- **[URTC-SMART-RACK](https://github.com/JuanenRac/URTC-SMART-RACK)** — firmware for a board-mounting rack with real tool-ID decoding and Smart Idle pre-heating logic.
- **[URTC-VISION-TOOL](https://github.com/JuanenRac/URTC-VISION-TOOL)** — firmware plus a real Python vision companion for a thermal/RGB inspection tool head.

---

## 📚 Documentation & Community

- **[docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md)** — every subcommand, its flags, and the exit-code contract.
- **[docs/CONFIG_SCHEMA.md](docs/CONFIG_SCHEMA.md)** — the real JSON shape of `HostProfile`/`ToolchainPolicy`/`TaskPolicy`.
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — purpose, the two working modes, initial scope, and disk layout.
- **[docs/OPS_INTEGRATION.md](docs/OPS_INTEGRATION.md)** — the full 17-relationship map and state-ownership table.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — tech stack and coding guidelines for a pull request.
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — the standards of behavior expected in this community.
- **[SECURITY.md](SECURITY.md)** — how to report a vulnerability, and this project's own real security focus areas.
- **[SUPPORT.md](SUPPORT.md)** — where to ask questions and report bugs.

## 👤 AUTHOR
**JuanenRac** (Electro Hobby 3D)
📧 electrohobby3d@gmail.com
📺 [youtube.com/@electrohobby3d](https://youtube.com/@electrohobby3d)

## 📜 LICENSE

GPL-3.0 (software) / CC BY-SA 4.0 (documentation) - see [LICENSE.md](LICENSE.md).
