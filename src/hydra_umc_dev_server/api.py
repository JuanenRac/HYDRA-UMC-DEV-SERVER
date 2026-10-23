# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/api.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""A small authenticated HTTP API for this development host.

Deliberately narrow: it only listens on a loopback address, every route but
`/v1/health` needs `Authorization: Bearer <token>` (compared in constant
time), request bodies are capped, and nothing here runs a task, deploys or
changes what the server allows. It reports the workspace inventory and
drives the plugin lifecycle in plugins.py.

Routes
    GET  /v1/health                         no token; version and plugin count
    GET  /v1/inventory                      manifests found under the workspace
    GET  /v1/audit                          the last requests (method, path, status, time), newest last
    GET  /v1/plugins                        every discovered plugin and its state
    POST /v1/plugins/rescan                 discover again from disk
    POST /v1/plugins/<name>/enable          body {"sha256": "..."}: the approved digest
    POST /v1/plugins/<name>/disable
    POST /v1/plugins/<name>/checks/<check>  run one check, bounded by a timeout
    POST /v1/plugins/<name>/reports/<report>        run one report, bounded by a timeout and a size limit
    POST /v1/plugins/<name>/generators/<generator>  body {"params": {...}} (optional): run one generator;
                                                    the answer carries the generated file's name and text,
                                                    nothing is written to disk
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import re
import threading
import time
from collections import deque
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .inventory import scan_project_manifests
from .plugins import PluginError, PluginRegistry

MAX_BODY_BYTES = 4096
MIN_TOKEN_LENGTH = 24
# At most this many requests are served at the same time; the next one is answered 503 and closed at once, so a
# flood of connections cannot grow the number of threads without limit.
MAX_CONNECTIONS = 32
# How many requests the audit trail keeps (a ring: the oldest fall off).
AUDIT_ENTRIES = 500

_ENABLE_RE = re.compile(r"^/v1/plugins/([a-z0-9-]+)/enable$")
_DISABLE_RE = re.compile(r"^/v1/plugins/([a-z0-9-]+)/disable$")
_CHECK_RE = re.compile(r"^/v1/plugins/([a-z0-9-]+)/checks/([a-z0-9-]+)$")
_REPORT_RE = re.compile(r"^/v1/plugins/([a-z0-9-]+)/reports/([a-z0-9-]+)$")
_GENERATOR_RE = re.compile(r"^/v1/plugins/([a-z0-9-]+)/generators/([a-z0-9-]+)$")


class ApiConfigError(ValueError):
    """The API cannot be started with these settings."""


def validate_bind(host: str, token: str) -> None:
    """Refuse a non-loopback address and a token too short to be a secret."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ApiConfigError(f"host must be a loopback IP address, got {host!r}") from exc
    if not address.is_loopback:
        raise ApiConfigError(f"host must be a loopback address, got {host}")
    if not isinstance(token, str) or len(token) < MIN_TOKEN_LENGTH:
        raise ApiConfigError(f"the API token must be at least {MIN_TOKEN_LENGTH} characters")


_BUSY_RESPONSE = (
    b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: 30\r\n"
    b"Retry-After: 1\r\nConnection: close\r\n\r\n{\"error\": \"too many requests\"}"
)


class DevServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        token: str,
        workspace_root: Path,
        plugins_root: Path,
        max_connections: int = MAX_CONNECTIONS,
    ) -> None:
        validate_bind(address[0], token)
        if max_connections < 1:
            raise ApiConfigError("max_connections must be at least 1")
        super().__init__(address, _Handler)
        self.token = token
        self.workspace_root = workspace_root
        self.plugins_root = plugins_root
        self.registry = PluginRegistry()
        self.registry.discover(plugins_root)
        self._slots = threading.BoundedSemaphore(max_connections)
        # the audit trail never holds a body, a token or a query string
        self.audit: deque[dict[str, object]] = deque(maxlen=AUDIT_ENTRIES)

    def process_request(self, request, client_address) -> None:  # type: ignore[override]
        if not self._slots.acquire(blocking=False):
            try:
                request.sendall(_BUSY_RESPONSE)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address) -> None:  # type: ignore[override]
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class _Handler(BaseHTTPRequestHandler):
    server: DevServer  # type: ignore[assignment]
    # A client that connects and then goes quiet must not hold a thread forever.
    timeout = 15.0

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return  # request lines can carry paths; keep the server quiet

    # -- plumbing ----------------------------------------------------------
    def _send(self, status: int, payload: object) -> None:
        self.server.audit.append({
            "at": round(time.time(), 3),
            "method": self.command,
            "path": self.path.split("?", 1)[0][:200],
            "status": status,
            "client": self.client_address[0],
        })
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        scheme, _, presented = header.partition(" ")
        return scheme == "Bearer" and hmac.compare_digest(presented.encode("utf-8"), self.server.token.encode("utf-8"))

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, {"error": "Content-Length must be a number"})
            return None
        if length < 0:
            self._send(400, {"error": "Content-Length must not be negative"})
            return None
        if length > MAX_BODY_BYTES:
            self._send(413, {"error": f"the body may be at most {MAX_BODY_BYTES} bytes"})
            return None
        if length == 0:
            return {}
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            self._send(400, {"error": "the body is not valid JSON"})
            return None
        if not isinstance(body, dict):
            self._send(400, {"error": "the body must be a JSON object"})
            return None
        return body

    # -- routes ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/v1/health":
            self._send(200, {"status": "ok", "version": __version__, "plugins": len(self.server.registry.list())})
            return
        if not self._authorized():
            self._send(401, {"error": "a valid bearer token is required"})
            return
        if path == "/v1/inventory":
            result = scan_project_manifests(self.server.workspace_root)
            self._send(200, {"projects": [asdict(p) for p in result.projects], "issues": [asdict(i) for i in result.issues]})
        elif path == "/v1/plugins":
            self._send(200, {"plugins": self.server.registry.list(), "problems": self.server.registry.problems})
        elif path == "/v1/audit":
            self._send(200, {"entries": list(self.server.audit)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if not self._authorized():
            self._send(401, {"error": "a valid bearer token is required"})
            return
        body = self._read_json()
        if body is None:
            return
        registry = self.server.registry
        try:
            if path == "/v1/plugins/rescan":
                registry.discover(self.server.plugins_root)
                self._send(200, {"plugins": registry.list(), "problems": registry.problems})
                return
            enable = _ENABLE_RE.match(path)
            if enable:
                digest = body.get("sha256")
                if not isinstance(digest, str):
                    self._send(400, {"error": "sha256 (the approved digest) is required"})
                    return
                described = registry.enable(enable.group(1), digest)
                self._send(409 if described["state"] == "failed" else 200, described)
                return
            disable = _DISABLE_RE.match(path)
            if disable:
                self._send(200, registry.disable(disable.group(1)))
                return
            check = _CHECK_RE.match(path)
            if check:
                self._send(200, registry.run_check(check.group(1), check.group(2)))
                return
            report = _REPORT_RE.match(path)
            if report:
                self._send(200, registry.run_report(report.group(1), report.group(2)))
                return
            generator = _GENERATOR_RE.match(path)
            if generator:
                self._send(200, registry.run_generator(generator.group(1), generator.group(2), body.get("params")))
                return
        except PluginError as exc:
            self._send(404 if str(exc).startswith("no plugin") else 409, {"error": str(exc)})
            return
        self._send(404, {"error": "not found"})
