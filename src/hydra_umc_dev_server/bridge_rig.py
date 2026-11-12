# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/bridge_rig.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The rig of the bridge bench: one machine bridge, run in this process, in front of an emulator, behind the broker of `bench/docker-compose.bridges.yml`.

    python -m hydra_umc_dev_server.bridge_rig cnc        # the CNC bridge and the GRBL emulator of its tests
    python -m hydra_umc_dev_server.bridge_rig printer3d  # the 3D-printer bridge and the Moonraker stand-in of this package

The bridge packages are not dependencies of this repository: the workflow installs them (and `paho-mqtt`) from sibling checkouts, and the CNC rig finds the
emulator in `BRIDGE_CNC_DIR/tests` (default: `../../HYDRA-UMC-BRIDGE-CNC` from the bench folder). The bridge connects as the `bridge` identity of the
compose file (password in `BRIDGE_BENCH_BRIDGE_PASSWORD`). Next to it the rig serves a control side on `--control-port` that the scenarios use to see
what the emulator received (`GET /_bench/log`) and to drive the machine (`POST /_bench/reset`, `/_bench/alarm`, `/_bench/hold`, `/_bench/print`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from .fake_moonraker import FakeMoonraker


class RecordingSerial:
    """The serial seam of the bridge around the emulator: one lock, because the bridge reads on one thread and writes the stops on another, and a log of every byte written."""

    def __init__(self, emulator: object) -> None:
        self._emulator = emulator
        self._lock = threading.Lock()
        self.written: list[str] = []

    def write(self, data: bytes) -> int:
        with self._lock:
            self.written.append(data.decode("latin1"))
            return self._emulator.write(data)  # type: ignore[attr-defined]

    def readline(self) -> bytes:
        with self._lock:
            return self._emulator.readline()  # type: ignore[attr-defined]

    def close(self) -> object:
        return self._emulator.close()  # type: ignore[attr-defined]

    def drive(self, action: Callable[[object], None]) -> None:
        """Runs [action] on the emulator under the lock, without logging it as something the bridge wrote."""
        with self._lock:
            action(self._emulator)

    def forget(self) -> None:
        with self._lock:
            self.written.clear()


def _drain(emulator: object) -> None:
    while emulator.readline():  # type: ignore[attr-defined]
        pass


class CncControl:
    """What the control side does to the GRBL emulator."""

    def __init__(self, emulator: object) -> None:
        self.serial = RecordingSerial(emulator)
        self.reset()

    def reset(self) -> None:
        def clear(emulator: object) -> None:
            emulator.write(b"\x18")  # type: ignore[attr-defined]
            emulator.write(b"$X\n")  # type: ignore[attr-defined]
            emulator.write(b"\x18")  # type: ignore[attr-defined]
            _drain(emulator)

        self.serial.drive(clear)
        self.serial.forget()

    def alarm(self) -> None:
        self.serial.drive(lambda emulator: emulator.trigger_alarm())  # type: ignore[attr-defined]

    def hold(self) -> None:
        def into_hold(emulator: object) -> None:
            emulator.start_program()  # type: ignore[attr-defined]
            emulator.write(b"!")  # type: ignore[attr-defined]
            _drain(emulator)

        self.serial.drive(into_hold)
        self.serial.forget()


def serve_control(host: str, port: int, log: Callable[[], list[str]], actions: dict[str, Callable[[], None]]) -> ThreadingHTTPServer:
    """The control side of a rig whose machine has no HTTP of its own: `GET /_bench/log` and one `POST /_bench/<action>` per entry of [actions]."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def _send(self, status: int, body: object) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/_bench/log":
                return self._send(200, log())
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            action = actions.get(self.path.removeprefix("/_bench/")) if self.path.startswith("/_bench/") else None
            if action is None:
                return self._send(404, {"error": "not found"})
            action()
            self._send(200, {"result": "ok"})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _credentials() -> tuple[str, str]:
    password = os.environ.get("BRIDGE_BENCH_BRIDGE_PASSWORD", "")
    if not password:
        raise SystemExit("BRIDGE_BENCH_BRIDGE_PASSWORD must be set")
    return "bridge", password


def run_cnc(arguments: argparse.Namespace) -> None:
    folder = Path(os.environ.get("BRIDGE_CNC_DIR", Path(__file__).resolve().parents[3] / "HYDRA-UMC-BRIDGE-CNC"))
    sys.path.insert(0, str(folder / "tests"))
    from grbl_emulator import GrblEmulator  # type: ignore[import-not-found]
    from hydra_umc_sdk.bridge_contract import CellState
    from hydra_umc_bridge_cnc import CncMqttBridge
    from hydra_umc_bridge_cnc.mqtt_transport import run_forever

    control = CncControl(GrblEmulator())
    serve_control(
        arguments.control_host,
        arguments.control_port,
        lambda: list(control.serial.written),
        {"reset": control.reset, "alarm": control.alarm, "hold": control.hold},
    )
    user, password = _credentials()
    bridge = CncMqttBridge(control.serial, lambda: False, lambda: True, lambda: CellState.READY)
    run_forever(bridge, arguments.mqtt_host, arguments.mqtt_port, "bridge-cnc-bench", username=user, password=password)


def run_printer3d(arguments: argparse.Namespace) -> None:
    from hydra_umc_sdk.bridge_contract import CellState
    from hydra_umc_bridge_printer3d.mqtt_transport import PrinterMqttBridge, run_forever

    moonraker = FakeMoonraker(arguments.control_host, arguments.control_port).start()
    user, password = _credentials()
    bridge = PrinterMqttBridge(moonraker.base_url, lambda: CellState.READY)
    run_forever(bridge, arguments.mqtt_host, arguments.mqtt_port, "bridge-printer3d-bench", username=user, password=password)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hydra-umc-dev-server-bridge-rig", description="One machine bridge in front of an emulator, for the bridge bench.")
    parser.add_argument("bridge", choices=("cnc", "printer3d"))
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--control-host", default="127.0.0.1")
    parser.add_argument("--control-port", type=int, default=8099)
    arguments = parser.parse_args(argv)
    (run_cnc if arguments.bridge == "cnc" else run_printer3d)(arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
