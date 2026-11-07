# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_compose_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The scenarios of the container bench, run against a small stand-in of the orchestrator on the loopback address.

The stand-in speaks the part of the orchestrator contract the scenarios use (bearer token, missions that start Pending and can be cancelled once,
409 on an invalid transition, 400 on an operation already sent); the real containers are exercised by the manual workflow of this repository."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hydra_umc_dev_server import compose_bench
from hydra_umc_dev_server.bench import free_port
from hydra_umc_dev_server.compose_bench import Cell, SCENARIOS, main, run, wait_until_ready

TOKEN = "bench-token-0123456789abcdef"


class FakeOrchestrator(ThreadingHTTPServer):
    def __init__(self, mode: str = "good") -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mode = mode
        self.missions: dict[str, str] = {}

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    server: FakeOrchestrator

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, status: int, payload: object) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        if self.server.mode == "open":
            return True
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    def do_GET(self) -> None:
        if self.server.mode == "down" and self.path == "/health":
            return self._send(503, {"error": "starting"})
        if not self._authorized():
            return self._send(401, {"error": "token"})
        if self.path == "/health":
            return self._send(200, {"status": "ok"})
        if self.path == "/missions":
            return self._send(200, [{"id": name, "state": state} for name, state in self.server.missions.items()])
        if self.path == "/stats":
            return self._send(500 if self.server.mode == "broken-stats" else 200, {"missions": len(self.server.missions)})
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return self._send(401, {"error": "token"})
        body = self._body()
        if self.path == "/missions":
            if body.get("status") == "sent":
                return self._send(400, {"error": "already sent"})
            name = body.get("id") or body.get("operation_id")
            self.server.missions[name] = "Pending"
            return self._send(200, {"id": name, "state": "Pending"})
        parts = self.path.strip("/").split("/")
        if parts[0] == "missions" and len(parts) == 3:
            name, verb = parts[1], parts[2]
            if name not in self.server.missions:
                return self._send(404, {"error": "unknown"})
            if verb == "cancel":
                if self.server.missions[name] == "Cancelled":
                    return self._send(200, {"id": name, "state": "AlreadyCancelled"})
                self.server.missions[name] = "Cancelled"
                return self._send(200, {"id": name, "state": "Cancelled"})
            if verb == "start":
                return self._send(409, {"id": name, "state": self.server.missions[name], "error": "invalid transition"})
            if verb == "auto-dispatch":
                return self._send(503 if self.server.mode != "dispatch-crash" else 500, {"error": "no robot"})
        if parts[0] == "nodes" and len(parts) == 3 and parts[2] == "recover":
            return self._send(200, {"requeued": []})
        self._send(404, {"error": "not found"})


@pytest.fixture
def fake():
    created: list[FakeOrchestrator] = []

    def make(mode: str = "good") -> FakeOrchestrator:
        server = FakeOrchestrator(mode)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        created.append(server)
        return server

    yield make
    for server in created:
        server.shutdown()
        server.server_close()


def _by_name(results):
    return {result.name: result for result in results}


def test_every_scenario_passes_against_a_well_behaved_orchestrator(fake) -> None:
    server = fake()
    results = run(Cell(server.url, TOKEN), run_id="t1")
    assert [r.name for r in results] == [name for name, _ in SCENARIOS]
    assert [r.status for r in results] == ["pass"] * len(SCENARIOS), [(r.name, r.detail) for r in results if r.status != "pass"]


def test_the_scenario_names_are_unique_and_documented() -> None:
    names = [name for name, _ in SCENARIOS]
    assert len(names) == len(set(names))
    for name, scenario in SCENARIOS:
        assert scenario.__doc__ is None or isinstance(scenario.__doc__, str)
        assert scenario.__name__ == f"scenario_{name}"


def test_an_open_api_fails_the_closed_without_token_scenario_only(fake) -> None:
    server = fake("open")
    results = _by_name(run(Cell(server.url, TOKEN), run_id="t2"))
    assert results["closed_without_token"].status == "fail"
    assert "expected 401" in results["closed_without_token"].detail
    assert results["health"].status == "pass" and results["mission_lifecycle"].status == "pass"


def test_a_server_fault_in_the_dispatcher_path_fails_that_scenario_and_the_run_goes_on(fake) -> None:
    server = fake("dispatch-crash")
    results = _by_name(run(Cell(server.url, TOKEN), run_id="t3"))
    assert results["dispatcher_through_orchestrator"].status == "fail"
    assert "500" in results["dispatcher_through_orchestrator"].detail
    assert results["recover_unknown_node"].status == "pass"


