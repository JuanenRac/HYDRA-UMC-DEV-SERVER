# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/bridge_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Scenarios for the bridge bench (`bench/docker-compose.bridges.yml`): a machine bridge behind the real MQTT broker, in front of an emulator.

The CNC bridge runs against the GRBL emulator of its own tests and the 3D-printer bridge against the Moonraker stand-in of this package, both started
by `bridge_rig.py` next to the broker container. The scenarios speak MQTT 3.1.1 as the operator and read what the emulator or the stand-in received over
the control side of the rig, so what is checked is the whole way: the retained availability, a status query, a refused command, a stop that really
reaches the machine, a start for a file that does not exist that never reaches it. Nothing here touches a machine; the emulators prove the bridge's
behaviour, not a controller's.

Each scenario is one named check with a PASS / FAIL line; the run fails at the end (never at the first failure).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Callable

from .bench import Result, call
from .broker_bench import SILENCE_S, SUBACK_REFUSED, MqttClient

#: More than the largest payload a bridge reads (16 KiB).
OVER_THE_LIMIT = 20 * 1024
#: How long the retained messages that are waiting for a new subscriber are collected before a command is sent.
RETAINED_WAIT_S = 0.8


class Rig:
    """The bench of one bridge: where the broker listens, the operator identity of the compose file and the control side of the rig."""

    def __init__(self, name: str, host: str, mqtt_port: int, ops_password: str, control_url: str) -> None:
        self.name = name
        self.host = host
        self.mqtt_port = mqtt_port
        self.ops_password = ops_password
        self.control_url = control_url

    @property
    def prefix(self) -> str:
        return f"hydra/bridges/{self.name}/"

    def ops(self, run_id: str) -> MqttClient:
        client = MqttClient(self.host, self.mqtt_port, f"ops-bridge-bench-{run_id}")
        code = client.connect("ops", self.ops_password)
        assert code == 0, f"ops with the right password was refused (CONNACK code {code})"
        return client

    def control(self, method: str, path: str) -> object:
        status, body = call(self.control_url, method, path)
        assert status == 200, f"the control side answered {status} to {method} {path}: {body}"
        return body

    def log(self) -> list[str]:
        body = self.control("GET", "/_bench/log")
        assert isinstance(body, list), f"the control log is not a list: {body!r}"
        return [str(item) for item in body]

    def reset(self) -> None:
        self.control("POST", "/_bench/reset")


def _listen(rig: Rig, run_id: str) -> MqttClient:
    """An operator that listens to every topic of the bridge, with the retained messages already collected."""
    ops = rig.ops(run_id)
    granted = ops.subscribe(rig.prefix + "#")
    assert granted != SUBACK_REFUSED and granted >= 0, f"the operator could not read the topics of the bridge (SUBACK {granted})"
    while ops.next_message(RETAINED_WAIT_S) is not None:
        pass
    return ops


def _answer(ops: MqttClient, topic: str, wait: float = 10.0) -> tuple[bytes | None, list[str]]:
    """The payload that arrives on `topic` within [wait] seconds (None: nothing), and the topics of the other messages that came first."""
    others: list[str] = []
    deadline = time.monotonic() + wait
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return None, others
        got = ops.next_message(left)
        if got is None:
            return None, others
        if got[0] == topic:
            return got[1], others
        others.append(got[0])


def _ask(rig: Rig, run_id: str, verb: str, payload: bytes, answer: str | None = None) -> dict:
    """Sends `cmd/<verb>` as the operator and returns the JSON the bridge answers on `answer` (default: the result topic of the verb)."""
    ops = _listen(rig, run_id)
    try:
        topic = rig.prefix + (answer or f"cmd/{verb}/result")
        ops.publish(f"{rig.prefix}cmd/{verb}", payload)
        raw, _ = _answer(ops, topic)
    finally:
        ops.close()
    assert raw is not None, f"cmd/{verb} got no answer on {topic}"
    body = json.loads(raw)
    assert isinstance(body, dict), f"the answer to cmd/{verb} is not an object: {raw!r}"
    return body


def scenario_availability(rig: Rig, run_id: str) -> str:
    ops = rig.ops(run_id)
    try:
        granted = ops.subscribe(rig.prefix + "availability")
        assert granted != SUBACK_REFUSED and granted >= 0, f"the availability topic could not be read (SUBACK {granted})"
        got = ops.next_message()
    finally:
        ops.close()
    assert got == (rig.prefix + "availability", b"online"), f"the retained availability is {got!r}, not online"
    return "the bridge is retained as online on its availability topic"


