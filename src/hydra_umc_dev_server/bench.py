# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A local bench that runs the services of the ecosystem against each other, without Docker and without a robot.

The chain it exercises is the one a goal follows before anything moves: the **planner** turns a goal into steps (a proposal that needs an
approval), the **safety zones** say whether the cell is clear, the **twin** signs the risk of the first movement, and only then does the
**dispatcher** get the job. A breach in the cell stops the chain before the certificate and before the job. With the **hardware-in-the-loop
bridge** and the twin's simulated robot, a certified command also moves a simulated joint over time, and the twin follows it as measured.

Each service is one of three things, chosen per service, and the report says which:

* **a URL you give** (`--planner URL`, `--safety URL`, `--dispatcher URL`, `--twin URL --twin-token T`): a service that is already running;
* **a service the bench starts** (`--real`): the planner and the safety zones as Python processes from the sibling checkouts, the twin and the
  bridge from their built binaries (`HYDRA_UMC_TWIN_BIN`, `HYDRA_UMC_HIL_BRIDGE_BIN`, or the usual `target/` folders), each on a free
  loopback port, with throw-away keys, tokens and folders that are deleted at the end;
* **a simulated service** (the default, and the fallback for what cannot be started): a small stand-in that speaks the documented contract of the
  real one. The stand-ins are what lets the bench run anywhere, in CI included; they prove the chain and the checks, not the real services.

Nothing here talks to anything but the loopback address, writes outside a throw-away folder, or needs a network.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

TIMEOUT_S = 5.0
LOOPBACK = "127.0.0.1"
TWIN_TOKEN = "bench-twin-token-0123456789"


