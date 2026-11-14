# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/server_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Scenarios for the server bench (`bench/docker-compose.server.yml`): HYDRA-UMC-SERVER as a real container, spoken to over HTTP.

The server starts the way a production start does (the image of its own Dockerfile: a user that is not root, the signing key and the first administrator
given at start), so what is checked is the boundary and the login, not only the answers: the version route answers without a token, nothing else does,
a wrong password and a wrong token open nothing, the first administrator signs in and reads the settings, and a command to a robot that does not exist is
refused and not a failure of the server.

Each scenario is one named check with a PASS / FAIL line; the run fails at the end (never at the first failure).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Callable

from .bench import Result, call


class Server:
    """The server of the bench: where it listens and the first administrator the compose file configures."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url
        self.username = username
        self.password = password
        self._token: str | None = None

    def get(self, path: str, token: str | None = None) -> tuple[int, object]:
        return call(self.base_url, "GET", path, token=token)

    def post(self, path: str, body: object, token: str | None = None) -> tuple[int, object]:
        return call(self.base_url, "POST", path, body, token=token)

    def login(self, password: str | None = None) -> tuple[int, object]:
        return self.post("/api/login", {"username": self.username, "password": self.password if password is None else password})

    def token(self) -> str:
        """The token of the first administrator, asked for once."""
        if self._token is None:
            status, body = self.login()
            assert status == 200 and isinstance(body, dict) and isinstance(body.get("token"), str), f"the first administrator could not sign in: {status} {body}"
            self._token = body["token"]
        return self._token


def scenario_info_without_a_token(server: Server, run_id: str) -> str:
    status, body = server.get("/api/hydra-info")
    assert status == 200 and isinstance(body, dict), f"/api/hydra-info answered {status}: {body}"
    return "the version route answers without a token"


def scenario_refuses_without_a_token(server: Server, run_id: str) -> str:
    for method, path in (("GET", "/api/settings"), ("POST", "/api/settings"), ("GET", "/api/users"), ("POST", "/api/robot/1/command")):
        status, _ = server.get(path) if method == "GET" else server.post(path, {})
        assert status == 401, f"{method} {path} with no token answered {status}, not 401"
    return "settings, users and the robot command are refused (401) without a token"


def scenario_refuses_a_wrong_token(server: Server, run_id: str) -> str:
    status, _ = server.get("/api/settings", token="this.is.not-a-token")
    assert status in (401, 403), f"a wrong token answered {status}, not 401 or 403"
    return f"a wrong token is refused ({status})"


def scenario_refuses_a_wrong_password(server: Server, run_id: str) -> str:
    status, body = server.login("this-is-not-the-password-0123456789")
    assert status in (400, 401, 403), f"a wrong password answered {status}, not a refusal"
    assert not (isinstance(body, dict) and "token" in body), "a wrong password was given a token"
    return f"a wrong password is refused ({status}) and gets no token"


def scenario_first_administrator_signs_in(server: Server, run_id: str) -> str:
    server.token()
    return "the first administrator signs in and gets a token"


def scenario_administrator_reads_the_settings(server: Server, run_id: str) -> str:
    status, body = server.get("/api/settings", token=server.token())
    assert status == 200 and isinstance(body, dict), f"the settings answered {status}: {body}"
    assert "controllers" in body, f"the settings have no controllers list (keys: {sorted(body)[:8]})"
    return "the administrator reads the settings tree"


def scenario_command_to_a_robot_that_does_not_exist(server: Server, run_id: str) -> str:
    status, _ = server.post("/api/robot/987654/command", {"command": "stop"}, token=server.token())
    assert 400 <= status < 500, f"a command to a robot that does not exist answered {status}, not a refusal of the client"
    return f"a command to a robot that does not exist is refused ({status}), not a failure of the server"


#: The scenarios of the server bench, in order.
SCENARIOS: list[tuple[str, Callable[[Server, str], str]]] = [
    ("server_info_without_a_token", scenario_info_without_a_token),
    ("server_refuses_without_a_token", scenario_refuses_without_a_token),
    ("server_refuses_a_wrong_token", scenario_refuses_a_wrong_token),
    ("server_refuses_a_wrong_password", scenario_refuses_a_wrong_password),
    ("server_first_administrator_signs_in", scenario_first_administrator_signs_in),
    ("server_administrator_reads_the_settings", scenario_administrator_reads_the_settings),
    ("server_command_to_a_robot_that_does_not_exist", scenario_command_to_a_robot_that_does_not_exist),
]


def wait_until_ready(server: Server, seconds: float) -> bool:
    """True once /api/hydra-info answers 200; the container may need a while after `up`."""
    deadline = time.monotonic() + seconds
    while True:
        status, _ = server.get("/api/hydra-info")
        if status == 200:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1.0)


def run(server: Server, run_id: str | None = None, only: list[str] | None = None) -> list[Result]:
    """Every scenario, in order. A scenario that raises is a failure with the reason; the run goes on."""
    run_id = run_id or str(int(time.time()))
    results: list[Result] = []
    for name, scenario in SCENARIOS:
        if only and name not in only:
            continue
        started = time.monotonic()
        try:
            detail, status = scenario(server, run_id), "pass"
        except AssertionError as error:
            detail, status = str(error), "fail"
        except Exception as error:  # a broken scenario must not stop the others
            detail, status = f"{type(error).__name__}: {error}", "fail"
        results.append(Result(name, status, detail, round(time.monotonic() - started, 3)))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hydra-umc-dev-server-server-bench", description="Scenarios against the server of the server bench.")
    parser.add_argument("--url", default="http://127.0.0.1:18200", help="where the server listens")
    parser.add_argument("--wait", type=float, default=60.0, help="seconds to wait for /api/hydra-info before the scenarios start (0: do not wait)")
    parser.add_argument("--only", action="append", help="run only this scenario (repeatable)")
    arguments = parser.parse_args(argv)
    username = os.environ.get("SERVER_BENCH_ADMIN_USERNAME", "bench-admin")
    password = os.environ.get("SERVER_BENCH_ADMIN_PASSWORD", "")
    if not password:
        print("SERVER_BENCH=FAIL SERVER_BENCH_ADMIN_PASSWORD must be set", file=sys.stderr)
        return 2
    server = Server(arguments.url, username, password)
    if arguments.wait > 0 and not wait_until_ready(server, arguments.wait):
        print(f"SERVER_BENCH=FAIL the server did not answer /api/hydra-info within {arguments.wait:g} s")
        return 1
    results = run(server, only=arguments.only)
    for result in results:
        print(f"{result.status.upper():4} {result.name}: {result.detail}")
    failed = [r.name for r in results if r.status != "pass"]
    print(f"SERVER_BENCH={'FAIL' if failed else 'PASS'} scenarios={len(results)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
