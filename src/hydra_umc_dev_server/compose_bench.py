# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/compose_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Scenarios for the container bench (`bench/docker-compose.yml`): real containers of the swarm cell, driven over HTTP.

The compose file starts the orchestrator, the job dispatcher, the node healer and the state replicator as independent containers; this module is
the client that runs the scenarios against the orchestrator, the only service published on the host. It uses nothing but the loopback address and
the standard library, so the same code is tested here against a stand-in server and run in CI against the containers.

The data suite (`--suite data`, `bench/docker-compose.data.yml`) does the same against the data lake alone.

Each scenario is one named check with a PASS / FAIL line; the run fails at the end (never at the first failure), so one broken scenario does not hide
the ones after it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Callable

from .bench import Result, call

#: The statuses a missions request may answer when the dispatcher owns the robot choice and has no robot to give (a refusal, never a crash).
NO_ROBOT_STATUSES = (200, 409, 502, 503)

#: Rank of the answers that must never appear: the server failing on its own.
SERVER_FAULT = 500


class Cell:
    """The orchestrator of the cell: its address and its bearer token."""

    def __init__(self, base: str, token: str) -> None:
        self.base = base
        self.token = token

    def get(self, path: str, token: str | None = None) -> tuple[int, Any]:
        return call(self.base, "GET", path, token=self.token if token is None else token or None)

    def post(self, path: str, body: Any = None) -> tuple[int, Any]:
        return call(self.base, "POST", path, body if body is not None else {}, token=self.token)


def _mission_ids(listing: Any) -> list[str]:
    if isinstance(listing, dict):
        listing = listing.get("missions", [])
    return [str(item.get("id")) for item in listing if isinstance(item, dict)] if isinstance(listing, list) else []


def scenario_health(cell: Cell, run_id: str) -> str:
    status, body = cell.get("/health")
    assert status == 200, f"/health answered {status}: {body}"
    return "the orchestrator answers /health"


def scenario_closed_without_token(cell: Cell, run_id: str) -> str:
    status, _ = cell.get("/missions", token="")
    assert status == 401, f"/missions without a token answered {status}, expected 401"
    status, _ = cell.get("/missions", token="not-the-token")
    assert status in (401, 403), f"/missions with a wrong token answered {status}, expected 401 or 403"
    return "the mission API is closed without the right token"


def scenario_mission_lifecycle(cell: Cell, run_id: str) -> str:
    mission = f"bench-{run_id}-life"
    status, body = cell.post("/missions", {"id": mission})
    assert status == 200 and "Pending" in json.dumps(body), f"creating the mission answered {status}: {body}"
    status, listing = cell.get("/missions")
    assert status == 200 and mission in _mission_ids(listing), f"the mission is not listed: {listing}"
    status, body = cell.post(f"/missions/{mission}/cancel")
    assert status == 200 and "Cancel" in json.dumps(body), f"cancelling answered {status}: {body}"
    status, body = cell.post(f"/missions/{mission}/cancel")
    assert status == 200 and "AlreadyCancelled" in json.dumps(body), f"cancelling twice answered {status}: {body}"
    other = f"bench-{run_id}-early"
    cell.post("/missions", {"id": other})
    status, body = cell.post(f"/missions/{other}/start")
    assert status == 409 and "Pending" in json.dumps(body), f"starting a mission that was never dispatched answered {status}: {body}"
    cell.post(f"/missions/{other}/cancel")
    return "a mission is created, listed and cancelled (twice is harmless), and one that was never dispatched cannot be started"


def scenario_malformed_input(cell: Cell, run_id: str) -> str:
    status, _ = call(cell.base, "POST", "/missions", {"schema_version": "1.0", "operation_id": f"bench-{run_id}-sent", "status": "sent", "params": {}}, token=cell.token)
    assert status == 400, f"an operation already sent answered {status}, expected 400"
    status, _ = cell.post("/missions/does-not-exist/start")
    assert 400 <= status < SERVER_FAULT, f"starting an unknown mission answered {status}"
    return "a bad operation and an unknown mission are refused with a client error"