# ---------------------------------------------------------------------------------------------------------------------------------
# a small client
# ---------------------------------------------------------------------------------------------------------------------------------
def call(base: str, method: str, path: str, body: Any = None, token: str | None = None) -> tuple[int, Any]:
    """One request; the answer is (status, parsed JSON or text). A service that cannot be reached is status 0 with the reason."""
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base.rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as reply:
            return reply.status, _parse(reply.read(), reply.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as error:
        return error.code, _parse(error.read(), error.headers.get("Content-Type", ""))
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        return 0, str(getattr(error, "reason", error))


def _parse(raw: bytes, content_type: str) -> Any:
    text = raw.decode("utf8", "replace")
    if "json" in content_type or text.lstrip().startswith(("{", "[")):
        try:
            return json.loads(text)
        except ValueError:
            pass
    return text


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


# ---------------------------------------------------------------------------------------------------------------------------------
# simulated services: the documented contract of each, nothing more
# ---------------------------------------------------------------------------------------------------------------------------------
Reply = tuple[int, Any]


class SimulatedService:
    """A stand-in server on a free loopback port. `handle(method, path, body, headers)` answers; every request is kept in `calls`."""

    def __init__(self, name: str, handle: Callable[[str, str, Any, dict[str, str]], Reply]) -> None:
        self.name = name
        self.calls: list[tuple[str, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # the bench prints its own report
                return

            def _serve(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = None
                outer.calls.append((method, self.path.split("?")[0]))
                status, payload = handle(method, self.path.split("?")[0], body, {k.lower(): v for k, v in self.headers.items()})
                data = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; version=0.0.4" if isinstance(payload, str) else "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802 - the name http.server asks for
                self._serve("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._serve("POST")

        self._server = ThreadingHTTPServer((LOOPBACK, 0), Handler)
        self.url = f"http://{LOOPBACK}:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> "SimulatedService":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _planner() -> SimulatedService:
    plans = {"assemble the pcb": [("MOVE_TO", {"location": "pickup"}), ("GRIP", {"target": "pcb"}), ("MOVE_TO", {"location": "assembly_point"}), ("RELEASE", {"target": "pcb"})]}

    def handle(method: str, path: str, body: Any, headers: dict[str, str]) -> Reply:
        if method == "GET" and path == "/stats":
            return 200, {"role": "simulated semantic planner"}
        if method == "POST" and path == "/decompose":
            goal = body.get("goal") if isinstance(body, dict) else None
            if not isinstance(goal, str) or not 0 < len(goal) <= 512:
                return 400, {"error": "goal must be text of at most 512 characters"}
            steps = plans.get(goal.strip().lower())
            if steps is None:
                return 200, {"matched": False, "goal": goal, "steps": [], "issues": ["no matching task template"], "valid": False}
            return 200, {"matched": True, "goal": goal, "steps": [{"primitive": p, "params": q} for p, q in steps], "issues": [], "valid": True, "executable": False, "requires_approval": True, "fingerprint": "sim-" + str(abs(hash(goal)) % 10**8)}
        return 404, {"error": "not found"}

    return SimulatedService("planner", handle)


def _inside(zone: dict[str, Any], position: dict[str, float]) -> bool:
    low, high = zone["min"], zone["max"]
    return all(low[axis] <= position[axis] <= high[axis] for axis in ("x", "y", "z"))


def _safety() -> SimulatedService:
    def handle(method: str, path: str, body: Any, headers: dict[str, str]) -> Reply:
        if method == "GET" and path == "/stats":
            return 200, {"role": "simulated safety zones"}
        if method == "POST" and path == "/check":
            if not isinstance(body, dict):
                return 400, {"error": "a JSON object is needed"}
            zones = body.get("zones") or {}
            if "calibration" not in zones:
                return 200, {"state": "inhibited", "reason": "no calibration metadata present - zone geometry cannot be trusted", "breaches": [], "estopRequests": [], "sdkSafetyState": {"state": "INHIBITED"}}
            observation = body.get("observation") or {}
            if not observation.get("active"):
                return 200, {"state": "inhibited", "reason": "no active observer", "breaches": [], "estopRequests": [], "sdkSafetyState": {"state": "INHIBITED"}}
            breaches = [
                {"zone_id": zone["id"], "level": zone["level"], "object_id": item["id"], "position": item["position"]}
                for zone in zones.get("zones", [])
                for item in (body.get("detections") or {}).get("objects", [])
                if zone["level"] == "danger" and _inside(zone, item["position"])
            ]
            if breaches:
                return 200, {"state": "danger", "reason": "objects breached a danger zone", "breaches": breaches, "estopRequests": [{"object_id": b["object_id"], "zone_id": b["zone_id"]} for b in breaches], "sdkSafetyState": {"state": "SAFE_STOP"}}
            return 200, {"state": "ready", "reason": "no breach, calibration valid", "breaches": [], "estopRequests": [], "sdkSafetyState": {"state": "READY"}}
        return 404, {"error": "not found"}

    return SimulatedService("safety", handle)


def _dispatcher() -> SimulatedService:
    jobs: dict[str, dict[str, Any]] = {}

    def handle(method: str, path: str, body: Any, headers: dict[str, str]) -> Reply:
        if method == "GET" and path == "/health":
            return 200, {"status": "ok", "persistenceHealthy": True, "lastPersistError": None}
        if method == "POST" and path == "/jobs":
            if not isinstance(body, dict) or not isinstance(body.get("id"), str) or not body["id"]:
                return 400, {"error": "id is required"}
            if body["id"] in jobs:
                return 409, {"error": "a job with this id exists"}
            jobs[body["id"]] = {"ID": body["id"], "Priority": int(body.get("priority", 0)), "RequiredTool": body.get("requiredTool", ""), "Status": "pending"}
            return 201, jobs[body["id"]]
        if method == "GET" and path.startswith("/jobs/"):
            job = jobs.get(path[len("/jobs/"):])
            return (200, job) if job else (404, {"error": "unknown job"})
        return 404, {"error": "not found"}

    return SimulatedService("dispatcher", handle)


def _twin() -> SimulatedService:
    counts = {"certificates": 0}

    def handle(method: str, path: str, body: Any, headers: dict[str, str]) -> Reply:
        if method == "GET" and path == "/stats":
            return 200, {"workspace": "simulated"}
        if method == "GET" and path == "/metrics":
            return 200, "# HELP hydra_umc_twin_up 1 while the service answers.\n# TYPE hydra_umc_twin_up gauge\nhydra_umc_twin_up 1\n# HELP hydra_umc_twin_certificates_signed_total Risk certificates signed.\n# TYPE hydra_umc_twin_certificates_signed_total counter\n" + f"hydra_umc_twin_certificates_signed_total {counts['certificates']}\n"
        if method == "POST" and path == "/interlock/certify":
            if headers.get("authorization") != f"Bearer {TWIN_TOKEN}":
                return 401, {"error": "a valid bearer token is required on the interlock routes"}
            if not isinstance(body, dict) or not isinstance(body.get("joint"), str):
                return 400, {"error": "malformed risk report"}
            counts["certificates"] += 1
            return 200, {"joint": body["joint"], "position": body.get("position"), "collision_imminent": bool(body.get("collision_imminent")), "distance_m": body.get("distance_m"), "issued_at_ms": int(time.time() * 1000), "nonce": f"sim{counts['certificates']:08d}", "key_id": "simulated", "signature": "0" * 128}
        return 404, {"error": "not found"}

    return SimulatedService("twin", handle)


SIMULATED: dict[str, Callable[[], SimulatedService]] = {"planner": _planner, "safety": _safety, "dispatcher": _dispatcher, "twin": _twin}


# ---------------------------------------------------------------------------------------------------------------------------------
# real services the bench starts
# ---------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Running:
    """What the bench knows about a service of the run: where it is, where it comes from and (if it started it) the process."""

    name: str
    url: str
    source: str   # "given", "real" or "simulated"
    process: subprocess.Popen[bytes] | None = None
    simulated: SimulatedService | None = None
    extra: dict[str, str] = field(default_factory=dict)


def workspace_of(explicit: str | None) -> Path:
    return Path(explicit).resolve() if explicit else Path(__file__).resolve().parents[3]


def _wait_up(url: str, path: str, process: subprocess.Popen[bytes] | None, seconds: float = 20.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if process is not None and process.poll() is not None:
            return False
        status, _ = call(url, "GET", path)
        if status in (200, 401):
            return True
        time.sleep(0.2)
    return False


def _python_service(workspace: Path, repo: str, module: str, port: int) -> subprocess.Popen[bytes] | None:
    source = workspace / repo / "src"
    if not source.is_dir():
        return None
    env = dict(os.environ, PYTHONPATH=str(source), PYTHONIOENCODING="utf-8")
    return subprocess.Popen([sys.executable, "-m", module, "serve", "--addr", LOOPBACK, "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _binary(workspace: Path, repo: str, executable: str, env_name: str) -> Path | None:
    suffix = ".exe" if os.name == "nt" else ""
    candidates: list[Path] = []
    if os.environ.get(env_name):
        candidates.append(Path(os.environ[env_name]))
    for root in filter(None, [os.environ.get("CARGO_TARGET_DIR")]):
        candidates += [Path(root) / "release" / (executable + suffix), Path(root) / "debug" / (executable + suffix)]
    for profile in ("release", "debug"):
        candidates.append(workspace / repo / "target" / profile / (executable + suffix))
    return next((path for path in candidates if path.is_file()), None)


SIM_MODEL = {"joints": [{"name": "shoulder", "lower": -2.0, "upper": 2.0, "max_velocity": 1.0, "max_acceleration": 5.0}, {"name": "elbow", "lower": -1.5, "upper": 1.5, "max_velocity": 2.0, "max_acceleration": 10.0}]}


class Bench:
    def __init__(self, *, real: bool = False, given: dict[str, str] | None = None, workspace: str | None = None, twin_token: str = TWIN_TOKEN) -> None:
        self.real = real
        self.given = given or {}
        self.workspace = workspace_of(workspace)
        self.twin_token = twin_token
        self.services: dict[str, Running] = {}
        self.scratch = Path(tempfile.mkdtemp(prefix="hydra-bench-"))
        self.twin_public_key = ""

    # -- start and stop ------------------------------------------------------------------------------------------------------------
    def __enter__(self) -> "Bench":
        for name in ("planner", "safety", "dispatcher", "twin"):
            self.services[name] = self._bring_up(name)
        self.services["bridge"] = self._bring_up_bridge()
        return self

    def __exit__(self, *exc: object) -> None:
        for running in self.services.values():
            if running.simulated is not None:
                running.simulated.stop()
            if running.process is not None:
                running.process.terminate()
                try:
                    running.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    running.process.kill()
        shutil.rmtree(self.scratch, ignore_errors=True)

    def _simulate(self, name: str) -> Running:
        service = SIMULATED[name]().start()
        return Running(name, service.url, "simulated", simulated=service)

    def _bring_up(self, name: str) -> Running:
        if name in self.given:
            return Running(name, self.given[name], "given")
        if self.real:
            started = self._start_real(name)
            if started is not None:
                return started
        return self._simulate(name)

    def _start_real(self, name: str) -> Running | None:
        port = free_port()
        url = f"http://{LOOPBACK}:{port}"
        if name == "planner":
            process = _python_service(self.workspace, "HYDRA-UMC-SEMANTIC-PLANNER", "hydra_umc_semantic_planner.main", port)
            health = "/stats"
        elif name == "safety":
            process = _python_service(self.workspace, "HYDRA-UMC-SAFETY-ZONES", "hydra_umc_safety_zones.main", port)
            health = "/stats"
        elif name == "twin":
            process, health = self._start_twin(port), "/stats"
        else:
            return None   # the dispatcher is a Go program: give its URL with --dispatcher
        if process is None:
            return None
        if not _wait_up(url, health, process):
            process.terminate()
            return None
        if name == "twin":
            # the twin signs only for a joint it has heard of lately: let the simulated robot report once
            call(url, "POST", "/sim/step", {"seconds": 0.01}, token=self.twin_token)
        return Running(name, url, "real", process=process)

    def _start_twin(self, port: int) -> subprocess.Popen[bytes] | None:
        binary = _binary(self.workspace, "HYDRA-UMC-TWIN", "hydra-umc-twin", "HYDRA_UMC_TWIN_BIN")
        if binary is None:
            return None
        key, token, model = self.scratch / "twin.key", self.scratch / "twin.token", self.scratch / "sim.json"
        if subprocess.run([str(binary), "keygen", "--key-file", str(key)], capture_output=True).returncode != 0:
            return None
        token.write_text(self.twin_token + "\n", encoding="utf8")
        model.write_text(json.dumps(SIM_MODEL), encoding="utf8")
        log = self.scratch / "twin.log"
        process = subprocess.Popen(
            [str(binary), "serve", "--addr", LOOPBACK, "--port", str(port), "--workspace", str(self.scratch), "--signing-key-file", str(key), "--certify-token-file", str(token), "--sim-config", str(model), "--require-fresh-state-ms", "60000"],
            stdout=subprocess.DEVNULL, stderr=log.open("wb"),
        )
        for _ in range(100):
            found = re.search(r"public key ([0-9a-f]{64})", log.read_text(encoding="utf8", errors="replace"))
            if found:
                self.twin_public_key = found.group(1)
                break
            time.sleep(0.1)
        return process

    def _bring_up_bridge(self) -> Running:
        """The bridge only exists as a real process (it is the thing that carries a certified command to the simulated robot)."""
        if "bridge" in self.given:
            return Running("bridge", self.given["bridge"], "given")
        twin = self.services["twin"]
        binary = _binary(self.workspace, "HYDRA-UMC-HIL-BRIDGE", "hydra-umc-hil-bridge", "HYDRA_UMC_HIL_BRIDGE_BIN")
        if not (self.real and twin.source == "real" and binary and self.twin_public_key):
            return Running("bridge", "", "unavailable")
        port = free_port()
        token = self.scratch / "twin.token"
        public = self.scratch / "twin.pub"
        public.write_text(self.twin_public_key + "\n", encoding="utf8")
        process = subprocess.Popen(
            [str(binary), "serve", "--addr", LOOPBACK, "--port", str(port), "--twin-url", twin.url, "--twin-state-token-file", str(token), "--twin-public-key-file", str(public), "--sim-robot"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        url = f"http://{LOOPBACK}:{port}"
        if not _wait_up(url, "/stats", process):
            process.terminate()
            return Running("bridge", "", "unavailable")
        return Running("bridge", url, "real", process=process)

    # -- the scenarios -------------------------------------------------------------------------------------------------------------
    def url(self, name: str) -> str:
        return self.services[name].url

    def run(self) -> list["Result"]:
        scenarios: list[Callable[[], Result]] = [self.health, self.chain_to_dispatch, self.breach_stops_the_chain, self.unapproved_plan_is_not_executable, self.metrics_are_prometheus_text, self.certified_command_moves_the_simulated_robot]
        results = []
        for scenario in scenarios:
            started = time.monotonic()
            try:
                result = scenario()
            except Exception as error:  # a scenario that crashes is a failed scenario, not a crashed bench
                result = Result(scenario.__name__, "fail", f"{type(error).__name__}: {error}")
            result.seconds = round(time.monotonic() - started, 3)
            results.append(result)
        return results

    HEALTH = {"planner": "/stats", "safety": "/stats", "dispatcher": "/health", "twin": "/stats"}

    def health(self) -> "Result":
        down = []
        for name, path in self.HEALTH.items():
            status, _ = call(self.url(name), "GET", path)
            if status != 200:
                down.append(f"{name} ({status})")
        sources = ", ".join(f"{name}={running.source}" for name, running in self.services.items())
        return Result("health", "fail" if down else "pass", f"down: {', '.join(down)}" if down else f"every service answers [{sources}]")

    def _zones(self) -> dict[str, Any]:
        return {"calibration": {"version": "bench", "source": "manual", "calibrated_at": time.strftime("%Y-%m-%d"), "max_age_days": 30}, "zones": [{"id": "cell", "level": "danger", "min": {"x": 0, "y": 0, "z": 0}, "max": {"x": 1, "y": 1, "z": 1}}]}

    def _observation(self) -> dict[str, Any]:
        return {"active": True, "observedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "maxAgeSeconds": 60, "error": None}

    def _check(self, position: dict[str, float]) -> Any:
        status, reply = call(self.url("safety"), "POST", "/check", {"zones": self._zones(), "detections": {"objects": [{"id": "thing", "position": position}]}, "observation": self._observation()})
        if status != 200:
            raise RuntimeError(f"safety answered {status}: {reply}")
        return reply

    def _plan(self) -> Any:
        status, plan = call(self.url("planner"), "POST", "/decompose", {"goal": "assemble the pcb"})
        if status != 200 or not plan.get("matched"):
            raise RuntimeError(f"planner answered {status}: {plan}")
        return plan

    def _certify(self, joint: str, position: float) -> tuple[int, Any]:
        """Ask the twin to sign the risk of a movement. A twin that refuses for lack of a recent state of the joint (409) is given one, once."""
        twin = self.url("twin")
        report = {"joint": joint, "position": position, "collision_imminent": False, "distance_m": 0.6}
        status, certificate = call(twin, "POST", "/interlock/certify", report, token=self.twin_token)
        if status == 409:
            call(twin, "POST", "/sim/step", {"seconds": 0.01}, token=self.twin_token)
            status, certificate = call(twin, "POST", "/interlock/certify", report, token=self.twin_token)
        return status, certificate

    def chain_to_dispatch(self) -> "Result":
        plan = self._plan()
        if not plan["valid"] or not plan["steps"]:
            return Result("chain_to_dispatch", "fail", "the plan is not valid or has no step")
        safety = self._check({"x": 5.0, "y": 5.0, "z": 0.0})
        if safety["state"] != "ready":
            return Result("chain_to_dispatch", "fail", f"the cell should be clear, safety says {safety['state']}: {safety['reason']}")
        status, certificate = self._certify("shoulder", 0.5)
        if status != 200 or not certificate.get("signature"):
            return Result("chain_to_dispatch", "fail", f"the twin answered {status}: {certificate}")
        job = f"bench-{int(time.time() * 1000)}"
        status, created = call(self.url("dispatcher"), "POST", "/jobs", {"id": job, "priority": 5, "requiredTool": "Gripper"})
        if status not in (200, 201):
            return Result("chain_to_dispatch", "fail", f"the dispatcher answered {status}: {created}")
        status, stored = call(self.url("dispatcher"), "GET", f"/jobs/{job}")
        if status != 200:
            return Result("chain_to_dispatch", "fail", f"the job is not there afterwards ({status})")
        return Result("chain_to_dispatch", "pass", f"{len(plan['steps'])} steps planned, cell clear, certificate signed, job {job} queued")

    def breach_stops_the_chain(self) -> "Result":
        self._plan()
        safety = self._check({"x": 0.5, "y": 0.5, "z": 0.5})
        if safety["state"] == "ready" or not safety.get("estopRequests"):
            return Result("breach_stops_the_chain", "fail", f"a person in the cell must stop the chain, safety says {safety['state']}")
        # the chain ends here: the bench asks for no certificate and submits no job, and checks nothing was queued under this name
        status, _ = call(self.url("dispatcher"), "GET", "/jobs/bench-breach")
        if status == 200:
            return Result("breach_stops_the_chain", "fail", "a job exists for a run that was stopped")
        return Result("breach_stops_the_chain", "pass", f"safety says {safety['state']} with {len(safety['estopRequests'])} stop request(s); nothing certified or queued")

    def unapproved_plan_is_not_executable(self) -> "Result":
        plan = self._plan()
        if plan.get("executable") is not False or plan.get("requires_approval") is not True:
            return Result("unapproved_plan_is_not_executable", "fail", "a plan must be a proposal that needs approval until someone approves it")
        return Result("unapproved_plan_is_not_executable", "pass", "the plan is a proposal (executable: false, requires_approval: true)")

    def metrics_are_prometheus_text(self) -> "Result":
        checked = []
        for name in ("twin", "bridge"):
            running = self.services.get(name)
            if running is None or not running.url:
                continue
            token = self.twin_token if name == "twin" else None
            status, text = call(running.url, "GET", "/metrics", token=token)
            if status == 404:
                continue   # a service without the route (an older build, or a service that has none yet)
            problem = prometheus_problem(text) if status == 200 and isinstance(text, str) else f"status {status}"
            if problem:
                return Result("metrics_are_prometheus_text", "fail", f"{name}: {problem}")
            checked.append(name)
        if not checked:
            return Result("metrics_are_prometheus_text", "skip", "no service of this run offers /metrics")
        return Result("metrics_are_prometheus_text", "pass", f"valid Prometheus text from {', '.join(checked)}")

    def certified_command_moves_the_simulated_robot(self) -> "Result":
        bridge, twin = self.services["bridge"], self.services["twin"]
        if bridge.source == "unavailable" or twin.source == "simulated":
            return Result("certified_command_moves_the_simulated_robot", "skip", "needs the real twin and the real bridge (--real with both binaries built)")
        status, certificate = self._certify("shoulder", 1.0)
        if status != 200:
            return Result("certified_command_moves_the_simulated_robot", "fail", f"the twin did not sign: {status} {certificate}")
        order = {"mode": "real", "joint": "shoulder", "position": 1.0, "certificate": certificate, "issued_at_ms": int(time.time() * 1000), "valid_for_ms": 5000, "seq": 1}
        status, routed = call(bridge.url, "POST", "/route", order)
        if status != 200 or "SentReal" not in json.dumps(routed):
            return Result("certified_command_moves_the_simulated_robot", "fail", f"the bridge answered {status}: {routed}")
        status, partway = call(twin.url, "POST", "/sim/step", {"seconds": 0.1}, token=self.twin_token)
        shoulder = next(j for j in partway["joints"] if j["joint"] == "shoulder")
        if not 0.0 < shoulder["position"] < 1.0 or not shoulder["moving"]:
            return Result("certified_command_moves_the_simulated_robot", "fail", f"after 100 ms the joint should be on its way: {shoulder}")
        status, done = call(twin.url, "POST", "/sim/step", {"seconds": 5}, token=self.twin_token)
        shoulder = next(j for j in done["joints"] if j["joint"] == "shoulder")
        status, followed = call(twin.url, "GET", "/interlock/state", token=self.twin_token)
        seen = next((j for j in followed["joints"] if j["joint"] == "shoulder"), None)
        if shoulder["position"] != 1.0 or shoulder["moving"] or not seen or seen["source"] != "measured":
            return Result("certified_command_moves_the_simulated_robot", "fail", f"the joint did not arrive or the twin does not follow it: {shoulder} {seen}")
        return Result("certified_command_moves_the_simulated_robot", "pass", "a certified command moved the simulated joint over time and the twin follows it as measured")


@dataclass
class Result:
    name: str
    status: str   # "pass", "fail" or "skip"
    detail: str
    seconds: float = 0.0


def prometheus_problem(text: str) -> str:
    """What is wrong with a Prometheus exposition text (None: nothing). Checks the shape the format asks for."""
    declared: set[str] = set()
    series = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("# TYPE "):
            parts = line.split()
            if len(parts) != 4 or parts[3] not in ("counter", "gauge", "histogram", "summary", "untyped"):
                return f"bad TYPE line: {line}"
            declared.add(parts[2])
        elif line.startswith("# HELP "):
            if len(line.split()) < 4:
                return f"bad HELP line: {line}"
        elif line.startswith("#"):
            continue
        else:
            match = re.fullmatch(r"([A-Za-z_:][A-Za-z0-9_:]*)(\{[^}]*\})? (-?[0-9.]+(?:e[+-]?[0-9]+)?|NaN|[+-]Inf)", line)
            if not match:
                return f"bad series line: {line}"
            if match.group(1) not in declared:
                return f"{match.group(1)} is used before its TYPE line"
            series += 1
    return "" if series else "no series at all"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hydra-umc-bench", description="Run the services of the ecosystem against each other on this machine (no Docker, no robot).")
    parser.add_argument("--real", action="store_true", help="start the real planner, safety zones, twin and bridge that can be found next to this checkout")
    parser.add_argument("--workspace", help="the folder that holds the repositories (default: the parent of this one)")
    for name in ("planner", "safety", "dispatcher", "twin", "bridge"):
        parser.add_argument(f"--{name}", metavar="URL", help=f"use the {name} that is already running at this address")
    parser.add_argument("--twin-token", default=TWIN_TOKEN, help="the token of the twin's /interlock routes (for a twin you give)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    given = {name: getattr(args, name) for name in ("planner", "safety", "dispatcher", "twin", "bridge") if getattr(args, name)}
    with Bench(real=args.real, given=given, workspace=args.workspace, twin_token=args.twin_token) as bench:
        results = bench.run()
        sources = {name: running.source for name, running in bench.services.items()}
    if args.json:
        print(json.dumps({"services": sources, "results": [result.__dict__ for result in results]}, indent=2))
    else:
        print("services: " + ", ".join(f"{name}={source}" for name, source in sources.items()))
        for result in results:
            print(f"{result.status.upper():5} {result.name} ({result.seconds}s): {result.detail}")
    failed = [result for result in results if result.status == "fail"]
    print(f"BENCH={'FAIL' if failed else 'PASS'} {len(results) - len(failed)}/{len(results)} scenarios (skipped ones count as not failed)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
