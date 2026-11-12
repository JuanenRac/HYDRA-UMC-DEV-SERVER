# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/voice_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Scenarios for the voice bench (`bench/docker-compose.voice.yml`): the speech-to-action gateway as a real container, spoken to over HTTP.

The gateway starts the way a production start does (bound beyond loopback, so it refuses to run without a bearer token), so what is checked is the
boundary and not only the answers: nobody speaks to it without the token, a bad turn is refused and counted, a body over the limit is refused, a
forged confirmation token confirms nothing, and `/metrics` is behind the token.

Each scenario is one named check with a PASS / FAIL line; the run fails at the end (never at the first failure).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Callable

from .bench import Result, call, prometheus_problem

#: More than the largest body the gateway reads (16 KiB).
OVER_THE_LIMIT = 20 * 1024


class Voice:
    """The gateway of the bench: where it listens and the token the compose file configures."""

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url
        self.token = token

    def get(self, path: str, token: str | None = None) -> tuple[int, object]:
        return call(self.base_url, "GET", path, token=token)

    def post(self, path: str, body: object, token: str | None = None) -> tuple[int, object]:
        return call(self.base_url, "POST", path, body, token=token)

    def turn(self, run_id: str, transcript: str = "what is the status") -> dict:
        return {"type": "voice_turn", "requestId": f"bench-{run_id}", "transcript": transcript, "locale": "en"}

    def metrics(self) -> str:
        status, body = self.get("/metrics", token=self.token)
        assert status == 200, f"/metrics with the token answered {status}: {body}"
        return str(body)

    def total(self, prefix: str) -> float:
        """The sum of the series of /metrics whose name (with its labels) starts with [prefix]."""
        return sum(float(line.rsplit(" ", 1)[1]) for line in self.metrics().splitlines() if line.startswith(prefix))


def scenario_health(voice: Voice, run_id: str) -> str:
    status, body = voice.get("/health")
    assert status == 200 and isinstance(body, dict), f"/health answered {status}: {body}"
    assert body.get("product") == "HYDRA-UMC-VOICE-UI", f"/health names {body.get('product')!r}"
    assert body.get("authRequired") is True, "the gateway says it does not require a token"
    return f"/health answers without a token and says a token is required (version {body.get('version')})"


def scenario_refuses_without_token(voice: Voice, run_id: str) -> str:
    status, _ = voice.post("/v1/voice/turn", voice.turn(run_id))
    assert status == 401, f"a turn with no token answered {status}, not 401"
    return "a turn with no token is refused (401)"


def scenario_refuses_wrong_token(voice: Voice, run_id: str) -> str:
    status, _ = voice.post("/v1/voice/turn", voice.turn(run_id), token="this-is-not-the-token-0123456789")
    assert status == 401, f"a turn with a wrong token answered {status}, not 401"
    return "a turn with a wrong token is refused (401)"


def scenario_answers_a_turn(voice: Voice, run_id: str) -> str:
    before = voice.total("hydra_umc_voice_ui_turns_total")
    status, body = voice.post("/v1/voice/turn", voice.turn(run_id), token=voice.token)
    assert status == 200 and isinstance(body, dict), f"a turn with the token answered {status}: {body}"
    assert body.get("type") == "assistant_reply", f"the answer is a {body.get('type')!r}, not an assistant_reply"
    assert body.get("requestId") == f"bench-{run_id}", "the answer does not carry the request id of the turn"
    after = voice.total("hydra_umc_voice_ui_turns_total")
    assert after == before + 1, f"the turn is not counted (before {before:g}, after {after:g})"
    return "a turn with the token is answered with its request id and counted"


def scenario_refuses_a_bad_turn(voice: Voice, run_id: str) -> str:
    series = 'hydra_umc_voice_ui_refused_total{reason="bad_request"}'
    before = voice.total(series)
    status, _ = voice.post("/v1/voice/turn", {"type": "voice_turn", "requestId": f"bench-{run_id}", "locale": "en"}, token=voice.token)
    assert status == 400, f"a turn with no transcript answered {status}, not 400"
    after = voice.total(series)
    assert after > before, f"the refusal is not counted (before {before:g}, after {after:g})"
    return "a turn with no transcript is refused (400) and the refusal is counted"


