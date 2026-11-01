# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The local bench that runs the services against each other: with simulated services (what CI can do anywhere), with a service that is down,
and the checks of the Prometheus text. The real services are exercised by `bench --real` where the other checkouts and builds exist."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from hydra_umc_dev_server import bench
from hydra_umc_dev_server.bench import Bench, call, free_port, main, prometheus_problem


def _by_name(results: list[bench.Result]) -> dict[str, bench.Result]:
    return {result.name: result for result in results}


def test_with_simulated_services_the_whole_chain_runs_and_what_needs_the_real_robot_is_skipped() -> None:
    with Bench() as run:
        results = _by_name(run.run())
        assert {name: service.source for name, service in run.services.items()} == {"planner": "simulated", "safety": "simulated", "dispatcher": "simulated", "twin": "simulated", "bridge": "unavailable"}
    assert [r.status for r in results.values()] == ["pass", "pass", "pass", "pass", "pass", "skip"]
    assert "job bench-" in results["chain_to_dispatch"].detail
    assert "SKIP" not in results["health"].detail


def test_a_person_in_the_cell_stops_the_chain_before_any_certificate_or_job() -> None:
    with Bench() as run:
        result = run.breach_stops_the_chain()
        twin, dispatcher = run.services["twin"].simulated, run.services["dispatcher"].simulated
        assert result.status == "pass", result.detail
        assert ("POST", "/interlock/certify") not in twin.calls
        assert ("POST", "/jobs") not in dispatcher.calls


def test_a_clear_cell_signs_one_certificate_and_queues_one_job() -> None:
    with Bench() as run:
        assert run.chain_to_dispatch().status == "pass"
        assert run.services["twin"].simulated.calls.count(("POST", "/interlock/certify")) == 1
        assert run.services["dispatcher"].simulated.calls.count(("POST", "/jobs")) == 1


def test_the_simulated_twin_signs_only_with_its_token_and_the_safety_zone_wants_calibration() -> None:
    with Bench() as run:
        report = {"joint": "shoulder", "position": 0.5, "collision_imminent": False, "distance_m": 0.5}
        assert call(run.url("twin"), "POST", "/interlock/certify", report)[0] == 401
        assert call(run.url("twin"), "POST", "/interlock/certify", report, token="wrong-token-0123456789")[0] == 401
        assert call(run.url("twin"), "POST", "/interlock/certify", report, token=bench.TWIN_TOKEN)[0] == 200
        uncalibrated = {"zones": {"zones": []}, "detections": {"objects": []}, "observation": {"active": True}}
        status, answer = call(run.url("safety"), "POST", "/check", uncalibrated)
        assert (status, answer["state"]) == (200, "inhibited")


def test_a_service_that_is_down_fails_the_scenarios_and_never_crashes_the_bench() -> None:
    dead = f"http://127.0.0.1:{free_port()}"
    with Bench(given={"planner": dead}) as run:
        results = _by_name(run.run())
        assert run.services["planner"].source == "given"
    assert results["health"].status == "fail" and "planner" in results["health"].detail
    assert results["chain_to_dispatch"].status == "fail" and "RuntimeError" in results["chain_to_dispatch"].detail
    assert results["metrics_are_prometheus_text"].status == "pass"   # the services that do answer still pass their own checks


def test_a_service_that_is_given_is_used_as_it_is() -> None:
    simulated = bench._planner().start()
    try:
        with Bench(given={"planner": simulated.url}) as run:
            assert run.services["planner"].url == simulated.url
            assert run.unapproved_plan_is_not_executable().status == "pass"
        assert ("POST", "/decompose") in simulated.calls
    finally:
        simulated.stop()


def test_real_mode_falls_back_to_simulated_services_where_the_checkouts_are_missing(tmp_path: Path) -> None:
    with Bench(real=True, workspace=str(tmp_path)) as run:
        assert {service.source for service in run.services.values()} <= {"simulated", "unavailable"}
        assert all(result.status != "fail" for result in run.run())


def test_the_command_line_prints_a_verdict_and_a_json_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    text = capsys.readouterr().out
    assert "BENCH=PASS 6/6" in text and "planner=simulated" in text
    assert main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out.split("BENCH=")[0])
    assert set(report) == {"services", "results"} and len(report["results"]) == 6


def test_the_exit_code_is_one_when_a_scenario_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--planner", f"http://127.0.0.1:{free_port()}"]) == 1
    assert "BENCH=FAIL" in capsys.readouterr().out


def test_a_whole_run_is_quick() -> None:
    started = time.monotonic()
    with Bench() as run:
        run.run()
    assert time.monotonic() - started < 10


def test_the_scratch_folder_is_deleted_at_the_end() -> None:
    with Bench() as run:
        scratch = run.scratch
        assert scratch.is_dir()
    assert not scratch.exists()


VALID = "# HELP a_total Things.\n# TYPE a_total counter\na_total 3\n# HELP b A gauge.\n# TYPE b gauge\nb{kind=\"x\"} 1.5\n"


def test_prometheus_text_that_follows_the_format_has_no_problem() -> None:
    assert prometheus_problem(VALID) == ""


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("", "no series"),
        ("a_total 3\n", "before its TYPE"),
        ("# TYPE a_total mystery\na_total 3\n", "bad TYPE"),
        ("# TYPE a_total counter\na_total three\n", "bad series"),
        ("# TYPE a_total counter\nbad name 3\n", "bad series"),
        ("# HELP a\n# TYPE a gauge\na 1\n", "bad HELP"),
    ],
)
def test_prometheus_text_with_a_defect_is_named(text: str, needle: str) -> None:
    assert needle in prometheus_problem(text)


def test_an_unreachable_address_is_status_zero_with_the_reason() -> None:
    status, reason = call(f"http://127.0.0.1:{free_port()}", "GET", "/stats")
    assert status == 0 and isinstance(reason, str) and reason
