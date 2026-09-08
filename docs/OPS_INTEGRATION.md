<!-- =============================================================================
HYDRA-UMC-DEV-SERVER - docs/OPS_INTEGRATION.md
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Cross-project relationships (DS01)

This is a faithful translation of this project's own private development
plan's section 13.2.1 - a design target, not proof that any of these
endpoints, transports or automations exist yet. Real, already-available
contracts are used where they exist; a missing one is proposed before it
is coded, and current code/manifests are always checked at implementation
time rather than assumed from this document.

Legend: **Receives** - what the project/family hands to DEV-SERVER.
**Provides** - what DEV-SERVER hands back. **Boundary** - which
responsibility never changes owner.

Not every repository needs a network client to talk to DEV-SERVER. There
are three classes of relationship: coordination the repair loop actually
needs, optional integration, and development/testing of a repository with
no permanent operational connection. Incidents are always routed through
HYDRA-UMC-OPS-AGENT - this project does not invent 58 separate maintenance
protocols.

## A. Coordination the repair loop actually needs

**01. HYDRA-UMC-OPS-AGENT - maintenance coordinator.**
Receives: an incident-linked task, minimal sanitized evidence, the
affected revision, constraints, and the eventual verification/recovery
result. Provides: task accept/reject, progress, reproduction, a change
candidate, tests, identified artifacts and limitations. May itself open an
incident about DEV-SERVER through its own supervisor, outside the AI
runner. Boundary: OPS-AGENT keeps the incident, the approval policy and
its closure. The authorized human approves - neither a model nor a green
build self-authorizes.

**02. HYDRA-UMC-SDK - shared contracts.**
Receives: schemas, validators, compatibility data and policy that are
genuinely implemented; fixtures to test consumers against. Provides:
versioned proposals for task/result contracts, regression cases and
compatibility tests between node and server versions. Boundary: SDK
validators are never copied into each runner, and no second security
authority is invented. Changing a contract requires testing both
producers and consumers.

**03. HYDRA-UMC-UPDATER - consumer of the approved candidate.**
Receives: package requirements and, via OPS-AGENT, install status,
compatibility rejections, observed inventory and recovery results.
Provides: the artifact and its provenance metadata, hashes, platform,
revision, release version, dependencies and evidence; access limited to
the authorized candidate only. Boundary: delivery to the node goes through
OPS-AGENT and UPDATER's own real flow, never a scp followed by arbitrary
commands from the runner. A deployment failure never automatically turns
into another patch attempt - its cause is diagnosed first.

**04. JuanenRac / GitHub / CI - catalog and publication.**
Receives: the project catalog, public revisions and CI results, subject to
permissions and to the exact revision evaluated. Provides: a new project's
manifest once created, public documentation, reviewable candidates and
publishable evidence per authorization. Boundary: the catalog does not
decide approvals. Commit, push, release and roadmap changes are distinct
actions; no private internal notes ever accompany these exchanges.
Maturity never increases automatically just from compiling or being
registered in the catalog.

## B. Optional integrations; none block the basic development station

**05. HYDRA-UMC-OS and HYDRA-UMC-OS-REBUILDER - systems and distribution.**
Receives: supported profiles, service/image recipes, ARM64 requirements
and target-environment diagnosis obtained through authorized channels.
Provides: tested packages, proposed recipe changes and clean-install/
restore results; delegates image building to its own dedicated tool.
Boundary: the development station has a profile separate from the
operational node. No keys, workspaces, private repositories or task
history ever go into a public image. DEV-SERVER is never required to boot
or recover a CM5.

**06. HYDRA-UMC-COGNITIVE-NODE, HYDRA-UMC-VOICE-UI,
HYDRA-UMC-SEMANTIC-PLANNER and HYDRA-UMC-DOCS-QA - interaction, hypotheses
and technical context.**
Receives: structured requests, hypotheses and authorized documentation
fragments, with source and version, through OPS-AGENT when maintenance-
related. Provides: verifiable status, an explanation of changes and a
result fit to display or speak; reviewed documentation for future queries.
Boundary: a dictated instruction, a hypothesis, or retrieved text are
never shell permission nor patch approval. Consent stays tied to exact
identity and content. Hailo/local-model availability never gates a manual
task.

