# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_voice_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The scenarios of the voice bench, run against a small stand-in gateway on the loopback address.

The stand-in keeps the rules the scenarios look at (a bearer token on every route but /health, a limit on the body, a counted refusal, a confirmation
that is never given to a forged token); the real container is exercised by the manual workflow of this repository."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hydra_umc_dev_server import voice_bench
from hydra_umc_dev_server.voice_bench import SCENARIOS, Voice, main, run

TOKEN = "voice-token-0123456789ab"
LIMIT = 16 * 1024


class _Gateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, mode: str = "good") -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mode = mode
        self.turns = 0
        self.bad = 0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Handler(BaseHTTPRequestHandler):
    server: _Gateway

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, status: int, payload: object, text: bool = False) -> None:
        raw = (payload if text else json.dumps(payload)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; version=0.0.4" if text else "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        return self.server.mode == "open" or self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(200, {"product": "HYDRA-UMC-VOICE-UI", "version": "0.0.0", "authRequired": self.server.mode != "open"})
        elif self.path == "/metrics":
            if not self._authorized():
                self._send(401, {"error": "token"})
                return
            lines = [
                "# HELP hydra_umc_voice_ui_turns_total Turns.",
                "# TYPE hydra_umc_voice_ui_turns_total counter",
                f'hydra_umc_voice_ui_turns_total{{intent="none"}} {self.server.turns}',
                "# HELP hydra_umc_voice_ui_refused_total Refusals.",
                "# TYPE hydra_umc_voice_ui_refused_total counter",
                f'hydra_umc_voice_ui_refused_total{{reason="bad_request"}} {self.server.bad if self.server.mode != "uncounted" else 0}',
            ]
            self._send(200, "\n".join(lines) + "\n", text=True)
        else:
            self._send(404, {})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(401, {"error": "token"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length > LIMIT:
            self._send(413, {"error": "too large"})
            return
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/v1/voice/confirm":
            status = "confirmed" if self.server.mode == "forgeable" else "unknown"
            self._send(200, {"type": "confirmation_result", "status": status})
            return
        if not body.get("transcript"):
            self.server.bad += 1
            self._send(400, {"error": "transcript"})
            return
        self.server.turns += 1
        self._send(200, {"type": "assistant_reply", "requestId": body["requestId"]})


@pytest.fixture
def served():
    made: list[_Gateway] = []

    def make(mode: str = "good") -> Voice:
        gateway = _Gateway(mode)
        threading.Thread(target=gateway.serve_forever, daemon=True).start()
        made.append(gateway)
        return Voice(gateway.url, TOKEN)

    yield make
    for gateway in made:
        gateway.shutdown()
        gateway.server_close()


def _by_name(results):
    return {r.name: r for r in results}


def test_every_scenario_passes_against_a_gateway_that_keeps_its_rules(served) -> None:
    results = run(served())
    assert len(results) == len(SCENARIOS) == 8
    assert [r.name for r in results if r.status != "pass"] == []


def test_an_open_gateway_fails_the_scenarios_about_the_token(served) -> None:
    failed = {r.name for r in run(served("open")) if r.status == "fail"}
    assert {"voice_health", "voice_refuses_without_token", "voice_refuses_wrong_token", "voice_metrics_are_behind_the_token"} <= failed


def test_a_refusal_that_is_not_counted_is_a_failure(served) -> None:
    results = _by_name(run(served("uncounted")))
    assert results["voice_refuses_a_bad_turn"].status == "fail"
    assert "not counted" in results["voice_refuses_a_bad_turn"].detail


def test_a_forged_confirmation_that_is_confirmed_is_a_failure(served) -> None:
    results = _by_name(run(served("forgeable")))
    assert results["voice_forged_confirmation_confirms_nothing"].status == "fail"


def test_only_runs_the_scenarios_it_names(served) -> None:
    results = run(served(), only=["voice_health"])
    assert [r.name for r in results] == ["voice_health"]


def test_a_scenario_that_raises_is_a_failure_and_the_run_goes_on(served, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(voice: Voice, run_id: str) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(voice_bench, "SCENARIOS", [("broken", broken)] + list(SCENARIOS))
    results = run(served())
    assert results[0].status == "fail" and "RuntimeError: boom" in results[0].detail
    assert all(r.status == "pass" for r in results[1:])


def test_a_gateway_nobody_listens_on_is_a_failure_with_a_reason() -> None:
    results = run(Voice("http://127.0.0.1:9", TOKEN), only=["voice_health"])
    assert results[0].status == "fail"


def test_the_command_line_needs_the_token(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("VOICE_BENCH_TOKEN", raising=False)
    assert main(["--wait", "0"]) == 2
    assert "VOICE_BENCH_TOKEN" in capsys.readouterr().err


def test_the_command_line_passes_and_fails_with_the_gateway(served, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("VOICE_BENCH_TOKEN", TOKEN)
    assert main(["--url", served().base_url, "--wait", "0"]) == 0
    assert "VOICE_BENCH=PASS" in capsys.readouterr().out
    assert main(["--url", served("open").base_url, "--wait", "0"]) == 1
    assert "VOICE_BENCH=FAIL" in capsys.readouterr().out


def test_the_command_line_gives_up_when_the_gateway_never_answers(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("VOICE_BENCH_TOKEN", TOKEN)
    assert main(["--url", "http://127.0.0.1:9", "--wait", "0.2"]) == 1
    assert "did not answer /health" in capsys.readouterr().out
