# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_compose_bench_data.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The scenarios of the data bench, run against a small stand-in of the data lake on the loopback address.

The stand-in speaks the part of the data lake contract the scenarios use (writes need the bearer token, reads are open, a sample needs a source, a kind,
a numeric timestamp and a mapping of fields); the real container is exercised by the manual workflow of this repository."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from hydra_umc_dev_server import compose_bench
from hydra_umc_dev_server.compose_bench import DATA_SCENARIOS, SCENARIOS, SUITES, Cell, main, run

TOKEN = "datalake-bench-token-0123456789"


class FakeDatalake(ThreadingHTTPServer):
    def __init__(self, mode: str = "good") -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mode = mode
        self.samples: list[dict] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    server: FakeDatalake

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, status: int, payload: object) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/health":
            return self._send(503 if self.server.mode == "down" else 200, {"status": "ok"})
        if url.path == "/query":
            wanted = query.get("sourceId", [""])[0]
            return self._send(200, {"samples": [s for s in self.server.samples if s["sourceId"] == wanted]})
        if url.path == "/aggregate":
            kind = query.get("kind", [""])[0]
            values = [s["fields"]["value"] for s in self.server.samples if s["kind"] == kind]
            return self._send(200, {"buckets": [{"avg": sum(values) / len(values)}] if values else []})
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if self.server.mode != "open-writes" and self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"error": "token"})
        try:
            body = json.loads(raw)
        except ValueError:
            return self._send(400, {"error": "json"})
        valid = (
            isinstance(body, dict)
            and body.get("sourceId")
            and body.get("kind")
            and isinstance(body.get("timestamp"), int)
            and isinstance(body.get("fields"), dict)
        )
        if not valid:
            return self._send(500 if self.server.mode == "crash-on-bad-input" else 400, {"error": "sample"})
        self.server.samples.append(body)
        self._send(200, {"ok": True})


@pytest.fixture
def fake():
    started: list[FakeDatalake] = []

    def make(mode: str = "good") -> FakeDatalake:
        server = FakeDatalake(mode)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started.append(server)
        return server

    yield make
    for server in started:
        server.shutdown()
        server.server_close()


def _results(server: FakeDatalake) -> dict[str, tuple[str, str]]:
    return {r.name: (r.status, r.detail) for r in run(Cell(server.url, TOKEN), "t1", scenarios=DATA_SCENARIOS)}


def test_every_data_scenario_passes_against_a_correct_data_lake(fake) -> None:
    results = _results(fake())
    assert set(results) == {name for name, _ in DATA_SCENARIOS}
    assert all(status == "pass" for status, _ in results.values()), results


def test_a_data_lake_that_accepts_writes_without_the_token_is_caught(fake) -> None:
    status, detail = _results(fake("open-writes"))["data_write_needs_token"]
    assert status == "fail" and "not a refusal" in detail


def test_a_server_fault_on_a_malformed_sample_is_caught(fake) -> None:
    status, detail = _results(fake("crash-on-bad-input"))["data_malformed_input"]
    assert status == "fail" and "500" in detail


def test_a_data_lake_that_is_down_fails_the_health_scenario_only_for_health(fake) -> None:
    results = _results(fake("down"))
    assert results["data_health"][0] == "fail"
    assert results["data_ingest_and_read_back"][0] == "pass"


def test_the_two_suites_have_different_scenarios_and_defaults() -> None:
    assert set(SUITES) == {"swarm", "data"}
    assert not {n for n, _ in SCENARIOS} & {n for n, _ in DATA_SCENARIOS}
    assert SUITES["data"][1].endswith(":8095") and SUITES["data"][2] == "DATALAKE_TOKEN"
    assert SUITES["swarm"][1].endswith(":8114") and SUITES["swarm"][2] == "ORCHESTRATOR_TOKEN"


def test_main_runs_the_data_suite_with_its_own_token_variable(fake, monkeypatch, capsys) -> None:
    server = fake()
    monkeypatch.setenv("DATALAKE_TOKEN", TOKEN)
    monkeypatch.delenv("ORCHESTRATOR_TOKEN", raising=False)
    assert main(["--suite", "data", "--base-url", server.url, "--wait", "5"]) == 0
    out = capsys.readouterr().out
    assert f"COMPOSE_BENCH=PASS scenarios={len(DATA_SCENARIOS)} failed=0" in out


def test_main_names_the_failed_data_scenario(fake, monkeypatch, capsys) -> None:
    server = fake("open-writes")
    monkeypatch.setenv("DATALAKE_TOKEN", TOKEN)
    assert main(["--suite", "data", "--base-url", server.url, "--wait", "5"]) == 1
    assert "FAIL data_write_needs_token" in capsys.readouterr().out


def test_main_refuses_an_empty_data_token(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DATALAKE_TOKEN", raising=False)
    assert main(["--suite", "data", "--wait", "0"]) == 2
    assert "DATALAKE_TOKEN" in capsys.readouterr().err


def test_only_limits_the_data_suite(fake, monkeypatch, capsys) -> None:
    server = fake()
    monkeypatch.setenv("DATALAKE_TOKEN", TOKEN)
    assert main(["--suite", "data", "--base-url", server.url, "--wait", "0", "--only", "data_health"]) == 0
    assert "scenarios=1 failed=0" in capsys.readouterr().out


def test_an_unknown_suite_is_refused() -> None:
    with pytest.raises(SystemExit):
        main(["--suite", "nothing"])


def test_the_swarm_suite_stays_the_default(fake, monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_TOKEN", TOKEN)
    assert compose_bench.SUITES["swarm"][0] is compose_bench.SCENARIOS
    # nothing listens on the default swarm address: the run ends without a verdict from the scenarios
    assert main(["--wait", "0", "--only", "no_such_scenario"]) == 0