**07. HYDRA-UMC-TELEMETRY-COLLECTOR, HYDRA-UMC-DATALAKE,
HYDRA-UMC-ANOMALY-DETECTOR and HYDRA-UMC-PRODUCTION-REPORTS - evidence.**
Receives: telemetry windows, anomalies and reports relevant to
reproducing an incident, each with unit, timestamp, node and correlation -
never unbounded dumps. Provides: sanitized development logs, test
measurements and the relation between an incident, a candidate and its
result, for storage or presentation. Boundary: an anomaly is an
observation, not a repair order. The server's own queue holds its own
work state - it does not replace DATALAKE's history. Client/camera data is
never reused for training without specific permission.

**08. HYDRA-UMC-SERVER, HYDRA-UMC-STUDIO, HYDRA-UMC-DASHBOARD-AI,
HYDRA-UMC-SUITE and HYDRA-UMC-TOOL-CLI - user interfaces and access.**
Receives: explicit tasks and authenticated queries from interfaces that
adopt the integration; contracts, examples and reproducible errors for
their own development. Provides: status and results referenced by ID,
diffs and revision links; test packages of these applications through the
normal circuit. Boundary: reuse an existing view when it already adds
value - do not build five independent task managers. Interfaces show
their owner's own status; they never infer success just because a
connection closed or a process no longer exists.

**09. HYDRA-UMC-ANDROID-CONTROL, HYDRA-UMC-IOS-CONTROL, HYDRA-UMC-WATCH and
HYDRA-UMC-DSI - user clients.**
Receives: voluntary failure reports and authenticated requests through
existing services; sources and fixtures to verify client contracts.
Provides: sanitized notifications and incident status; compatible builds
or work delegated to the right executor, with traceable results. Boundary:
the phone/watch/screen never reach the server's own filesystem nor receive
a provider secret. Each platform keeps its own real distribution
mechanism - having the source code does not guarantee Linux ARM64 can
build or install it.

**10. HYDRA-UMC-CONNECTOR-HUB - external adapter catalog.**
Receives: declared/validated adapter capabilities and constraints, to
pick tests and check incompatibilities without guessing a protocol.
Provides: manifest proposals and evidence tied to an adapter revision.
Boundary: the GET-only catalog is never turned into a remote executor - a
simulation's evidence is never published as certification of real
physical operation.

## C. Developed and tested repositories; no mandatory operational coupling

For this whole class, **Receives** includes sources, tests, recipes,
manifests and authorized reproducible cases. **Provides** includes
reviewable changes, regressions, synchronized documentation/translations,
and artifacts whenever the toolchain allows it. None of this means these
applications must call DEV-SERVER while running.

**11. HYDRA-UMC-TWIN, HYDRA-UMC-PHYSICS-REPLICA, HYDRA-UMC-HIL-BRIDGE,
HYDRA-UMC-EDITOR-URDF and HYDRA-UMC-SYNTHETIC-DATA-GEN.**
Receives: models, scenarios, limits, simulation results and test sets
whose provenance and conditions are recorded. Provides: validation runs,
coordinate/unit checks and before/after patch comparisons; a record of the
engine, configuration and evidence level used. Boundary: simulators run
the physics - DEV-SERVER only organizes their tests. Kinematics is never
duplicated, and synthetic data is never presented as a physical
measurement. An external x86 executor is optional for tools without
proven ARM64 support.

