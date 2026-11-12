# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/broker_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Scenarios for the broker bench (`bench/docker-compose.broker.yml`): the MQTT broker as a real container, spoken to with MQTT 3.1.1 over a socket.

The broker starts the way a production start does (credentials, a topic ACL, passwords of 16 characters or more), so what is checked is the
protection and not only the transport: nobody connects without the right password, a message published by one identity reaches the identity that
may read it, and a client that asks for more than its rule grants gets nothing. The client below is the few packets this needs (CONNECT, SUBSCRIBE,
PUBLISH at QoS 0) written with the standard library, so the same code is tested here against a stand-in broker and run in CI against the container.

Each scenario is one named check with a PASS / FAIL line; the run fails at the end (never at the first failure).
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from typing import Callable

from .bench import Result, call, prometheus_problem

#: How long a scenario waits for a packet before it decides nothing will come.
PACKET_WAIT_S = 5.0
#: How long a scenario listens to be sure that a message that must NOT arrive did not arrive.
SILENCE_S = 1.5

#: The return codes of a CONNACK that mean "refused" (bad user name or password, not authorized).
REFUSED_CODES = (4, 5)
#: The return code of a SUBACK for a filter the broker did not grant.
SUBACK_REFUSED = 0x80


def _length(size: int) -> bytes:
    out = bytearray()
    while True:
        byte, size = size % 128, size // 128
        out.append(byte | (0x80 if size else 0))
        if not size:
            return bytes(out)


def _text(value: str) -> bytes:
    raw = value.encode("utf8")
    return len(raw).to_bytes(2, "big") + raw


class Closed(Exception):
    """The broker closed the connection."""


class MqttClient:
    """One MQTT 3.1.1 connection to the broker (plain TCP, QoS 0)."""

    def __init__(self, host: str, port: int, client_id: str) -> None:
        self.client_id = client_id
        self.sock = socket.create_connection((host, port), timeout=PACKET_WAIT_S)
        self._next_id = 1

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _send(self, first: int, body: bytes) -> None:
        self.sock.sendall(bytes([first]) + _length(len(body)) + body)

    def _read_exactly(self, count: int) -> bytes:
        data = b""
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise Closed()
            data += chunk
        return data

    def read_packet(self, wait: float = PACKET_WAIT_S) -> tuple[int, int, bytes]:
        """The next packet as (type, flags, body). Raises Closed when the broker closed, TimeoutError when nothing came."""
        self.sock.settimeout(wait)
        try:
            first = self._read_exactly(1)[0]
            size, shift = 0, 0
            while True:
                byte = self._read_exactly(1)[0]
                size += (byte & 0x7F) << shift
                shift += 7
                if not byte & 0x80:
                    break
            body = self._read_exactly(size) if size else b""
        except (socket.timeout, TimeoutError) as error:
            raise TimeoutError("no packet within the wait") from error
        except (ConnectionResetError, BrokenPipeError) as error:
            raise Closed() from error
        return first >> 4, first & 0x0F, body

    def connect(self, username: str | None = None, password: str | None = None) -> int:
        """Sends CONNECT and returns the return code of the CONNACK (0: accepted). A broker that closes instead of answering is code -1."""
        flags = 0x02
        payload = _text(self.client_id)
        if username is not None:
            flags |= 0x80
            payload += _text(username)
        if password is not None:
            flags |= 0x40
            payload += _text(password)
        self._send(0x10, _text("MQTT") + bytes([4, flags]) + (30).to_bytes(2, "big") + payload)
        try:
            kind, _, body = self.read_packet()
        except Closed:
            return -1
        if kind != 2 or len(body) != 2:
            raise AssertionError(f"the answer to CONNECT was packet type {kind}, not a CONNACK")
        return body[1]

    def subscribe(self, topic_filter: str) -> int:
        """Sends SUBSCRIBE and returns the granted QoS of the SUBACK (0x80: refused). A broker that closes instead of answering is -1."""
        packet_id = self._next_id
        self._next_id += 1
        self._send(0x82, packet_id.to_bytes(2, "big") + _text(topic_filter) + bytes([0]))
        try:
            kind, _, body = self.read_packet()
        except Closed:
            return -1
        if kind != 9:
            raise AssertionError(f"the answer to SUBSCRIBE was packet type {kind}, not a SUBACK")
        return body[-1]

    def publish(self, topic: str, payload: bytes) -> None:
        self._send(0x30, _text(topic) + payload)

    def next_message(self, wait: float = PACKET_WAIT_S) -> tuple[str, bytes] | None:
        """The next PUBLISH as (topic, payload); None when nothing came in [wait] seconds or the broker closed."""
        deadline = time.monotonic() + wait
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            try:
                kind, _, body = self.read_packet(left)
            except (TimeoutError, Closed):
                return None
            if kind == 3:
                size = int.from_bytes(body[:2], "big")
                return body[2 : 2 + size].decode("utf8", "replace"), body[2 + size :]