def scenario_status(rig: Rig, run_id: str) -> str:
    before = int(time.time() * 1000) - 5000
    body = _ask(rig, run_id, "status", b"", answer="state")
    state = body.get("machine_state", body.get("state"))
    assert state == "IDLE", f"the state of an idle machine is {state!r}: {body}"
    observed = body.get("observed_at")
    assert isinstance(observed, int) and observed >= before, f"observed_at is {observed!r}, not a time of this run"
    return "a status query publishes the state of the idle machine with the time it was read"


def scenario_malformed_job(rig: Rig, run_id: str) -> str:
    body = _ask(rig, run_id, "job", b"this is not json")
    assert body.get("allowed") is False, f"a payload that is not JSON was allowed: {body}"
    return f"a job that is not JSON is refused ({body.get('reason', 'no reason')})"


def scenario_oversized(rig: Rig, run_id: str) -> str:
    body = _ask(rig, run_id, "job", b"{" + b" " * OVER_THE_LIMIT + b"}")
    assert body.get("allowed") is False, f"a payload over the limit was allowed: {body}"
    assert "larger" in str(body.get("reason", "")), f"the refusal does not say that the payload is too large: {body}"
    return "a payload over the limit is refused with its reason"


def scenario_unknown_verb(rig: Rig, run_id: str) -> str:
    ops = _listen(rig, run_id)
    try:
        ops.publish(rig.prefix + "cmd/not_a_verb", b"{}")
        heard = ops.next_message(SILENCE_S)
    finally:
        ops.close()
    assert heard is None or heard[0] == rig.prefix + "cmd/not_a_verb", f"a verb the bridge does not know was answered: {heard!r}"
    return "a verb the bridge does not know is ignored, never answered"


def scenario_cnc_feed_hold_reaches_the_controller(rig: Rig, run_id: str) -> str:
    rig.reset()
    body = _ask(rig, run_id, "feed_hold", b"")
    assert body.get("executed") is True, f"the feed hold was not executed: {body}"
    written = "".join(rig.log())
    assert "!" in written, f"the emulator did not receive the feed hold byte, it got {written!r}"
    return "a feed hold reaches the controller as the real-time byte and the result says it was sent"


def scenario_cnc_resume_needs_a_hold(rig: Rig, run_id: str) -> str:
    rig.reset()
    body = _ask(rig, run_id, "cycle_start_resume", b"")
    assert body.get("executed") is False, f"a resume of an idle machine was executed: {body}"
    assert "~" not in "".join(rig.log()), "the cycle start byte reached the controller of an idle machine"
    rig.control("POST", "/_bench/hold")
    body = _ask(rig, run_id, "cycle_start_resume", b"")
    assert body.get("executed") is True, f"a resume of a machine in hold was refused: {body}"
    assert "~" in "".join(rig.log()), "the cycle start byte did not reach the controller"
    rig.reset()
    return "a resume is refused while the machine is idle and reaches the controller only from a hold"


def scenario_cnc_alarm_is_not_idle(rig: Rig, run_id: str) -> str:
    rig.reset()
    rig.control("POST", "/_bench/alarm")
    try:
        body = _ask(rig, run_id, "status", b"", answer="state")
    finally:
        rig.reset()
    state = body.get("machine_state")
    assert state != "IDLE", f"a machine in alarm was published as {state!r}"
    return f"a machine in alarm is published as {state}, never idle"


def scenario_printer_pause_and_cancel(rig: Rig, run_id: str) -> str:
    rig.reset()
    rig.control("POST", "/_bench/print")
    body = _ask(rig, run_id, "pause", b"")
    assert body.get("executed") is True, f"the pause was not executed: {body}"
    assert "POST /printer/print/pause" in rig.log(), f"the stand-in never received the pause: {rig.log()}"
    status = _ask(rig, run_id, "status", b"", answer="state")
    assert status.get("state") == "HOLDING", f"a paused print is published as {status.get('state')!r}"
    body = _ask(rig, run_id, "cancel", b"")
    assert body.get("executed") is True, f"the cancel was not executed: {body}"
    assert "POST /printer/print/cancel" in rig.log(), f"the stand-in never received the cancel: {rig.log()}"
    rig.reset()
    return "a pause and a cancel reach the printer, and a paused print is published as holding"


def scenario_printer_resume_needs_a_pause(rig: Rig, run_id: str) -> str:
    rig.reset()
    body = _ask(rig, run_id, "resume", b"")
    assert body.get("executed") is False, f"a resume of an idle printer was executed: {body}"
    assert "POST /printer/print/resume" not in rig.log(), "the resume reached the printer although nothing was paused"
    return "a resume is refused while nothing is paused and never reaches the printer"


