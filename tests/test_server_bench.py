# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_server_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The scenarios of the server bench, run against a small stand-in server on the loopback address.

The stand-in keeps the rules the scenarios look at (a token on every route but the version, a login that gives a token only to the right password, a
settings tree with controllers, a refusal for a robot that does not exist); the real container is exercised by the workflow of this repository."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hydra_umc_dev_server import server_bench
from hydra_umc_dev_server.server_bench import SCENARIOS, Server, main, run

USER = "bench-admin"
PASSWORD = "bench-password-0123456789"
TOKEN = "a.valid.token"


class _Stand(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, mode: str = "good") -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mode = mode

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    server: _Stand

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, status: int, payload: object) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        return self.server.mode == "open" or self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/hydra-info":
            self._send(200, {"product": "HYDRA-UMC-SERVER"})
        elif not self._authorized():
            self._send(401, {"error": "No token provided"})
        elif self.path == "/api/settings":
            self._send(200, {} if self.server.mode == "empty" else {"controllers": []})
        else:
            self._send(200, [])

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/login":
            ok = body.get("username") == USER and (body.get("password") == PASSWORD or self.server.mode == "lax")
            self._send(200, {"token": TOKEN}) if ok else self._send(401, {"error": "bad credentials"})
        elif not self._authorized():
            self._send(401, {"error": "No token provided"})
        elif self.path.startswith("/api/robot/"):
            self._send(500 if self.server.mode == "crashes" else 404, {"error": "no such robot"})
        else:
            self._send(200, {})


@pytest.fixture
def served():
    made: list[_Stand] = []

    def make(mode: str = "good") -> Server:
        stand = _Stand(mode)
        threading.Thread(target=stand.serve_forever, daemon=True).start()
        made.append(stand)
        return Server(stand.url, USER, PASSWORD)

    yield make
    for stand in made:
        stand.shutdown()
        stand.server_close()


def _by_name(results):
    return {r.name: r for r in results}


def test_every_scenario_passes_against_a_server_that_keeps_its_rules(served) -> None:
    results = run(served())
    assert len(results) == len(SCENARIOS) == 7
    assert [r.name for r in results if r.status != "pass"] == []


def test_an_open_server_fails_the_scenarios_about_the_token(served) -> None:
    failed = {r.name for r in run(served("open")) if r.status == "fail"}
    assert {"server_refuses_without_a_token", "server_refuses_a_wrong_token"} <= failed


def test_a_login_that_lets_a_wrong_password_in_is_a_failure(served) -> None:
    results = _by_name(run(served("lax")))
    assert results["server_refuses_a_wrong_password"].status == "fail"


def test_settings_without_controllers_are_a_failure(served) -> None:
    results = _by_name(run(served("empty")))
    assert results["server_administrator_reads_the_settings"].status == "fail"
    assert "controllers" in results["server_administrator_reads_the_settings"].detail


def test_a_server_that_fails_on_an_unknown_robot_is_a_failure(served) -> None:
    results = _by_name(run(served("crashes")))
    assert results["server_command_to_a_robot_that_does_not_exist"].status == "fail"


def test_only_runs_the_scenarios_it_names(served) -> None:
    assert [r.name for r in run(served(), only=["server_info_without_a_token"])] == ["server_info_without_a_token"]


def test_a_scenario_that_raises_is_a_failure_and_the_run_goes_on(served, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(server: Server, run_id: str) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(server_bench, "SCENARIOS", [("broken", broken)] + list(SCENARIOS))
    results = run(served())
    assert results[0].status == "fail" and "RuntimeError: boom" in results[0].detail
    assert all(r.status == "pass" for r in results[1:])


def test_a_server_nobody_listens_on_is_a_failure_with_a_reason() -> None:
    results = run(Server("http://127.0.0.1:9", USER, PASSWORD), only=["server_info_without_a_token"])
    assert results[0].status == "fail"


def test_the_command_line_needs_the_password(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("SERVER_BENCH_ADMIN_PASSWORD", raising=False)
    assert main(["--wait", "0"]) == 2
    assert "SERVER_BENCH_ADMIN_PASSWORD" in capsys.readouterr().err


def test_the_command_line_passes_and_fails_with_the_server(served, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("SERVER_BENCH_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("SERVER_BENCH_ADMIN_USERNAME", USER)
    assert main(["--url", served().base_url, "--wait", "0"]) == 0
    assert "SERVER_BENCH=PASS" in capsys.readouterr().out
    assert main(["--url", served("open").base_url, "--wait", "0"]) == 1
    assert "SERVER_BENCH=FAIL" in capsys.readouterr().out


def test_the_command_line_gives_up_when_the_server_never_answers(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("SERVER_BENCH_ADMIN_PASSWORD", PASSWORD)
    assert main(["--url", "http://127.0.0.1:9", "--wait", "0.2"]) == 1
    assert "did not answer /api/hydra-info" in capsys.readouterr().out


def test_the_compose_file_asks_for_the_secrets_and_keeps_them_out_of_the_file() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "bench" / "docker-compose.server.yml").read_text(encoding="utf-8")
    assert "SERVER_BENCH_JWT_SECRET:?" in text and "SERVER_BENCH_ADMIN_PASSWORD:?" in text
    assert "127.0.0.1:18200:3000" in text, "published on the loopback interface only"