def scenario_dispatcher_through_orchestrator(cell: Cell, run_id: str) -> str:
    mission = f"bench-{run_id}-dispatch"
    cell.post("/missions", {"id": mission})
    status, body = cell.post(f"/missions/{mission}/auto-dispatch")
    assert status in NO_ROBOT_STATUSES, f"auto-dispatch answered {status}: {body}"
    status, body = cell.get("/stats")
    assert status == 200, f"/stats answered {status}"
    cell.post(f"/missions/{mission}/cancel")
    return "the orchestrator reached the job dispatcher container (auto-dispatch answered a handled status)"


def scenario_recover_unknown_node(cell: Cell, run_id: str) -> str:
    status, body = cell.post("/nodes/bench-node-that-never-existed/recover")
    assert 100 <= status < SERVER_FAULT, f"recovering a node nobody uses answered {status}: {body}"
    return f"recovering a node with no mission is handled (status {status})"


SCENARIOS: list[tuple[str, Callable[[Cell, str], str]]] = [
    ("health", scenario_health),
    ("closed_without_token", scenario_closed_without_token),
    ("mission_lifecycle", scenario_mission_lifecycle),
    ("malformed_input", scenario_malformed_input),
    ("dispatcher_through_orchestrator", scenario_dispatcher_through_orchestrator),
    ("recover_unknown_node", scenario_recover_unknown_node),
]


def scenario_data_health(cell: Cell, run_id: str) -> str:
    status, body = cell.get("/health")
    assert status == 200, f"/health of the data lake answered {status}: {body}"
    return "the data lake answers /health"


def scenario_data_write_needs_token(cell: Cell, run_id: str) -> str:
    sample = {"sourceId": f"bench-{run_id}", "kind": "bench_probe", "timestamp": 1_700_000_000_000, "fields": {"value": 1.0}}
    status, body = call(cell.base, "POST", "/ingest", sample, token=None)
    assert status in (401, 403), f"writing without a token answered {status}, not a refusal: {body}"
    status, _ = call(cell.base, "POST", "/ingest", sample, token="not-the-token-0123456789abcdef")
    assert status in (401, 403), f"writing with a wrong token answered {status}, not a refusal"
    return f"the data lake refuses a write without the token or with a wrong one (status {status})"


def scenario_data_ingest_and_read_back(cell: Cell, run_id: str) -> str:
    source = f"bench-{run_id}"
    for index, value in enumerate((40.5, 41.5, 42.5)):
        sample = {"sourceId": source, "kind": "bench_probe", "timestamp": 1_700_000_000_000 + index * 1000, "fields": {"value": value}}
        status, body = cell.post("/ingest", sample)
        assert status in (200, 201), f"ingest answered {status}: {body}"
    status, body = cell.get(f"/query?sourceId={source}")
    assert status == 200, f"query answered {status}: {body}"
    samples = body.get("samples", body) if isinstance(body, dict) else body
    assert isinstance(samples, list) and len(samples) == 3, f"expected the 3 samples back, got {body}"
    return "three samples written with the token were read back"


def scenario_data_aggregate(cell: Cell, run_id: str) -> str:
    source = f"bench-agg-{run_id}"
    for index, value in enumerate((10.0, 20.0)):
        cell.post("/ingest", {"sourceId": source, "kind": "bench_agg", "timestamp": 1_700_000_000_000 + index * 1000, "fields": {"value": value}})
    status, body = cell.get("/aggregate?kind=bench_agg&field=value&bucketMs=60000&start=0&end=1800000000000&agg=avg")
    assert status == 200, f"aggregate answered {status}: {body}"
    assert "15" in json.dumps(body), f"the average of 10 and 20 should be 15, got {body}"
    return "the average of two stored samples is computed by the data lake"


