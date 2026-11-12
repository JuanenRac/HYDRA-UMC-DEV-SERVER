# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_broker_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The scenarios of the broker bench, run against a small stand-in broker on the loopback address.

The stand-in speaks the part of MQTT 3.1.1 the scenarios use (CONNECT with a user name and a password, SUBSCRIBE, PUBLISH at QoS 0), applies the same kind
of topic rule as the real broker and serves /metrics; the real container is exercised by the manual workflow of this repository."""
from __future__ import annotations

import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hydra_umc_dev_server import broker_bench
from hydra_umc_dev_server.broker_bench import SCENARIOS, Broker, Closed, MqttClient, main, run

ROBOT_PASSWORD = "robot-password-0123456789"
OPS_PASSWORD = "ops-password-0123456789ab"
USERS = {"robot": (ROBOT_PASSWORD, "robot-"), "ops": (OPS_PASSWORD, "ops-")}
RULES = {
    "robot-": {"publish": ["hydra/swarm/+/joints"], "subscribe": ["hydra/swarm/+/cmd/#"]},
    "ops-": {"publish": ["hydra/swarm/+/cmd/#"], "subscribe": ["hydra/swarm/#"]},
}


def _matches(topic: str, pattern: str) -> bool:
    t, p = topic.split("/"), pattern.split("/")
    for index, part in enumerate(p):
        if part == "#":
            return True
        if index >= len(t) or (part != "+" and part != t[index]):
            return False
    return len(t) == len(p)


def _covers(allowed: str, requested: str) -> bool:
    """A requested filter is granted when the allowed filter covers every topic it could match."""
    a, r = allowed.split("/"), requested.split("/")
    for index, part in enumerate(a):
        if part == "#":
            return True
        if index >= len(r) or r[index] == "#":
            return False
        if part != "+" and part != r[index]:
            return False
    return len(a) == len(r)


class FakeBroker(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, mode: str = "good") -> None:
        super().__init__(("127.0.0.1", 0), _Connection)
        self.mode = mode
        self.lock = threading.Lock()
        self.subscribers: list[tuple[_Connection, str]] = []
        self.denied = 0
        self.messages = 0
        self.metrics_server = ThreadingHTTPServer(("127.0.0.1", 0), _Metrics)
        self.metrics_server.broker = self  # type: ignore[attr-defined]
        threading.Thread(target=self.serve_forever, daemon=True).start()
        threading.Thread(target=self.metrics_server.serve_forever, daemon=True).start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def metrics_url(self) -> str:
        return f"http://127.0.0.1:{self.metrics_server.server_address[1]}"

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        self.metrics_server.shutdown()
        self.metrics_server.server_close()


class _Metrics(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        broker: FakeBroker = self.server.broker  # type: ignore[attr-defined]
        if self.path != "/metrics" or broker.mode == "no-metrics":
            self.send_response(404)
            self.end_headers()
            return
        text = (
            "# HELP hydra_mqtt_connected_clients Clients.\n# TYPE hydra_mqtt_connected_clients gauge\nhydra_mqtt_connected_clients 1\n"
            "# HELP hydra_mqtt_messages_total Messages.\n# TYPE hydra_mqtt_messages_total counter\n"
            f"hydra_mqtt_messages_total {broker.messages}\n"
            "# HELP hydra_mqtt_acl_denied_total Refusals.\n# TYPE hydra_mqtt_acl_denied_total counter\n"
            f"hydra_mqtt_acl_denied_total {0 if broker.mode == 'uncounted' else broker.denied}\n"
        )
        raw = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


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
    server: FakeBroker

    def handle(self) -> None:
        self.prefix = ""
        try:
            while True:
                first = self.rfile.read(1)
                if not first:
                    return
                body = self.rfile.read(_read_length(self.rfile))
                if not self.packet(first[0] >> 4, body):
                    return
        except (OSError, IndexError):
            return
        finally:
            with self.server.lock:
                self.server.subscribers = [s for s in self.server.subscribers if s[0] is not self]

    def send(self, first: int, body: bytes) -> None:
        self.wfile.write(bytes([first]) + broker_bench._length(len(body)) + body)
        self.wfile.flush()

    def packet(self, kind: int, body: bytes) -> bool:
        mode = self.server.mode
        if kind == 1:
            flags = body[7]
            at = 10
            _client, at = _text(body, at)
            user = password = None
            if flags & 0x80:
                user, at = _text(body, at)
            if flags & 0x40:
                password, at = _text(body, at)
            known = USERS.get(user or "")
            accepted = known is not None and known[0] == password or mode == "open"
            if not accepted:
                if mode == "silent":
                    return False
                self.send(0x20, bytes([0, 5]))
                return False
            self.prefix = known[1] if known else "robot-"
            self.send(0x20, bytes([0, 0]))
            return True
        if kind == 8:
            packet_id = body[:2]
            topic, _ = _text(body, 2)
            if mode == "open" or any(_covers(p, topic) for p in RULES[self.prefix]["subscribe"]):
                with self.server.lock:
                    self.server.subscribers.append((self, topic))
                self.send(0x90, packet_id + bytes([0]))
            else:
                self.server.denied += 1
                self.send(0x90, packet_id + bytes([0x80]))
            return True
        if kind == 3:
            topic, at = _text(body, 0)
            if mode != "open" and not any(_matches(topic, p) for p in RULES[self.prefix]["publish"]):
                self.server.denied += 1
                return False
            self.server.messages += 1
            with self.server.lock:
                targets = [c for c, f in self.server.subscribers if _matches(topic, f)]
            for target in targets:
                target.send(0x30, body)
            return True
        return True


@pytest.fixture
def fake():
    broker = FakeBroker()
    yield broker
    broker.stop()


def _bench(fake: FakeBroker) -> Broker:
    return Broker("127.0.0.1", fake.port, fake.metrics_url, ROBOT_PASSWORD, OPS_PASSWORD)


def test_every_scenario_passes_against_a_broker_that_keeps_its_rules(fake: FakeBroker) -> None:
    results = run(_bench(fake), run_id="t1")
    assert [r.name for r in results] == [name for name, _ in SCENARIOS]
    assert all(r.status == "pass" for r in results), [(r.name, r.detail) for r in results if r.status != "pass"]


def test_an_open_broker_fails_the_scenarios_about_protection() -> None:
    broker = FakeBroker(mode="open")
    try:
        failed = {r.name for r in run(_bench(broker), run_id="t2") if r.status != "pass"}
    finally:
        broker.stop()
    assert {"broker_refuses_anonymous", "broker_refuses_wrong_password", "broker_robot_cannot_read_everything", "broker_robot_cannot_command_robots"} <= failed
    assert "broker_state_reaches_the_operator" not in failed


def test_a_refusal_that_is_not_counted_is_a_failure() -> None:
    broker = FakeBroker(mode="uncounted")
    try:
        failed = {r.name: r.detail for r in run(_bench(broker), run_id="t3") if r.status != "pass"}
    finally:
        broker.stop()
    assert set(failed) == {"broker_robot_cannot_read_everything", "broker_robot_cannot_command_robots"}
    assert all("not counted" in detail for detail in failed.values())


def test_only_runs_the_scenarios_it_names(fake: FakeBroker) -> None:
    results = run(_bench(fake), run_id="t4", only=["broker_metrics", "broker_refuses_anonymous"])
    assert [r.name for r in results] == ["broker_metrics", "broker_refuses_anonymous"]


def test_a_scenario_that_raises_is_a_failure_and_the_run_goes_on(fake: FakeBroker, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(broker: Broker, run_id: str) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(broker_bench, "SCENARIOS", [("broken", broken), *SCENARIOS[:1]])
    results = run(_bench(fake), run_id="t5")
    assert [(r.name, r.status) for r in results] == [("broken", "fail"), ("broker_metrics", "pass")]
    assert "RuntimeError: boom" in results[0].detail


def test_a_broker_that_closes_without_answering_counts_as_a_refusal(fake: FakeBroker) -> None:
    fake.mode = "silent"
    results = run(_bench(fake), run_id="t6", only=["broker_refuses_anonymous", "broker_refuses_wrong_password"])
    assert [r.status for r in results] == ["pass", "pass"]
    assert all("(code -1)" in r.detail for r in results)


def test_the_client_reads_back_what_it_sends(fake: FakeBroker) -> None:
    ops = MqttClient("127.0.0.1", fake.port, "ops-direct")
    robot = MqttClient("127.0.0.1", fake.port, "robot-direct")
    try:
        assert ops.connect("ops", OPS_PASSWORD) == 0
        assert robot.connect("robot", ROBOT_PASSWORD) == 0
        assert ops.subscribe("hydra/swarm/#") == 0
        robot.publish("hydra/swarm/robot_9/joints", b"x" * 200)
        assert ops.next_message() == ("hydra/swarm/robot_9/joints", b"x" * 200)
        assert ops.next_message(0.2) is None
    finally:
        ops.close()
        robot.close()


def test_a_packet_that_never_comes_is_a_timeout_and_a_closed_socket_is_closed(fake: FakeBroker) -> None:
    client = MqttClient("127.0.0.1", fake.port, "ops-direct")
    try:
        assert client.connect("ops", OPS_PASSWORD) == 0
        with pytest.raises(TimeoutError):
            client.read_packet(0.2)
    finally:
        client.close()
    closed = MqttClient("127.0.0.1", fake.port, "robot-x")
    try:
        assert closed.connect("robot", "wrong-wrong-wrong-wrong") == 5
        with pytest.raises(Closed):
            closed.read_packet(1.0)
    finally:
        closed.close()


def test_the_length_of_a_long_packet_uses_more_than_one_byte() -> None:
    assert broker_bench._length(0) == b"\x00"
    assert broker_bench._length(127) == b"\x7f"
    assert broker_bench._length(128) == b"\x80\x01"
    assert broker_bench._length(16383) == b"\xff\x7f"
    assert broker_bench._length(16384) == b"\x80\x80\x01"


def test_the_command_line_needs_both_passwords(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("BROKER_ROBOT_PASSWORD", raising=False)
    monkeypatch.setenv("BROKER_OPS_PASSWORD", OPS_PASSWORD)
    assert main(["--wait", "0"]) == 2
    assert "BROKER_ROBOT_PASSWORD" in capsys.readouterr().err


def test_the_command_line_passes_and_fails_with_the_broker(fake: FakeBroker, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("BROKER_ROBOT_PASSWORD", ROBOT_PASSWORD)
    monkeypatch.setenv("BROKER_OPS_PASSWORD", OPS_PASSWORD)
    arguments = ["--mqtt-port", str(fake.port), "--metrics-url", fake.metrics_url, "--wait", "2"]
    assert main(arguments) == 0
    assert "BROKER_BENCH=PASS scenarios=7 failed=0" in capsys.readouterr().out
    fake.mode = "no-metrics"
    assert main(["--mqtt-port", str(fake.port), "--metrics-url", fake.metrics_url, "--wait", "1"]) == 1
    assert "BROKER_BENCH=FAIL the broker did not answer /metrics" in capsys.readouterr().out


def test_a_port_nobody_listens_on_is_a_failure_with_a_reason() -> None:
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    broker = Broker("127.0.0.1", port, "http://127.0.0.1:1", ROBOT_PASSWORD, OPS_PASSWORD)
    results = run(broker, run_id="t7", only=["broker_refuses_anonymous"])
    assert results[0].status == "fail"
    assert results[0].detail
