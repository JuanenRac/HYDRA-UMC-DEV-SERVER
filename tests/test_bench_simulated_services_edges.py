# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_bench_simulated_services_edges.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The refusals of the simulated services of the bench (a request that is malformed, unknown or repeated) and the wait of the bridge bench for its
rig. The services are the real stand-in servers on a loopback port; the rig is a stand-in whose `call` is replaced (evidence: simulator)."""
from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Iterator

import pytest

from hydra_umc_dev_server import bench, bridge_bench


@pytest.fixture
def services() -> Iterator[dict[str, bench.SimulatedService]]:
    started = {name: factory().start() for name, factory in bench.SIMULATED.items()}
    try:
        yield started
    finally:
        for service in started.values():
            service.stop()


def test_the_planner_refuses_a_goal_that_is_not_text_or_too_long_and_a_route_it_does_not_have(services) -> None:
    url = services["planner"].url
    assert bench.call(url, "POST", "/decompose", {"goal": 5})[0] == 400
    assert bench.call(url, "POST", "/decompose", {"goal": "x" * 513})[0] == 400
    assert bench.call(url, "POST", "/decompose", [1])[0] == 400
    assert bench.call(url, "GET", "/nothing")[0] == 404
    status, unknown = bench.call(url, "POST", "/decompose", {"goal": "paint the moon"})
    assert status == 200 and unknown["matched"] is False and unknown["valid"] is False


def test_the_safety_service_inhibits_without_an_observer_and_refuses_what_is_not_an_object(services) -> None:
    url = services["safety"].url
    assert bench.call(url, "POST", "/check", [1])[0] == 400
    assert bench.call(url, "GET", "/nothing")[0] == 404
    zones = {"calibration": {"version": "x"}, "zones": []}
    status, answer = bench.call(url, "POST", "/check", {"zones": zones, "observation": {"active": False}})
    assert status == 200 and answer["state"] == "inhibited" and answer["reason"] == "no active observer"


def test_the_dispatcher_refuses_a_job_without_id_a_repeated_job_and_an_unknown_route(services) -> None:
    url = services["dispatcher"].url
    assert bench.call(url, "POST", "/jobs", {"priority": 1})[0] == 400
    assert bench.call(url, "POST", "/jobs", {"id": ""})[0] == 400
    assert bench.call(url, "POST", "/jobs", {"id": "job-1"})[0] == 201
    assert bench.call(url, "POST", "/jobs", {"id": "job-1"})[0] == 409
    assert bench.call(url, "GET", "/jobs/missing")[0] == 404
    assert bench.call(url, "GET", "/nothing")[0] == 404


def test_the_twin_refuses_a_malformed_report_a_missing_token_and_an_unknown_route(services) -> None:
    url = services["twin"].url
    assert bench.call(url, "POST", "/interlock/certify", {"joint": "j"})[0] == 401
    assert bench.call(url, "POST", "/interlock/certify", {"joint": 5}, token=bench.TWIN_TOKEN)[0] == 400
    assert bench.call(url, "POST", "/interlock/certify", [1], token=bench.TWIN_TOKEN)[0] == 400
    assert bench.call(url, "GET", "/nothing")[0] == 404


def test_a_body_that_is_not_json_reaches_the_service_as_no_body(services) -> None:
    import urllib.request

    request = urllib.request.Request(services["dispatcher"].url + "/jobs", data=b"{not json", method="POST")
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=5)
    assert refused.value.code == 400


def test_the_bridge_bench_waits_for_the_rig_and_gives_up_at_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = SimpleNamespace(control_url="http://rig")
    answers = iter([(0, "down"), (0, "down"), (200, "ok")])
    monkeypatch.setattr(bridge_bench, "call", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(bridge_bench.time, "sleep", lambda seconds: None)
    assert bridge_bench.wait_until_ready(rig, 60.0) is True

    ticks = itertools.count(0.0, 1.0)
    monkeypatch.setattr(bridge_bench, "call", lambda *args, **kwargs: (0, "down"))
    monkeypatch.setattr(bridge_bench.time, "monotonic", lambda: next(ticks))
    assert bridge_bench.wait_until_ready(rig, 3.0) is False
