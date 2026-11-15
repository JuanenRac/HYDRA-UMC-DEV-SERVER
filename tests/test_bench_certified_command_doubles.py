# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_bench_certified_command_doubles.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The scenario of the bench that carries a certified command to the simulated robot needs the real twin and the real bridge binaries. Here the
two services are stand-ins that answer through a replaced `call`, so each way the scenario can end (pass, a twin that does not sign, a bridge that
refuses, a joint that is not on its way, a joint that never arrives) is checked without any binary (evidence: simulator)."""
from __future__ import annotations

from typing import Any

import pytest

from hydra_umc_dev_server import bench
from hydra_umc_dev_server.bench import Bench, Running

NAME = "certified_command_moves_the_simulated_robot"


class Stand:
    """Answers the requests of the scenario in the order they come; every field can be changed to make one step go wrong."""

    def __init__(self) -> None:
        self.certify = [(200, {"signature": "abc"})]
        self.route = (200, {"outcome": "SentReal"})
        self.partway = {"joint": "shoulder", "position": 0.4, "moving": True}
        self.done = {"joint": "shoulder", "position": 1.0, "moving": False}
        self.follow = {"joint": "shoulder", "source": "measured"}
        self.steps = 0
        self.certify_calls = 0

    def __call__(self, base: str, method: str, path: str, body: Any = None, token: str | None = None) -> tuple[int, Any]:
        if path == "/interlock/certify":
            answer = self.certify[min(self.certify_calls, len(self.certify) - 1)]
            self.certify_calls += 1
            return answer
        if path == "/route":
            return self.route
        if path == "/sim/step":
            self.steps += 1
            if body == {"seconds": 0.1}:
                return 200, {"joints": [self.partway]}
            return 200, {"joints": [self.done]}
        if path == "/interlock/state":
            return 200, {"joints": [self.follow]}
        raise AssertionError(f"unexpected request {method} {path}")


def run_scenario(monkeypatch: pytest.MonkeyPatch, stand: Stand) -> bench.Result:
    monkeypatch.setattr(bench, "call", stand)
    with Bench() as run:
        run.services["bridge"] = Running("bridge", "http://bridge", "real")
        run.services["twin"] = Running("twin", "http://twin", "real")
        return run.certified_command_moves_the_simulated_robot()


def test_a_certified_command_moves_the_joint_over_time_and_the_twin_follows_it(monkeypatch: pytest.MonkeyPatch) -> None:
    result = run_scenario(monkeypatch, Stand())
    assert (result.status, result.name) == ("pass", NAME)
    assert "measured" in result.detail


def test_a_twin_that_refuses_to_sign_fails_with_its_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    stand = Stand()
    stand.certify = [(403, "no")]
    result = run_scenario(monkeypatch, stand)
    assert result.status == "fail"
    assert "403" in result.detail


def test_a_twin_without_a_recent_state_is_given_one_and_asked_again(monkeypatch: pytest.MonkeyPatch) -> None:
    stand = Stand()
    stand.certify = [(409, "stale"), (200, {"signature": "abc"})]
    result = run_scenario(monkeypatch, stand)
    assert result.status == "pass"
    assert stand.certify_calls == 2
    assert stand.steps >= 3  # the refresh of the state, then the two steps of the scenario


def test_a_bridge_that_does_not_send_the_order_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    for route in ((500, "down"), (200, {"outcome": "Refused"})):
        stand = Stand()
        stand.route = route
        result = run_scenario(monkeypatch, stand)
        assert result.status == "fail"
        assert "the bridge answered" in result.detail


def test_a_joint_that_is_not_on_its_way_after_a_moment_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    for partway in ({"joint": "shoulder", "position": 0.0, "moving": True}, {"joint": "shoulder", "position": 1.0, "moving": True}, {"joint": "shoulder", "position": 0.5, "moving": False}):
        stand = Stand()
        stand.partway = partway
        result = run_scenario(monkeypatch, stand)
        assert result.status == "fail"
        assert "on its way" in result.detail


def test_a_joint_that_never_arrives_or_is_not_followed_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    for field_name, value in (("done", {"joint": "shoulder", "position": 0.9, "moving": False}), ("done", {"joint": "shoulder", "position": 1.0, "moving": True}), ("follow", {"joint": "shoulder", "source": "commanded"}), ("follow", {"joint": "elbow", "source": "measured"})):
        stand = Stand()
        setattr(stand, field_name, value)
        result = run_scenario(monkeypatch, stand)
        assert result.status == "fail"
        assert "did not arrive" in result.detail
