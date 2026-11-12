# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/fake_moonraker.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A stand-in Moonraker for the bridge bench: the few REST endpoints a printer bridge speaks, with the print state a real Klipper keeps.

It answers in the wire shape of the real thing (a `result` envelope, `{"result": "ok"}` for an action) and remembers every request, so a scenario can
ask afterwards what the bridge really sent. Under `/_bench/` it has a control side that is not part of Moonraker: `GET /_bench/log` lists the requests,
`POST /_bench/reset` clears the log and the state and `POST /_bench/print` puts a print in progress. Nothing here touches a printer; the run proves the bridge's behaviour, not a machine's.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

#: The files the stand-in printer holds (a start for any other name is a 404 on the metadata, like the real one).
FILES = ("part.gcode",)


class PrinterState:
    """What the stand-in printer is doing; the lock lets the handler threads share it."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.klippy = "ready"
        self.print_state = "standby"
        self.log: list[str] = []

    def act(self, path: str) -> bool:
        """Applies an action endpoint; False when the real one would refuse it from the state the printer is in."""
        if path == "/printer/emergency_stop":
            self.klippy, self.print_state = "shutdown", "error"
            return True
        if self.klippy != "ready":
            return False
        if path == "/printer/print/start":
            if self.print_state == "printing":
                return False
            self.print_state = "printing"
        elif path == "/printer/print/pause":
            if self.print_state != "printing":
                return False
            self.print_state = "paused"
        elif path == "/printer/print/resume":
            if self.print_state != "paused":
                return False
            self.print_state = "printing"
        elif path == "/printer/print/cancel":
            if self.print_state not in ("printing", "paused"):
                return False
            self.print_state = "cancelled"
        else:
            return False
        return True


class _Handler(BaseHTTPRequestHandler):
    server: "FakeMoonraker"

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, status: int, body: Any) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 - the name the base class asks for
        parsed = urlparse(self.path)
        state = self.server.state
        with state.lock:
            if parsed.path == "/_bench/log":
                return self._send(200, list(state.log))
            state.log.append(f"GET {parsed.path}")
            if parsed.path == "/printer/info":
                return self._send(200, {"result": {"state": state.klippy, "state_message": f"Printer is {state.klippy}"}})
            if parsed.path == "/printer/objects/query":
                return self._send(200, {"result": {"status": {"print_stats": {"state": state.print_state}}}})
            if parsed.path == "/server/files/metadata":
                name = parse_qs(parsed.query).get("filename", [""])[0]
                if name in FILES:
                    return self._send(200, {"result": {"filename": name}})
                return self._send(404, {"error": {"code": 404, "message": "file not found"}})
        self._send(404, {"error": {"code": 404, "message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        state = self.server.state
        with state.lock:
            if path == "/_bench/reset":
                state.reset()
                return self._send(200, {"result": "ok"})
            if path == "/_bench/print":
                state.print_state = "printing"
                return self._send(200, {"result": "ok"})
            state.log.append(f"POST {path}")
            if state.act(path):
                return self._send(200, {"result": "ok"})
        self._send(400, {"error": {"code": 400, "message": "not allowed in the state the printer is in"}})


class FakeMoonraker(ThreadingHTTPServer):
    """The stand-in on one port of the loopback interface (0: the system picks one)."""

    daemon_threads = True

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        super().__init__((host, port), _Handler)
        self.state = PrinterState()

    @property
    def base_url(self) -> str:
        host = self.server_address[0]
        return f"http://{host.decode() if isinstance(host, bytes) else host}:{self.server_address[1]}"

    def start(self) -> "FakeMoonraker":
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
