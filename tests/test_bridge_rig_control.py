# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_bridge_rig_control.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""What the rig of the bridge bench does to its emulator and how it starts a bridge (evidence: simulator).

The bridge packages are not dependencies of this repository, so the modules they would come from are stand-ins that record how the rig used them.
"""
from __future__ import annotations

import sys
import types

import pytest

from hydra_umc_dev_server import bridge_rig
from hydra_umc_dev_server.bridge_rig import CncControl


class FakeEmulator:
    """The part of the GRBL emulator that the control side touches: what it was given and what it still has to say."""

    def __init__(self, pending: list[bytes] | None = None) -> None:
        self.calls: list[tuple] = []
        self.pending = list(pending if pending is not None else [b"ok\n", b"[MSG:Reset]\n"])

    def write(self, data: bytes) -> int:
        self.calls.append(("write", data))
        return len(data)

    def readline(self) -> bytes:
        return self.pending.pop(0) if self.pending else b""

    def trigger_alarm(self) -> None:
        self.calls.append(("alarm",))

    def start_program(self) -> None:
        self.calls.append(("start",))

    def close(self) -> str:
        self.calls.append(("close",))
        return "closed"


def test_starting_the_control_clears_the_alarm_and_forgets_what_that_wrote() -> None:
    emulator = FakeEmulator()
    control = CncControl(emulator)
    assert emulator.calls == [("write", b"\x18"), ("write", b"$X\n"), ("write", b"\x18")]
    assert emulator.pending == []  # the answers of the reset were read away
    assert control.serial.written == []  # and none of it counts as something the bridge wrote


def test_what_the_bridge_writes_is_logged_and_reaches_the_emulator() -> None:
    emulator = FakeEmulator()
    control = CncControl(emulator)
    emulator.pending.append(b"ok\n")
    assert control.serial.write(b"G0 X1\n") == 6
    assert control.serial.readline() == b"ok\n"
    assert control.serial.written == ["G0 X1\n"]
    assert control.serial.close() == "closed"
    control.reset()
    assert control.serial.written == []  # a reset starts the log again


def test_an_alarm_is_raised_on_the_emulator_without_being_logged() -> None:
    emulator = FakeEmulator()
    control = CncControl(emulator)
    emulator.calls.clear()
    control.alarm()
    assert emulator.calls == [("alarm",)]
    assert control.serial.written == []


def test_a_hold_starts_a_program_and_sends_the_feed_hold() -> None:
    emulator = FakeEmulator()
    control = CncControl(emulator)
    emulator.calls.clear()
    emulator.pending = [b"<Hold:0>\n", b"ok\n"]
    control.hold()
    assert emulator.calls == [("start",), ("write", b"!")]
    assert emulator.pending == []
    assert control.serial.written == []


def test_the_command_line_picks_the_rig_and_hands_it_its_ports(monkeypatch) -> None:
    seen = []
    monkeypatch.setattr(bridge_rig, "run_cnc", lambda arguments: seen.append(("cnc", arguments)))
    monkeypatch.setattr(bridge_rig, "run_printer3d", lambda arguments: seen.append(("printer3d", arguments)))
    assert bridge_rig.main(["cnc"]) == 0
    assert bridge_rig.main(["printer3d", "--mqtt-host", "broker", "--mqtt-port", "1884", "--control-host", "0.0.0.0", "--control-port", "9001"]) == 0
    (first_name, first), (second_name, second) = seen
    assert first_name == "cnc" and (first.mqtt_host, first.mqtt_port, first.control_port) == ("127.0.0.1", 1883, 8099)
    assert second_name == "printer3d" and (second.mqtt_host, second.mqtt_port, second.control_host, second.control_port) == ("broker", 1884, "0.0.0.0", 9001)
    with pytest.raises(SystemExit):
        bridge_rig.main(["laser"])


def _module(monkeypatch, name: str, **members) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in members.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_the_cnc_rig_connects_the_bridge_to_the_emulator_and_serves_the_control_side(monkeypatch, tmp_path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "grbl_emulator.py").write_text(
        "class GrblEmulator:\n"
        "    def __init__(self):\n"
        "        self.sent = []\n"
        "    def write(self, data):\n"
        "        self.sent.append(data)\n"
        "        return len(data)\n"
        "    def readline(self):\n"
        "        return b''\n"
        "    def trigger_alarm(self):\n"
        "        self.sent.append(b'alarm')\n"
        "    def start_program(self):\n"
        "        self.sent.append(b'start')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BRIDGE_CNC_DIR", str(tmp_path))
    monkeypatch.setenv("BRIDGE_BENCH_BRIDGE_PASSWORD", "p" * 16)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "grbl_emulator", raising=False)
    ready = types.SimpleNamespace(name="READY")
    runs, controls, bridges = [], [], []

    class Bridge:
        def __init__(self, serial, *states) -> None:
            self.serial, self.states = serial, states
            bridges.append(self)

    _module(monkeypatch, "hydra_umc_sdk")
    _module(monkeypatch, "hydra_umc_sdk.bridge_contract", CellState=types.SimpleNamespace(READY=ready))
    _module(monkeypatch, "hydra_umc_bridge_cnc", CncMqttBridge=Bridge)
    _module(monkeypatch, "hydra_umc_bridge_cnc.mqtt_transport", run_forever=lambda bridge, host, port, client, **auth: runs.append((bridge, host, port, client, auth)))
    monkeypatch.setattr(bridge_rig, "serve_control", lambda host, port, log, actions: controls.append((host, port, log, actions)))
    arguments = types.SimpleNamespace(control_host="127.0.0.1", control_port=8099, mqtt_host="broker", mqtt_port=1884)

    bridge_rig.run_cnc(arguments)
    try:
        assert len(runs) == 1
        bridge, host, port, client, auth = runs[0]
        assert (host, port, client, auth) == ("broker", 1884, "bridge-cnc-bench", {"username": "bridge", "password": "p" * 16})
        assert bridge.states[0]() is False and bridge.states[1]() is True and bridge.states[2]() is ready
        control_host, control_port, log, actions = controls[0]
        assert (control_host, control_port) == ("127.0.0.1", 8099)
        assert set(actions) == {"reset", "alarm", "hold"}
        bridge.serial.write(b"G1 X2\n")
        assert log() == ["G1 X2\n"]  # the control side sees what the bridge wrote
        actions["reset"]()
        assert log() == []
    finally:
        sys.modules.pop("grbl_emulator", None)


def test_the_printer_rig_serves_the_stand_in_and_connects_the_bridge_to_it(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_BENCH_BRIDGE_PASSWORD", "q" * 16)
    ready = types.SimpleNamespace(name="READY")
    runs, started, bridges = [], [], []

    class Moonraker:
        base_url = "http://127.0.0.1:8099"

        def __init__(self, host, port) -> None:
            started.append((host, port))

        def start(self):
            return self

    class Bridge:
        def __init__(self, url, state) -> None:
            self.url, self.state = url, state
            bridges.append(self)

    _module(monkeypatch, "hydra_umc_sdk")
    _module(monkeypatch, "hydra_umc_sdk.bridge_contract", CellState=types.SimpleNamespace(READY=ready))
    _module(monkeypatch, "hydra_umc_bridge_printer3d")
    _module(
        monkeypatch,
        "hydra_umc_bridge_printer3d.mqtt_transport",
        PrinterMqttBridge=Bridge,
        run_forever=lambda bridge, host, port, client, **auth: runs.append((bridge, host, port, client, auth)),
    )
    monkeypatch.setattr(bridge_rig, "FakeMoonraker", Moonraker)
    arguments = types.SimpleNamespace(control_host="127.0.0.1", control_port=8099, mqtt_host="broker", mqtt_port=1884)

    bridge_rig.run_printer3d(arguments)

    assert started == [("127.0.0.1", 8099)]
    bridge, host, port, client, auth = runs[0]
    assert (host, port, client, auth) == ("broker", 1884, "bridge-printer3d-bench", {"username": "bridge", "password": "q" * 16})
    assert bridge.url == "http://127.0.0.1:8099" and bridge.state() is ready


def test_a_rig_without_the_password_of_the_bridge_does_not_start(monkeypatch) -> None:
    monkeypatch.delenv("BRIDGE_BENCH_BRIDGE_PASSWORD", raising=False)
    _module(monkeypatch, "hydra_umc_sdk")
    _module(monkeypatch, "hydra_umc_sdk.bridge_contract", CellState=types.SimpleNamespace(READY=None))
    _module(monkeypatch, "hydra_umc_bridge_printer3d")
    _module(monkeypatch, "hydra_umc_bridge_printer3d.mqtt_transport", PrinterMqttBridge=object, run_forever=lambda *a, **k: None)

    class Moonraker:
        base_url = "http://127.0.0.1:1"

        def __init__(self, host, port) -> None:
            pass

        def start(self):
            return self

    monkeypatch.setattr(bridge_rig, "FakeMoonraker", Moonraker)
    with pytest.raises(SystemExit):
        bridge_rig.run_printer3d(types.SimpleNamespace(control_host="127.0.0.1", control_port=1, mqtt_host="h", mqtt_port=1))
