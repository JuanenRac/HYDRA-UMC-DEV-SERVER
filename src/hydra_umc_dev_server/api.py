# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/api.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
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
    GET  /v1/plugins                        every discovered plugin and its state
    POST /v1/plugins/rescan                 discover again from disk
    POST /v1/plugins/<name>/enable          body {"sha256": "..."}: the approved digest
    POST /v1/plugins/<name>/disable
    POST /v1/plugins/<name>/checks/<check>  run one check, bounded by a timeout
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import re
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .inventory import scan_project_manifests
from .plugins import PluginError, PluginRegistry

MAX_BODY_BYTES = 4096
MIN_TOKEN_LENGTH = 24

_ENABLE_RE = re.compile(r"^/v1/plugins/([a-z0-9-]+)/enable$")
_DISABLE_RE = re.compile(r"^/v1/plugins/([a-z0-9-]+)/disable$")
_CHECK_RE = re.compile(r"^/v1/plugins/([a-z0-9-]+)/checks/([a-z0-9-]+)$")


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


class DevServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], *, token: str, workspace_root: Path, plugins_root: Path) -> None:
        validate_bind(address[0], token)
        super().__init__(address, _Handler)
        self.token = token
        self.workspace_root = workspace_root
        self.plugins_root = plugins_root
        self.registry = PluginRegistry()
        self.registry.discover(plugins_root)


class _Handler(BaseHTTPRequestHandler):
    server: DevServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return  # request lines can carry paths; keep the server quiet

    # -- plumbing ----------------------------------------------------------
    def _send(self, status: int, payload: object) -> None:
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
        except PluginError as exc:
            self._send(404 if str(exc).startswith("no plugin") else 409, {"error": str(exc)})
            return
        self._send(404, {"error": "not found"})