def test_a_failing_stats_endpoint_is_reported_with_its_status(fake) -> None:
    server = fake("broken-stats")
    results = _by_name(run(Cell(server.url, TOKEN), run_id="t4"))
    assert results["dispatcher_through_orchestrator"].status == "fail"
    assert "/stats answered 500" in results["dispatcher_through_orchestrator"].detail


def test_a_wrong_token_makes_the_authenticated_scenarios_fail_but_not_the_closed_one(fake) -> None:
    server = fake()
    results = _by_name(run(Cell(server.url, "a-different-token-0123456789"), run_id="t5"))
    assert results["health"].status == "fail"
    assert results["closed_without_token"].status == "pass"


def test_an_unreachable_orchestrator_fails_every_scenario_that_needs_it() -> None:
    results = run(Cell(f"http://127.0.0.1:{free_port()}", TOKEN), run_id="t6")
    assert {r.status for r in results} == {"fail"}
    assert _by_name(results)["health"].status == "fail"


def test_a_scenario_that_raises_is_a_failure_with_the_exception_name(fake, monkeypatch) -> None:
    def boom(cell, run_id):
        raise KeyError("x")

    monkeypatch.setattr(compose_bench, "SCENARIOS", [("boom", boom), *compose_bench.SCENARIOS[:1]])
    server = fake()
    results = run(Cell(server.url, TOKEN))
    assert results[0].status == "fail" and results[0].detail.startswith("KeyError")
    assert results[1].status == "pass"


def test_only_runs_the_named_scenarios(fake) -> None:
    server = fake()
    results = run(Cell(server.url, TOKEN), only=["health", "mission_lifecycle"])
    assert [r.name for r in results] == ["health", "mission_lifecycle"]


def test_two_runs_with_different_ids_do_not_collide(fake) -> None:
    server = fake()
    cell = Cell(server.url, TOKEN)
    assert all(r.status == "pass" for r in run(cell, run_id="a"))
    assert all(r.status == "pass" for r in run(cell, run_id="b"))
    assert len(server.missions) == 6


def test_wait_until_ready_returns_true_when_it_answers_and_false_when_it_never_does(fake) -> None:
    assert wait_until_ready(Cell(fake().url, TOKEN), 2.0) is True
    assert wait_until_ready(Cell(fake("down").url, TOKEN), 0.0) is False


def test_main_prints_one_line_per_scenario_and_the_verdict(fake, monkeypatch, capsys) -> None:
    server = fake()
    monkeypatch.setenv("ORCHESTRATOR_TOKEN", TOKEN)
    assert main(["--base-url", server.url, "--wait", "5"]) == 0
    out = capsys.readouterr().out
    assert out.count("PASS ") >= len(SCENARIOS)
    assert f"COMPOSE_BENCH=PASS scenarios={len(SCENARIOS)} failed=0" in out


def test_main_exits_nonzero_and_names_the_failure(fake, monkeypatch, capsys) -> None:
    server = fake("open")
    monkeypatch.setenv("ORCHESTRATOR_TOKEN", TOKEN)
    assert main(["--base-url", server.url, "--wait", "5"]) == 1
    out = capsys.readouterr().out
    assert "FAIL closed_without_token" in out and "COMPOSE_BENCH=FAIL" in out


def test_main_refuses_an_empty_token(monkeypatch, capsys) -> None:
    monkeypatch.delenv("ORCHESTRATOR_TOKEN", raising=False)
    assert main(["--wait", "0"]) == 2
    assert "COMPOSE_BENCH=FAIL" in capsys.readouterr().err


def test_main_reports_an_orchestrator_that_never_answers(fake, monkeypatch, capsys) -> None:
    server = fake("down")
    monkeypatch.setenv("ORCHESTRATOR_TOKEN", TOKEN)
    monkeypatch.setattr(compose_bench.time, "sleep", lambda s: None)
    assert main(["--base-url", server.url, "--wait", "0.05"]) == 1
    assert "did not answer /health" in capsys.readouterr().out


def test_main_accepts_another_token_variable(fake, monkeypatch) -> None:
    server = fake()
    monkeypatch.delenv("ORCHESTRATOR_TOKEN", raising=False)
    monkeypatch.setenv("BENCH_TOKEN", TOKEN)
    assert main(["--base-url", server.url, "--token-env", "BENCH_TOKEN", "--wait", "0", "--only", "health"]) == 0
