# =============================================================================
# HYDRA-UMC-SDK - tools/canonical/health_route.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The uniform `GET /health` of the Python services of the family, closed unless the operator opens it, written once.

This file has a single canonical copy (`tools/canonical/health_route.py` of HYDRA-UMC-SDK) that is vendored, byte for byte, into the services that list it in
`PER_REPOSITORY_FILES` of `tools/sync_repo_tools.py`; the script keeps the copies identical. It needs nothing but the standard library, so a service adopts it
whether or not it carries `http_common.py`, and nothing in it is specific to a service: the name of the service comes from the package the file sits in.

Every service of the family can answer `GET /health` with the same small body, `{"status": "ok", "service": ..., "version": ...}`, so that a watchdog or the
service registry can read the health of any of them the same way. It is an opt-in:

* Closed (the default): the route answers `404` like any route that does not exist, and nothing else about the service changes.
* Open (`--health-open` on the command line, or `HYDRA_UMC_<SERVICE>_HEALTH_OPEN=1` where `<SERVICE>` is the package name in capitals, for example
  `HYDRA_UMC_COGNITIVE_NODE_HEALTH_OPEN`): the route answers `200` to a caller on loopback. A caller that is not on loopback must present the bearer token of the
  service (`401` otherwise); a service without a token never answers a caller that is not on loopback.

The body names the service and its version and nothing else: no path, no configuration, no secret. The handler may set `metrics_service` and `metrics_version`
(the same attributes the `/metrics` route reads); without them the service is named after the package and the version is `unknown`.

A service adopts it in three steps: put `HealthRouteMixin` before `BaseHTTPRequestHandler` in the bases of the handler, call `self.serve_health(token)` first in
`do_GET` (`token` is the bearer token of the service, or `None`), and set `server.health_open = health_open_requested(flag)` where it starts the server.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import os
from http.server import BaseHTTPRequestHandler

_PACKAGE = (__package__ or __name__).split(".", 1)[0]
HEALTH_PATH = "/health"
ENV_HEALTH_OPEN = f"{_PACKAGE.upper()}_HEALTH_OPEN"
_TRUE = {"1", "true", "yes", "on"}


def health_open_requested(flag: bool = False) -> bool:
    """Whether the operator opened `GET /health`: the flag of the command line, or the environment variable set to 1/true/yes/on."""
    return bool(flag) or os.environ.get(ENV_HEALTH_OPEN, "").strip().lower() in _TRUE


def _is_loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _write(handler: BaseHTTPRequestHandler, status: int, payload: object) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _bearer_ok(handler: BaseHTTPRequestHandler, expected: str) -> bool:
    scheme, _, presented = handler.headers.get("Authorization", "").partition(" ")
    return scheme == "Bearer" and hmac.compare_digest(presented.strip().encode("utf-8"), expected.encode("utf-8"))


class HealthRouteMixin(BaseHTTPRequestHandler):
    """Put it before `BaseHTTPRequestHandler` in the bases of the handler and ask `serve_health` first in `do_GET`. The server opens the route with `health_open = True`."""

    def serve_health(self, token: str | None = None) -> bool:
        """Answer `GET /health` and return True; return False for any other path so the handler carries on."""
        if self.path.split("?", 1)[0] != HEALTH_PATH:
            return False
        if not getattr(self.server, "health_open", False):
            _write(self, 404, {"error": "not found"})
            return True
        identity_key = getattr(self.server, "identity_key", None)
        if identity_key is not None:
            # the identity of HYDRA-UMC-SERVER is on (server_identity.py): nothing is open, not even this route and not even on loopback
            from .server_identity import accepts

            if not accepts(self, token or "", identity_key):
                _write(self, 401, {"error": "a valid identity is required"})
                return True
        elif not _is_loopback(self.client_address[0]) and (not token or not _bearer_ok(self, token)):
            _write(self, 401, {"error": "a valid bearer token is required"})
            return True
        _write(
            self,
            200,
            {
                "status": "ok",
                "service": getattr(self, "metrics_service", "") or _PACKAGE.replace("_", "-"),
                "version": getattr(self, "metrics_version", "") or "unknown",
            },
        )
        return True