class Broker:
    """The broker of the bench: where its MQTT port and its metrics are, and the two identities the compose file configures."""

    def __init__(self, host: str, mqtt_port: int, metrics_url: str, robot_password: str, ops_password: str) -> None:
        self.host = host
        self.mqtt_port = mqtt_port
        self.metrics_url = metrics_url
        self.robot_password = robot_password
        self.ops_password = ops_password

    def client(self, client_id: str) -> MqttClient:
        return MqttClient(self.host, self.mqtt_port, client_id)

    def connected(self, client_id: str, username: str, password: str) -> MqttClient:
        client = self.client(client_id)
        code = client.connect(username, password)
        assert code == 0, f"{username} with the right password was refused (CONNACK code {code})"
        return client

    def robot(self, run_id: str) -> MqttClient:
        return self.connected(f"robot-bench-{run_id}", "robot", self.robot_password)

    def ops(self, run_id: str) -> MqttClient:
        return self.connected(f"ops-bench-{run_id}", "ops", self.ops_password)

    def metrics(self) -> str:
        status, body = call(self.metrics_url, "GET", "/metrics")
        assert status == 200, f"/metrics answered {status}: {body}"
        return str(body)

    def metric(self, name: str) -> float:
        for line in self.metrics().splitlines():
            if line.startswith(name + " "):
                return float(line.split()[1])
        raise AssertionError(f"the metric {name} is not in /metrics")


def scenario_metrics(broker: Broker, run_id: str) -> str:
    text = broker.metrics()
    problem = prometheus_problem(text)
    assert not problem, f"/metrics is not valid Prometheus text: {problem}"
    for name in ("hydra_mqtt_connected_clients", "hydra_mqtt_messages_total", "hydra_mqtt_acl_denied_total"):
        broker.metric(name)
    return "/metrics is valid Prometheus text and holds the clients, messages and ACL refusals"


def scenario_refuses_anonymous(broker: Broker, run_id: str) -> str:
    client = broker.client(f"robot-anon-{run_id}")
    try:
        code = client.connect()
    finally:
        client.close()
    assert code in REFUSED_CODES or code == -1, f"a CONNECT with no credentials was accepted (code {code})"
    return f"a client with no credentials is refused (code {code})"


def scenario_refuses_wrong_password(broker: Broker, run_id: str) -> str:
    client = broker.client(f"robot-wrong-{run_id}")
    try:
        code = client.connect("robot", "this-is-not-the-password-0123")
    finally:
        client.close()
    assert code in REFUSED_CODES or code == -1, f"a CONNECT with a wrong password was accepted (code {code})"
    return f"a client with a wrong password is refused (code {code})"


def scenario_state_reaches_the_operator(broker: Broker, run_id: str) -> str:
    ops, robot = broker.ops(run_id), broker.robot(run_id)
    try:
        granted = ops.subscribe("hydra/swarm/#")
        assert granted != SUBACK_REFUSED and granted >= 0, f"the operator could not read the swarm topics (SUBACK {granted})"
        robot.publish("hydra/swarm/robot_1/joints", b'{"j1": 12.5}')
        got = ops.next_message()
        assert got == ("hydra/swarm/robot_1/joints", b'{"j1": 12.5}'), f"the operator got {got!r}, not the state the robot published"
    finally:
        ops.close()
        robot.close()
    return "a state published by a robot reaches the operator that reads the swarm topics"


def scenario_command_reaches_the_robot(broker: Broker, run_id: str) -> str:
    ops, robot = broker.ops(run_id), broker.robot(run_id)
    try:
        granted = robot.subscribe("hydra/swarm/robot_1/cmd/#")
        assert granted != SUBACK_REFUSED and granted >= 0, f"the robot could not read its commands (SUBACK {granted})"
        ops.publish("hydra/swarm/robot_1/cmd/jog", b'{"axis": "x"}')
        got = robot.next_message()
        assert got == ("hydra/swarm/robot_1/cmd/jog", b'{"axis": "x"}'), f"the robot got {got!r}, not the command the operator published"
    finally:
        ops.close()
        robot.close()
    return "a command published by the operator reaches the robot it is for"