**12. HYDRA-UMC-ORCHESTRATOR, HYDRA-UMC-JOB-DISPATCHER,
HYDRA-UMC-SWARM-SYNC, HYDRA-UMC-NODE-HEALING, HYDRA-UMC-PATH-PLANNER-3D and
HYDRA-UMC-SAFETY-ZONES.**
Receives: traces, state machines, policies and coordination fixtures;
persistent incidents reach OPS-AGENT without starting repair loops on
their own. Provides: regressions for cancellation, retry, disconnection,
limits and scheduling; improvement candidates with proven consumer
compatibility. Boundary: the build queue is never mixed with robot
missions. NODE-HEALING keeps the operational recoveries it is authorized
for; DEV-SERVER never takes control of motion nor disables an interlock to
make a test easier.

**13. HYDRA-UMC-BRIDGE-ROS2, HYDRA-UMC-BRIDGE-OPENPNP,
HYDRA-UMC-BRIDGE-PRINTER3D, HYDRA-UMC-BRIDGE-CNC, HYDRA-UMC-BRIDGE-LASER,
HYDRA-UMC-BRIDGE-AMR, HYDRA-UMC-BRIDGE-DROIDS and HYDRA-UMC-BRIDGE-UAV.**
Receives: each external software's own contract, anonymized profiles and
authorized exchange captures, with no credentials and no physically
executable order by default. Provides: tests against emulators/isolated
processes, parser regressions, compatibility and per-bridge candidate
packages - never a new universal controller. Boundary: each bridge keeps
its own protocol and policies; a simulated machine response never proves
real-world operation.

**14. HYDRA-UMC-GATEWAY-INDUSTRIAL, HYDRA-UMC-OPCUA-SERVER,
HYDRA-UMC-MTCONNECT-ADAPTER and HYDRA-UMC-MQTT-BROKER.**
Receives: schemas, sanitized configuration and communication-failure
traces. Provides: tests for reconnection, permissions, malformed payloads,
duplicates and slow clients, plus fix candidates. Boundary: a transport is
used only when it satisfies its own contract and permissions - an MQTT
publish or an industrial tag write never authorizes running a shell
command. None of these protocols become a dependency of the server's own
first delivery.

**15. HYDRA-UMC-VISION-NODE, HYDRA-UMC-VISION-STREAMER,
HYDRA-UMC-VISUAL-SERVOING-API, HYDRA-UMC-DETECTION-HEF and
HYDRA-UMC-VLA-ENGINE.**
Receives: authorized visual fixtures, output contracts, model inventories
and pipeline traces; runtime/device versions when relevant. Provides:
pre/post-processing tests, stream management, timeouts and contracts;
explicit delegation of model tasks to a compatible platform. Boundary:
having Python on ARM64 never promises compiling a HEF, running Hailo
inference, or validating visual servoing - tests with substitutes remain
software-only.

**16. HYDRA-UMC and URTC - firmware and board contracts.**
Receives: sources, per-board configuration, protocol, limits and build
recipes. Provides: identified builds, firmware inventory/hashes, protocol
tests and a coordinated update proposal with the right tools. Boundary:
this never flashes, changes a bootloader, or activates an output
automatically. A compiled binary never certifies pinout, power, timing or
safety.

**17. URTC-FLASHER, URTC-TESTER, URTC-SMART-RACK, URTC-VISION-TOOL and
URTC-WEB-STUDIO - URTC family applications and equipment.**
Receives: diagnostic reports, device profiles and authorized test
results; firmware contracts to build coherent regressions. Provides:
candidate applications, fixtures and documented URTC compatibility; fix
proposals tied to the exact incident and equipment model. Boundary:
flasher/tester/rack and their controls keep their own role - a test,
motion or recording action that needs operational authorization is never
reassigned to DEV-SERVER. The URTC family keeps its own identity and
catalog grouping.

## Ownership map (13.2.2)