def scenario_data_malformed_input(cell: Cell, run_id: str) -> str:
    for body in ({}, {"sourceId": ""}, {"sourceId": "x", "kind": "k", "timestamp": "yesterday", "fields": {"value": 1}}, ["not", "an", "object"]):
        status, reply = cell.post("/ingest", body)
        assert 400 <= status < SERVER_FAULT, f"a malformed sample {body!r} answered {status}: {reply}"
    return "malformed samples are refused with a client error, never a server fault"


#: The scenarios of the data bench (`bench/docker-compose.data.yml`): the data lake alone, over HTTP.
DATA_SCENARIOS: list[tuple[str, Callable[[Cell, str], str]]] = [
    ("data_health", scenario_data_health),
    ("data_write_needs_token", scenario_data_write_needs_token),
    ("data_ingest_and_read_back", scenario_data_ingest_and_read_back),
    ("data_aggregate", scenario_data_aggregate),
    ("data_malformed_input", scenario_data_malformed_input),
]

#: The suites the command line can run: name -> (scenarios, default address, default token variable).
SUITES: dict[str, tuple[list[tuple[str, Callable[[Cell, str], str]]], str, str]] = {
    "swarm": (SCENARIOS, "http://127.0.0.1:8114", "ORCHESTRATOR_TOKEN"),
    "data": (DATA_SCENARIOS, "http://127.0.0.1:8095", "DATALAKE_TOKEN"),
}


def wait_until_ready(cell: Cell, seconds: float) -> bool:
    """True once /health answers 200; the containers may need a while after `up`."""
    deadline = time.monotonic() + seconds
    while True:
        status, _ = cell.get("/health")
        if status == 200:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1.0)


def run(cell: Cell, run_id: str | None = None, only: list[str] | None = None, scenarios: list[tuple[str, Callable[[Cell, str], str]]] | None = None) -> list[Result]:
    """Every scenario of the suite (the swarm one by default), in order. A scenario that raises is a failure with the reason; the run goes on."""
    run_id = run_id or str(int(time.time()))
    results: list[Result] = []
    for name, scenario in (SCENARIOS if scenarios is None else scenarios):
        if only and name not in only:
            continue
        started = time.monotonic()
        try:
            detail = scenario(cell, run_id)
            status = "pass"
        except AssertionError as error:
            detail, status = str(error), "fail"
        except Exception as error:  # a broken scenario must not stop the others
            detail, status = f"{type(error).__name__}: {error}", "fail"
        results.append(Result(name, status, detail, round(time.monotonic() - started, 3)))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hydra-umc-dev-server-compose-bench", description="Scenarios against the orchestrator of the container bench.")
    parser.add_argument("--suite", choices=sorted(SUITES), default="swarm", help="which container bench to drive: the swarm cell or the data lake")
    parser.add_argument("--base-url", default=None, help="the published address of the service (default: the one of the suite)")
    parser.add_argument("--token-env", default=None, help="the environment variable that holds the token (default: the one of the suite)")
    parser.add_argument("--wait", type=float, default=120.0, help="seconds to wait for /health before the scenarios start (0: do not wait)")
    parser.add_argument("--only", action="append", help="run only this scenario (repeatable)")
    arguments = parser.parse_args(argv)
    scenarios, default_url, default_token_env = SUITES[arguments.suite]
    base_url = arguments.base_url or default_url
    token_env = arguments.token_env or default_token_env
    token = os.environ.get(token_env, "")
    if not token:
        print(f"COMPOSE_BENCH=FAIL the variable {token_env} is empty", file=sys.stderr)
        return 2
    cell = Cell(base_url, token)
    if arguments.wait > 0 and not wait_until_ready(cell, arguments.wait):
        print(f"COMPOSE_BENCH=FAIL the service did not answer /health within {arguments.wait:g} s")
        return 1
    results = run(cell, only=arguments.only, scenarios=scenarios)
    for result in results:
        print(f"{result.status.upper():4} {result.name}: {result.detail}")
    failed = [r.name for r in results if r.status != "pass"]
    print(f"COMPOSE_BENCH={'FAIL' if failed else 'PASS'} scenarios={len(results)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
