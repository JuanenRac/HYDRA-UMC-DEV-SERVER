# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_bridge_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The Moonraker stand-in, the control side of the rig and the scenarios of the bridge bench.

The scenarios are run against a small broker on the loopback address that keeps retained messages, and a stand-in for the printer bridge that speaks to the
Moonraker stand-in the way the real one does (readiness, the action endpoints, a check of the file before a start). The real bridges behind the real broker
container are exercised by the manual workflow of this repository."""
from __future__ import annotations

import json
import socketserver
import threading

import pytest

from hydra_umc_dev_server import bridge_bench, broker_bench
from hydra_umc_dev_server.bench import call
from hydra_umc_dev_server.bridge_bench import SCENARIOS, Rig, main, run
from hydra_umc_dev_server.bridge_rig import serve_control
from hydra_umc_dev_server.broker_bench import MqttClient
from hydra_umc_dev_server.fake_moonraker import FakeMoonraker

PREFIX = "hydra/bridges/printer3d/"
OPS_PASSWORD = "ops-password-0123456789ab"


# ---- the Moonraker stand-in --------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def moonraker():
    server = FakeMoonraker().start()
    yield server
    server.stop()


def test_the_stand_in_answers_in_the_wire_shape_of_moonraker(moonraker):
    status, info = call(moonraker.base_url, "GET", "/printer/info")
    assert status == 200 and info == {"result": {"state": "ready", "state_message": "Printer is ready"}}
    status, objects = call(moonraker.base_url, "GET", "/printer/objects/query?print_stats=state")
    assert status == 200 and objects["result"]["status"]["print_stats"]["state"] == "standby"
    assert call(moonraker.base_url, "GET", "/server/files/metadata?filename=part.gcode")[0] == 200
    assert call(moonraker.base_url, "GET", "/server/files/metadata?filename=other.gcode")[0] == 404
    assert call(moonraker.base_url, "GET", "/nowhere")[0] == 404


def test_the_print_state_follows_the_actions_a_real_printer_allows(moonraker):
    post = lambda path: call(moonraker.base_url, "POST", path)  # noqa: E731
    state = lambda: call(moonraker.base_url, "GET", "/printer/objects/query")[1]["result"]["status"]["print_stats"]["state"]  # noqa: E731
    assert post("/printer/print/pause")[0] == 400 and post("/printer/print/resume")[0] == 400 and post("/printer/print/cancel")[0] == 400
    assert post("/printer/print/start") == (200, {"result": "ok"}) and state() == "printing"
    assert post("/printer/print/start")[0] == 400
    assert post("/printer/print/pause")[0] == 200 and state() == "paused"
    assert post("/printer/print/resume")[0] == 200 and state() == "printing"
    assert post("/printer/print/cancel")[0] == 200 and state() == "cancelled"


def test_an_emergency_stop_shuts_the_printer_down_and_nothing_else_is_accepted_after_it(moonraker):
    assert call(moonraker.base_url, "POST", "/printer/emergency_stop")[0] == 200
    assert call(moonraker.base_url, "GET", "/printer/info")[1]["result"]["state"] == "shutdown"
    assert call(moonraker.base_url, "POST", "/printer/print/start")[0] == 400


def test_the_control_side_lists_the_requests_and_resets_the_printer(moonraker):
    call(moonraker.base_url, "GET", "/printer/info")
    call(moonraker.base_url, "POST", "/printer/print/start")
    assert call(moonraker.base_url, "GET", "/_bench/log")[1] == ["GET /printer/info", "POST /printer/print/start"]
    assert call(moonraker.base_url, "POST", "/_bench/print")[0] == 200
    assert call(moonraker.base_url, "POST", "/_bench/reset")[0] == 200
    assert call(moonraker.base_url, "GET", "/_bench/log")[1] == []
    assert call(moonraker.base_url, "GET", "/printer/objects/query")[1]["result"]["status"]["print_stats"]["state"] == "standby"


def test_the_control_side_of_a_machine_without_http_runs_its_actions_and_refuses_the_rest():
    ran: list[str] = []
    server = serve_control("127.0.0.1", 0, lambda: ["written"], {"alarm": lambda: ran.append("alarm")})
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert call(base, "GET", "/_bench/log") == (200, ["written"])
        assert call(base, "POST", "/_bench/alarm")[0] == 200 and ran == ["alarm"]
        assert call(base, "POST", "/_bench/unknown")[0] == 404
        assert call(base, "POST", "/elsewhere")[0] == 404
        assert call(base, "GET", "/elsewhere")[0] == 404
    finally:
        server.shutdown()
        server.server_close()


# ---- a broker that keeps retained messages -------------------------------------------------------------------------------------------------------


def _matches(topic: str, pattern: str) -> bool:
    t, p = topic.split("/"), pattern.split("/")
    for index, part in enumerate(p):
        if part == "#":
            return True
        if index >= len(t) or (part != "+" and part != t[index]):
            return False
    return len(t) == len(p)


class RetainingBroker(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Connection)
        self.lock = threading.Lock()
        self.subscribers: list[tuple[_Connection, str]] = []
        self.retained: dict[str, bytes] = {}
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


def _read_length(rfile) -> int:
    size, shift = 0, 0
    while True:
        byte = rfile.read(1)[0]
        size += (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return size


def _text(body: bytes, at: int) -> tuple[str, int]:
    size = int.from_bytes(body[at : at + 2], "big")
    return body[at + 2 : at + 2 + size].decode(), at + 2 + size


class _Connection(socketserver.StreamRequestHandler):
    server: RetainingBroker

    def handle(self) -> None:
        try:
            while True:
                first = self.rfile.read(1)
                if not first:
                    return
                body = self.rfile.read(_read_length(self.rfile))
                self.packet(first[0], body)
        except (OSError, IndexError):
            return
        finally:
            with self.server.lock:
                self.server.subscribers = [s for s in self.server.subscribers if s[0] is not self]

    def send(self, first: int, body: bytes) -> None:
        with self.server.lock:
            self.wfile.write(bytes([first]) + broker_bench._length(len(body)) + body)
            self.wfile.flush()

    def packet(self, first: int, body: bytes) -> None:
        kind = first >> 4
        if kind == 1:
            self.send(0x20, bytes([0, 0]))
        elif kind == 8:
            topic, _ = _text(body, 2)
            with self.server.lock:
                self.server.subscribers.append((self, topic))
                retained = [(t, p) for t, p in self.server.retained.items() if _matches(t, topic)]
            self.send(0x90, body[:2] + bytes([0]))
            for t, p in retained:
                self.send(0x31, len(t.encode()).to_bytes(2, "big") + t.encode() + p)
        elif kind == 3:
            topic, at = _text(body, 0)
            payload = body[at:]
            with self.server.lock:
                if first & 1:
                    if payload:
                        self.server.retained[topic] = payload
                    else:
                        self.server.retained.pop(topic, None)
                targets = [c for c, f in self.server.subscribers if _matches(topic, f)]
            for target in targets:
                target.send(0x30, body)


# ---- a stand-in for the printer bridge ----------------------------------------------------------------------------------------------------------


class StandInBridge(threading.Thread):
    """Answers the commands of the bench the way the printer bridge does, through the Moonraker stand-in."""

    def __init__(self, port: int, moonraker: FakeMoonraker, mistakes: set[str] | None = None) -> None:
        super().__init__(daemon=True)
        self.moonraker = moonraker
        self.mistakes = mistakes or set()
        self.client = MqttClient("127.0.0.1", port, "bridge-printer3d-test")
        assert self.client.connect("bridge", "x") == 0
        assert self.client.subscribe(PREFIX + "cmd/#") == 0
        self.client._send(0x31, broker_bench._text(PREFIX + "availability") + b"online")
        self.running = True

    def publish(self, topic: str, body: object, retain: bool = False) -> None:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.client._send(0x31 if retain else 0x30, broker_bench._text(PREFIX + topic) + raw)

    def post(self, path: str) -> dict:
        status, _ = call(self.moonraker.base_url, "POST", path)
        return {"allowed": True, "executed": status == 200, "reason": "ok" if status == 200 else "rejected", "http_status": status}

    def run(self) -> None:
        while self.running:
            got = self.client.next_message(0.2)
            if got is None:
                continue
            verb = got[0].removeprefix(PREFIX + "cmd/")
            payload = got[1]
            if len(payload) > 16 * 1024:
                self.publish(f"cmd/{verb}/result", {"allowed": False, "executed": False, "reason": "payload is larger than 16384 bytes"})
            elif verb == "status":
                info = call(self.moonraker.base_url, "GET", "/printer/info")[1]["result"]["state"]
                stats = call(self.moonraker.base_url, "GET", "/printer/objects/query")[1]["result"]["status"]["print_stats"]["state"]
                state = "HOLDING" if stats == "paused" else "RUNNING" if stats == "printing" else "IDLE" if info == "ready" else "FAULT"
                self.publish("state", {"state": state, "message": "", "observed_at": int(__import__("time").time() * 1000)}, retain=True)
            elif verb == "job":
                self.publish("cmd/job/result", {"allowed": False, "reason": "malformed job payload"})
            elif verb in ("pause", "cancel", "emergency_stop"):
                if verb in self.mistakes:
                    self.publish(f"cmd/{verb}/result", {"allowed": True, "executed": True, "reason": "ok", "http_status": 200})
                else:
                    self.publish(f"cmd/{verb}/result", self.post("/printer/emergency_stop" if verb == "emergency_stop" else f"/printer/print/{verb}"))
            elif verb == "resume":
                held = call(self.moonraker.base_url, "GET", "/printer/objects/query")[1]["result"]["status"]["print_stats"]["state"] == "paused"
                if held or "resume" in self.mistakes:
                    self.publish("cmd/resume/result", self.post("/printer/print/resume"))
                else:
                    self.publish("cmd/resume/result", {"allowed": False, "executed": False, "reason": "nothing to resume", "http_status": None})
            elif verb == "start":
                name = json.loads(payload)["filename"]
                known = call(self.moonraker.base_url, "GET", f"/server/files/metadata?filename={name}")[0] == 200
                if known or "start" in self.mistakes:
                    self.publish("cmd/start/result", self.post("/printer/print/start"))
                else:
                    self.publish("cmd/start/result", {"allowed": True, "executed": False, "reason": "no file", "http_status": None})

    def stop(self) -> None:
        self.running = False
        self.join(timeout=3)
        self.client.close()


@pytest.fixture
def rig(moonraker):
    broker = RetainingBroker()
    bridge = StandInBridge(broker.port, moonraker)
    bridge.start()
    control = Rig("printer3d", "127.0.0.1", broker.port, OPS_PASSWORD, moonraker.base_url)
    yield control, bridge
    bridge.stop()
    broker.stop()


def _results(control: Rig) -> dict[str, tuple[str, str]]:
    return {r.name: (r.status, r.detail) for r in run(control, "t")}


def test_every_scenario_of_the_printer_passes_against_the_stand_ins(rig, monkeypatch):
    monkeypatch.setattr(bridge_bench, "RETAINED_WAIT_S", 0.2)
    monkeypatch.setattr(bridge_bench, "SILENCE_S", 0.4)
    results = _results(rig[0])
    assert list(results) == [name for name, _ in SCENARIOS["printer3d"]]
    assert {name: r for name, r in results.items() if r[0] != "pass"} == {}


@pytest.mark.parametrize(
    "mistake, scenario",
    [("emergency_stop", "printer_emergency_stop"), ("resume", "printer_resume_needs_a_pause"), ("start", "printer_start_of_a_missing_file")],
)
def test_a_bridge_that_lets_a_wrong_command_through_fails_its_scenario(moonraker, monkeypatch, mistake, scenario):
    monkeypatch.setattr(bridge_bench, "RETAINED_WAIT_S", 0.2)
    broker = RetainingBroker()
    bridge = StandInBridge(broker.port, moonraker, {mistake})
    bridge.start()
    try:
        control = Rig("printer3d", "127.0.0.1", broker.port, OPS_PASSWORD, moonraker.base_url)
        results = {r.name: r for r in run(control, "t", only=[scenario])}
        assert results[scenario].status == "fail", results[scenario].detail
    finally:
        bridge.stop()
        broker.stop()


def test_a_scenario_that_raises_is_a_failure_and_the_others_still_run(moonraker, monkeypatch):
    monkeypatch.setattr(bridge_bench, "RETAINED_WAIT_S", 0.1)
    unreachable = Rig("printer3d", "127.0.0.1", 1, OPS_PASSWORD, moonraker.base_url)
    results = run(unreachable, "t", only=["availability", "status"])
    assert [r.status for r in results] == ["fail", "fail"]
    assert all(r.detail for r in results)


def test_the_run_can_be_narrowed_to_named_scenarios(rig, monkeypatch):
    monkeypatch.setattr(bridge_bench, "RETAINED_WAIT_S", 0.2)
    results = run(rig[0], "t", only=["availability"])
    assert [r.name for r in results] == ["availability"] and results[0].status == "pass"


def test_the_command_line_needs_the_operator_password_and_a_rig_that_answers(monkeypatch, capsys):
    monkeypatch.delenv("BRIDGE_BENCH_OPS_PASSWORD", raising=False)
    assert main(["cnc"]) == 2
    monkeypatch.setenv("BRIDGE_BENCH_OPS_PASSWORD", OPS_PASSWORD)
    assert main(["cnc", "--wait", "0.2", "--control-url", "http://127.0.0.1:1"]) == 1
    assert "BRIDGE_BENCH=FAIL" in capsys.readouterr().out


def test_the_command_line_prints_one_line_per_scenario_and_the_verdict(rig, monkeypatch, capsys):
    control, _ = rig
    monkeypatch.setattr(bridge_bench, "RETAINED_WAIT_S", 0.2)
    monkeypatch.setattr(bridge_bench, "SILENCE_S", 0.4)
    monkeypatch.setenv("BRIDGE_BENCH_OPS_PASSWORD", OPS_PASSWORD)
    code = main(["printer3d", "--mqtt-port", str(control.mqtt_port), "--control-url", control.control_url, "--wait", "5", "--only", "availability"])
    out = capsys.readouterr().out
    assert code == 0 and "PASS availability" in out and "BRIDGE_BENCH=PASS bridge=printer3d scenarios=1 failed=0" in out


def test_both_bridges_have_the_common_scenarios_and_their_own():
    common = {name for name, _ in bridge_bench.COMMON}
    for bridge, scenarios in SCENARIOS.items():
        names = [name for name, _ in scenarios]
        assert common <= set(names) and len(names) == len(set(names)), bridge
    assert any(name.startswith("cnc_") for name, _ in SCENARIOS["cnc"])
    assert any(name.startswith("printer_") for name, _ in SCENARIOS["printer3d"])


def test_the_rig_reads_nothing_it_was_not_given(monkeypatch):
    from hydra_umc_dev_server import bridge_rig

    monkeypatch.delenv("BRIDGE_BENCH_BRIDGE_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        bridge_rig._credentials()
    monkeypatch.setenv("BRIDGE_BENCH_BRIDGE_PASSWORD", "x" * 16)
    assert bridge_rig._credentials() == ("bridge", "x" * 16)


def test_the_recording_serial_logs_what_the_bridge_writes_but_not_what_the_rig_drives():
    from hydra_umc_dev_server.bridge_rig import RecordingSerial

    class Emulator:
        def __init__(self) -> None:
            self.got = b""

        def write(self, data: bytes) -> int:
            self.got += data
            return len(data)

        def readline(self) -> bytes:
            return b"ok\r\n"

        def close(self) -> None:
            return None

    emulator = Emulator()
    serial = RecordingSerial(emulator)
    assert serial.write(b"!") == 1 and serial.written == ["!"]
    serial.drive(lambda e: e.write(b"$X\n"))
    assert serial.written == ["!"] and emulator.got == b"!$X\n"
    assert serial.readline() == b"ok\r\n"
    serial.forget()
    assert serial.written == [] and serial.close() is None
