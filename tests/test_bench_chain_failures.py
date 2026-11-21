# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_bench_chain_failures.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Every way the two chain scenarios of the bench can fail, and the reading of the answers of the bridge rig: a plan that is not valid, a cell that is
not clear, a twin or a dispatcher that refuses, a job that is not there afterwards, a person in the cell that safety does not see, a job that exists for
a stopped run, and the wait for a message that never comes or that comes after others (evidence: simulator; the steps of the chain are replaced)."""
from __future__ import annotations

import time
from unittest import mock

from hydra_umc_dev_server import bench, bridge_bench
from hydra_umc_dev_server.bench import Bench

READY = {"state": "ready", "reason": "clear", "estopRequests": []}
PLAN = {"valid": True, "steps": [{"id": 1}], "matched": True}


def chain(plan=PLAN, safety=READY, certify=(200, {"signature": "s"}), calls=None):
    """A bench whose steps answer as given; `calls` are the answers of the dispatcher in order."""
    answers = list(calls if calls is not None else [(201, {}), (200, {})])
    run = Bench()
    run._plan = lambda: plan  # type: ignore[method-assign]
    run._check = lambda position: safety  # type: ignore[method-assign]
    run._certify = lambda joint, position: certify  # type: ignore[method-assign]
    run.url = lambda name: "http://dispatcher.invalid"  # type: ignore[method-assign]
    return run, answers


def run_chain(method, **given):
    run, answers = chain(**given)
    with mock.patch.object(bench, "call", side_effect=lambda *a, **k: answers.pop(0)):
        return getattr(run, method)()


def test_a_plan_that_is_not_valid_or_has_no_step_fails_the_chain() -> None:
    for plan in ({"valid": False, "steps": [1]}, {"valid": True, "steps": []}):
        result = run_chain("chain_to_dispatch", plan=plan)
        assert result.status == "fail" and "not valid or has no step" in result.detail


def test_a_cell_that_is_not_clear_fails_the_chain_with_the_reason_safety_gives() -> None:
    result = run_chain("chain_to_dispatch", safety={"state": "stopped", "reason": "person"})
    assert result.status == "fail" and "stopped: person" in result.detail


def test_a_twin_that_refuses_or_signs_nothing_fails_the_chain() -> None:
    assert "the twin answered 403" in run_chain("chain_to_dispatch", certify=(403, {})).detail
    assert "the twin answered 200" in run_chain("chain_to_dispatch", certify=(200, {})).detail


def test_a_dispatcher_that_refuses_the_job_or_loses_it_fails_the_chain() -> None:
    refused = run_chain("chain_to_dispatch", calls=[(500, {"error": "x"})])
    assert refused.status == "fail" and "dispatcher answered 500" in refused.detail
    lost = run_chain("chain_to_dispatch", calls=[(201, {}), (404, {})])
    assert lost.status == "fail" and "not there afterwards (404)" in lost.detail


def test_a_person_in_the_cell_that_safety_does_not_see_fails_the_breach_scenario() -> None:
    for safety in ({"state": "ready", "estopRequests": []}, {"state": "stopped", "estopRequests": []}):
        result = run_chain("breach_stops_the_chain", safety=safety)
        assert result.status == "fail" and "must stop the chain" in result.detail


def test_a_job_that_exists_for_a_stopped_run_fails_the_breach_scenario() -> None:
    stopped = {"state": "stopped", "estopRequests": [{"id": 1}]}
    assert run_chain("breach_stops_the_chain", safety=stopped, calls=[(200, {})]).status == "fail"
    assert run_chain("breach_stops_the_chain", safety=stopped, calls=[(404, {})]).status == "pass"


class Operator:
    """Plays the operator side of the rig: the messages come in the order given, then nothing."""

    def __init__(self, messages) -> None:
        self.messages = list(messages)

    def next_message(self, wait: float):
        return self.messages.pop(0) if self.messages else None


def test_the_wait_for_an_answer_collects_the_other_topics_that_came_first() -> None:
    payload, others = bridge_bench._answer(Operator([("a", b"1"), ("b", b"2"), ("want", b"ok")]), "want", wait=5.0)
    assert (payload, others) == (b"ok", ["a", "b"])


def test_the_wait_for_an_answer_ends_empty_when_nothing_more_comes() -> None:
    payload, others = bridge_bench._answer(Operator([("a", b"1")]), "want", wait=5.0)
    assert (payload, others) == (None, ["a"])


def test_the_wait_for_an_answer_ends_empty_when_the_time_is_up() -> None:
    with mock.patch.object(time, "monotonic", side_effect=[0.0, 10.0]):
        assert bridge_bench._answer(Operator([("want", b"late")]), "want", wait=1.0) == (None, [])