| Data or decision | Proposed owner |
| --- | --- |
| Incident, approval and closure | OPS-AGENT / authorized person |
| Task, workspace, lease and build | **DEV-SERVER** |
| Shared contract and compatibility | SDK |
| External capability catalog | CONNECTOR-HUB |
| Install/recovery status | UPDATER |
| Service recipe / image | OS / OS-REBUILDER, respectively |
| Operational mission | ORCHESTRATOR / JOB-DISPATCHER |
| Fact observed on a machine | The component/node that measures it |
| Published revision and CI result | The specific repository / CI run |

OPS-AGENT records the human approval - no capability to approve is ever
attributed to the AI. A transport ACK only ever proves receipt, never
installation or a physical result.

First useful station: Git, a remote environment and toolchain profiles.
Not every ecosystem service needs to be running. The repair loop adds
SDK + OPS-AGENT + UPDATER with a proven transport. Everything else
integrates on an as-needed basis. No cycle is created where booting/
repairing the node requires a healthy DEV-SERVER, which in turn requires
that same node to recover.

Each relationship records producer, consumer, schema version and
compatible ranges. Published version, source commit and artifact hash are
kept separately - they are never interchangeable identifiers. The shared
manifest is extended compatibly if it does not yet express a necessary
relationship, without inventing a field the dashboard or UPDATER could
misinterpret.

## Concrete bidirectional flows (13.2.3)

**Repair requested by the CM5**
Component -> evidence/hypothesis -> OPS-AGENT -> SDK task -> DEV-SERVER.
DEV-SERVER -> candidate + regression + artifact -> OPS-AGENT -> human
approval. OPS-AGENT -> approved candidate -> UPDATER -> isolated install
on the target node. Node/UPDATER -> observations -> OPS-AGENT -> incident
result -> DEV-SERVER. OPS-AGENT -> sanitized status -> the user's
interface/voice, if integrated. The final response reports whether the
candidate resolved the issue, failed, or is still unverified. This lets a
failed repair be linked back to its original task without automatically
starting an unbounded program-and-deploy loop.

**Improvement requested by the user, with no incident**
PC/editor -> authorized task -> DEV-SERVER -> workspace -> tests/
build-test. DEV-SERVER -> diffs and tests -> human review -> authorized
publication. Installation, if requested, enters the controlled-change
cycle - a fault is never invented to justify an improvement, and it is
never deployed the moment it compiles.

**Change affecting several repositories**
A proposed SDK change -> DEV-SERVER identifies consumers via the catalog
and proven dependencies -> pins revisions -> runs a contract matrix ->
per-repository candidates + a joint report -> review and publication
order. If compatibility breaks, a transition/rollback is established
before deployment. All repositories are never silently updated to `main`
while still under test.

**Failure of the development server itself**
An independent supervisor (not the runner) -> diagnosis/alarm -> the
operator or OPS-AGENT -> authorized recovery from a recipe and backup.
CM5 nodes stay operational per their own policy - they never wait on a
response from the very process that just failed.

## Tests that make these relationships count as implemented (13.2.4)

These criteria are folded into DS01, DS07, DS08 and DS10 - they do not
create a separate delivery list, and documenting a relationship never
marks it done by itself.

- Every shared contract has a tested producer and consumer, a direction,
  authentication, a size/time limit, and defined behavior for an
  incompatible version.
- A task and its incident keep the same IDs across a retry or restart; an
  old response never overwrites the state of a later run.
- A tampered package, a different destination, or an unapproved revision
  is rejected; accepting a request is never confused with a test or
  install actually succeeding.
- If DEV-SERVER disconnects, the node follows its own local policy and
  keeps its evidence; once the network returns, an already-confirmed
  operation is never repeated.
- An SDK contract change is verified against at least one previous
  consumer and the new candidate, or the incompatibility is declared
  explicitly.
- A missing optional flow produces "not available", never invented data.
- A relationship declared or tested with fixtures stays marked as a
  proposal or E1/E2 evidence - only a real test on the target counts as
  E3, and only a physical one as E4.
- Every implemented integration is documented in both affected projects,
  their README/translations where relevant, and their own private notes -
  never with a public link to internal-only documentation.