def scenario_printer_emergency_stop(rig: Rig, run_id: str) -> str:
    rig.reset()
    body = _ask(rig, run_id, "emergency_stop", b"")
    assert body.get("executed") is True, f"the emergency stop was not executed: {body}"
    assert "POST /printer/emergency_stop" in rig.log(), f"the stand-in never received the emergency stop: {rig.log()}"
    rig.reset()
    return "an emergency stop reaches the printer even when nothing is printing"


def scenario_printer_start_of_a_missing_file(rig: Rig, run_id: str) -> str:
    rig.reset()
    job = {
        "job_id": f"bench-{run_id}",
        "idempotency_key": f"bench-start-{run_id}",
        "source": "bench",
        "phase": "PROCESS",
        "machine_state": "IDLE",
    }
    body = _ask(rig, run_id, "start", json.dumps({"job": job, "filename": "no_such_file.gcode"}).encode())
    assert body.get("executed") is False, f"a start for a file the printer does not hold was executed: {body}"
    assert "POST /printer/print/start" not in rig.log(), "the start reached the printer for a file it does not hold"
    return "a start for a file the printer does not hold is refused before it reaches the printer"


COMMON: list[tuple[str, Callable[[Rig, str], str]]] = [
    ("availability", scenario_availability),
    ("status", scenario_status),
    ("malformed_job", scenario_malformed_job),
    ("oversized", scenario_oversized),
    ("unknown_verb", scenario_unknown_verb),
]

#: The scenarios of each bridge of the bench, in order.
SCENARIOS: dict[str, list[tuple[str, Callable[[Rig, str], str]]]] = {
    "cnc": COMMON
    + [
        ("cnc_feed_hold_reaches_the_controller", scenario_cnc_feed_hold_reaches_the_controller),
        ("cnc_resume_needs_a_hold", scenario_cnc_resume_needs_a_hold),
        ("cnc_alarm_is_not_idle", scenario_cnc_alarm_is_not_idle),
    ],
    "printer3d": COMMON
    + [
        ("printer_pause_and_cancel", scenario_printer_pause_and_cancel),
        ("printer_resume_needs_a_pause", scenario_printer_resume_needs_a_pause),
        ("printer_emergency_stop", scenario_printer_emergency_stop),
        ("printer_start_of_a_missing_file", scenario_printer_start_of_a_missing_file),
    ],
}


def wait_until_ready(rig: Rig, seconds: float) -> bool:
    """True once the control side of the rig answers; the bridge needs a moment after it starts."""
    deadline = time.monotonic() + seconds
    while True:
        status, _ = call(rig.control_url, "GET", "/_bench/log")
        if status == 200:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1.0)


def run(rig: Rig, run_id: str | None = None, only: list[str] | None = None) -> list[Result]:
    """Every scenario of the bridge, in order. A scenario that raises is a failure with the reason; the run goes on."""
    run_id = run_id or str(int(time.time()))
    results: list[Result] = []
    for name, scenario in SCENARIOS[rig.name]:
        if only and name not in only:
            continue
        started = time.monotonic()
        try:
            detail, status = scenario(rig, run_id), "pass"
        except AssertionError as error:
            detail, status = str(error), "fail"
        except Exception as error:  # a broken scenario must not stop the others
            detail, status = f"{type(error).__name__}: {error}", "fail"
        results.append(Result(name, status, detail, round(time.monotonic() - started, 3)))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hydra-umc-dev-server-bridge-bench", description="Scenarios against a machine bridge behind the MQTT broker of the bridge bench.")
    parser.add_argument("bridge", choices=sorted(SCENARIOS), help="which bridge the rig runs")
    parser.add_argument("--host", default="127.0.0.1", help="where the MQTT port is published")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--control-url", default="http://127.0.0.1:8099")
    parser.add_argument("--wait", type=float, default=60.0, help="seconds to wait for the rig before the scenarios start (0: do not wait)")
    parser.add_argument("--only", action="append", help="run only this scenario (repeatable)")
    arguments = parser.parse_args(argv)
    ops_password = os.environ.get("BRIDGE_BENCH_OPS_PASSWORD", "")
    if not ops_password:
        print("BRIDGE_BENCH=FAIL BRIDGE_BENCH_OPS_PASSWORD must be set", file=sys.stderr)
        return 2
    rig = Rig(arguments.bridge, arguments.host, arguments.mqtt_port, ops_password, arguments.control_url)
    if arguments.wait > 0 and not wait_until_ready(rig, arguments.wait):
        print(f"BRIDGE_BENCH=FAIL the rig did not answer within {arguments.wait:g} s")
        return 1
    results = run(rig, only=arguments.only)
    for result in results:
        print(f"{result.status.upper():4} {result.name}: {result.detail}")
    failed = [r.name for r in results if r.status != "pass"]
    print(f"BRIDGE_BENCH={'FAIL' if failed else 'PASS'} bridge={rig.name} scenarios={len(results)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