def scenario_refuses_a_body_over_the_limit(voice: Voice, run_id: str) -> str:
    status, _ = voice.post("/v1/voice/turn", voice.turn(run_id, "a" * OVER_THE_LIMIT), token=voice.token)
    assert status == 413, f"a body over the limit answered {status}, not 413"
    return "a body over the limit is refused (413)"


def scenario_forged_confirmation_confirms_nothing(voice: Voice, run_id: str) -> str:
    status, body = voice.post("/v1/voice/confirm", {"confirmationToken": "forged.token.0123456789"}, token=voice.token)
    assert status == 200 and isinstance(body, dict), f"a confirmation answered {status}: {body}"
    assert body.get("status") != "confirmed", f"a forged confirmation token was confirmed: {body}"
    assert "signature" not in body, "a forged confirmation token got a signed result"
    return f"a forged confirmation token confirms nothing (status {body.get('status')})"


def scenario_metrics_are_behind_the_token(voice: Voice, run_id: str) -> str:
    status, _ = voice.get("/metrics")
    assert status == 401, f"/metrics with no token answered {status}, not 401"
    problem = prometheus_problem(voice.metrics())
    assert not problem, f"/metrics is not valid Prometheus text: {problem}"
    return "/metrics is refused without the token and is valid Prometheus text with it"


#: The scenarios of the voice bench, in order.
SCENARIOS: list[tuple[str, Callable[[Voice, str], str]]] = [
    ("voice_health", scenario_health),
    ("voice_refuses_without_token", scenario_refuses_without_token),
    ("voice_refuses_wrong_token", scenario_refuses_wrong_token),
    ("voice_answers_a_turn", scenario_answers_a_turn),
    ("voice_refuses_a_bad_turn", scenario_refuses_a_bad_turn),
    ("voice_refuses_a_body_over_the_limit", scenario_refuses_a_body_over_the_limit),
    ("voice_forged_confirmation_confirms_nothing", scenario_forged_confirmation_confirms_nothing),
    ("voice_metrics_are_behind_the_token", scenario_metrics_are_behind_the_token),
]


def wait_until_ready(voice: Voice, seconds: float) -> bool:
    """True once /health answers 200; the container may need a while after `up`."""
    deadline = time.monotonic() + seconds
    while True:
        status, _ = voice.get("/health")
        if status == 200:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1.0)


def run(voice: Voice, run_id: str | None = None, only: list[str] | None = None) -> list[Result]:
    """Every scenario, in order. A scenario that raises is a failure with the reason; the run goes on."""
    run_id = run_id or str(int(time.time()))
    results: list[Result] = []
    for name, scenario in SCENARIOS:
        if only and name not in only:
            continue
        started = time.monotonic()
        try:
            detail, status = scenario(voice, run_id), "pass"
        except AssertionError as error:
            detail, status = str(error), "fail"
        except Exception as error:  # a broken scenario must not stop the others
            detail, status = f"{type(error).__name__}: {error}", "fail"
        results.append(Result(name, status, detail, round(time.monotonic() - started, 3)))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hydra-umc-dev-server-voice-bench", description="Scenarios against the voice gateway of the voice bench.")
    parser.add_argument("--url", default="http://127.0.0.1:8091", help="where the gateway listens")
    parser.add_argument("--wait", type=float, default=60.0, help="seconds to wait for /health before the scenarios start (0: do not wait)")
    parser.add_argument("--only", action="append", help="run only this scenario (repeatable)")
    arguments = parser.parse_args(argv)
    token = os.environ.get("VOICE_BENCH_TOKEN", "")
    if not token:
        print("VOICE_BENCH=FAIL VOICE_BENCH_TOKEN must be set", file=sys.stderr)
        return 2
    voice = Voice(arguments.url, token)
    if arguments.wait > 0 and not wait_until_ready(voice, arguments.wait):
        print(f"VOICE_BENCH=FAIL the gateway did not answer /health within {arguments.wait:g} s")
        return 1
    results = run(voice, only=arguments.only)
    for result in results:
        print(f"{result.status.upper():4} {result.name}: {result.detail}")
    failed = [r.name for r in results if r.status != "pass"]
    print(f"VOICE_BENCH={'FAIL' if failed else 'PASS'} scenarios={len(results)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