def scenario_robot_cannot_read_everything(broker: Broker, run_id: str) -> str:
    before = broker.metric("hydra_mqtt_acl_denied_total")
    robot, ops = broker.robot(run_id), broker.ops(run_id)
    try:
        granted = robot.subscribe("hydra/swarm/#")
        assert granted in (SUBACK_REFUSED, -1), f"a robot subscribed to the whole swarm (SUBACK {granted})"
        ops.publish("hydra/swarm/robot_2/joints", b"{}")
        if granted != -1:
            heard = robot.next_message(SILENCE_S)
            assert heard is None, f"a robot that was refused the swarm still heard {heard!r}"
    finally:
        robot.close()
        ops.close()
    after = broker.metric("hydra_mqtt_acl_denied_total")
    assert after > before, f"the refusal is not counted (before {before:g}, after {after:g})"
    return "a robot that asks for the whole swarm is refused, hears nothing and the refusal is counted"


def scenario_robot_cannot_command_robots(broker: Broker, run_id: str) -> str:
    before = broker.metric("hydra_mqtt_acl_denied_total")
    ops, robot = broker.ops(run_id), broker.robot(run_id)
    try:
        assert ops.subscribe("hydra/swarm/#") not in (SUBACK_REFUSED, -1)
        robot.publish("hydra/swarm/robot_2/cmd/jog", b'{"axis": "z"}')
        heard = ops.next_message(SILENCE_S)
        assert heard is None, f"a command a robot was not allowed to give reached the operator: {heard!r}"
    finally:
        ops.close()
        robot.close()
    after = broker.metric("hydra_mqtt_acl_denied_total")
    assert after > before, f"the refusal is not counted (before {before:g}, after {after:g})"
    return "a robot that publishes a command is not delivered and the refusal is counted"


#: The scenarios of the broker bench, in order.
SCENARIOS: list[tuple[str, Callable[[Broker, str], str]]] = [
    ("broker_metrics", scenario_metrics),
    ("broker_refuses_anonymous", scenario_refuses_anonymous),
    ("broker_refuses_wrong_password", scenario_refuses_wrong_password),
    ("broker_state_reaches_the_operator", scenario_state_reaches_the_operator),
    ("broker_command_reaches_the_robot", scenario_command_reaches_the_robot),
    ("broker_robot_cannot_read_everything", scenario_robot_cannot_read_everything),
    ("broker_robot_cannot_command_robots", scenario_robot_cannot_command_robots),
]


def wait_until_ready(broker: Broker, seconds: float) -> bool:
    """True once /metrics answers 200; the container may need a while after `up`."""
    deadline = time.monotonic() + seconds
    while True:
        status, _ = call(broker.metrics_url, "GET", "/metrics")
        if status == 200:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1.0)


def run(broker: Broker, run_id: str | None = None, only: list[str] | None = None) -> list[Result]:
    """Every scenario, in order. A scenario that raises is a failure with the reason; the run goes on."""
    run_id = run_id or str(int(time.time()))
    results: list[Result] = []
    for name, scenario in SCENARIOS:
        if only and name not in only:
            continue
        started = time.monotonic()
        try:
            detail, status = scenario(broker, run_id), "pass"
        except AssertionError as error:
            detail, status = str(error), "fail"
        except Exception as error:  # a broken scenario must not stop the others
            detail, status = f"{type(error).__name__}: {error}", "fail"
        results.append(Result(name, status, detail, round(time.monotonic() - started, 3)))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hydra-umc-dev-server-broker-bench", description="Scenarios against the MQTT broker of the broker bench.")
    parser.add_argument("--host", default="127.0.0.1", help="where the MQTT port is published")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--metrics-url", default="http://127.0.0.1:9883")
    parser.add_argument("--wait", type=float, default=60.0, help="seconds to wait for /metrics before the scenarios start (0: do not wait)")
    parser.add_argument("--only", action="append", help="run only this scenario (repeatable)")
    arguments = parser.parse_args(argv)
    robot_password = os.environ.get("BROKER_ROBOT_PASSWORD", "")
    ops_password = os.environ.get("BROKER_OPS_PASSWORD", "")
    if not robot_password or not ops_password:
        print("BROKER_BENCH=FAIL BROKER_ROBOT_PASSWORD and BROKER_OPS_PASSWORD must both be set", file=sys.stderr)
        return 2
    broker = Broker(arguments.host, arguments.mqtt_port, arguments.metrics_url, robot_password, ops_password)
    if arguments.wait > 0 and not wait_until_ready(broker, arguments.wait):
        print(f"BROKER_BENCH=FAIL the broker did not answer /metrics within {arguments.wait:g} s")
        return 1
    results = run(broker, only=arguments.only)
    for result in results:
        print(f"{result.status.upper():4} {result.name}: {result.detail}")
    failed = [r.name for r in results if r.status != "pass"]
    print(f"BROKER_BENCH={'FAIL' if failed else 'PASS'} scenarios={len(results)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
