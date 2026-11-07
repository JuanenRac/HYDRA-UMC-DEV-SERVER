# =============================================================================
# HYDRA-UMC-DEV-SERVER - tools/code_server_tls_check.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Starts the real code-server with the arguments of the unit the plan writes for a TLS station, and talks to it (what the manual workflow runs).

It needs `code-server` and `openssl` on the machine. A throw-away certificate for 127.0.0.1 is made, the `ExecStart` line is taken from the unit text that
`provision._systemd_unit_text` builds for a profile with TLS files (only the port is changed to a free one), and code-server is started with those
arguments, a throw-away home and a throw-away password in the environment (the unit reads a hash from its environment file; `code-server hash-password` asks on a terminal, which a check cannot answer). Then it checks, from outside:

  * `GET /healthz` over HTTPS with the certificate as the only trusted root answers 200;
  * the same address over plain HTTP is refused or only sent to HTTPS, never served;
  * a client that does not trust the certificate refuses it;
  * `GET /` without logging in is sent to the login page and never to the editor.

Prints `CODE_SERVER_TLS=PASS` or `CODE_SERVER_TLS=FAIL <why>`. The port is on loopback and the folders are in a temporary directory that is removed.
"""
from __future__ import annotations

import http.client
import os
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hydra_umc_dev_server.provision import _systemd_unit_text  # noqa: E402
from hydra_umc_dev_server.remote_station import RemoteStationProfile  # noqa: E402

PASSWORD = "throw-away-password-for-the-check"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def make_certificate(folder: Path) -> tuple[Path, Path]:
    cert, key = folder / "station.crt", folder / "station.key"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "2", "-subj", "/CN=hydra-dev-station",
         "-addext", "subjectAltName=IP:127.0.0.1"],
        check=True, capture_output=True, timeout=60,
    )
    return cert, key


def exec_arguments(cert: Path, key: Path, port: int) -> list[str]:
    profile = RemoteStationProfile.from_dict(
        {
            "identity": {"user": "hydra-dev-station", "home": "/srv/hydra-umc-dev/station", "workspace_subdir": "workspace"},
            "remote_access": {"kind": "code-server", "port": port, "bind_address": "127.0.0.1", "tls_cert_file": str(cert), "tls_key_file": str(key)},
            "required_tools": [{"name": "git", "min_version": "2.40", "required": True}],
            "min_free_disk_gb": 1.0,
        }
    )
    line = next(row for row in _systemd_unit_text(profile).splitlines() if row.startswith("ExecStart="))
    return shlex.split(line[len("ExecStart="):])[1:]


def get(port: int, path: str, context: ssl.SSLContext | None) -> tuple[int, str, str]:
    connection: http.client.HTTPConnection
    if context is None:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    else:
        connection = http.client.HTTPSConnection("127.0.0.1", port, timeout=10, context=context)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.getheader("Location") or "", response.read(2000).decode("utf-8", "replace")
    finally:
        connection.close()


def main() -> int:
    if shutil.which("code-server") is None or shutil.which("openssl") is None:
        print("CODE_SERVER_TLS=FAIL needs code-server and openssl on the machine")
        return 1
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="hydra-tls-") as scratch:
        folder = Path(scratch)
        cert, key = make_certificate(folder)
        port = free_port()
        arguments = exec_arguments(cert, key, port)
        print("arguments:", " ".join(arguments).replace(str(folder), "<tmp>"))
        home = folder / "home"
        (home / ".config").mkdir(parents=True)
        (home / ".local" / "share").mkdir(parents=True)
        env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local" / "share"), "PASSWORD": PASSWORD}
        child = subprocess.Popen(["code-server", *arguments, str(folder)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            trusted = ssl.create_default_context(cafile=str(cert))
            deadline = time.monotonic() + 90
            health = None
            while time.monotonic() < deadline and child.poll() is None:
                try:
                    health = get(port, "/healthz", trusted)
                    break
                except (OSError, http.client.HTTPException):
                    time.sleep(1)
            if health is None:
                tail = (child.stdout.read(1500) if child.poll() is not None and child.stdout else b"").decode("utf-8", "replace")
                problems.append(f"code-server never answered over HTTPS (exit {child.poll()}): {tail[-300:]}")
            else:
                print(f"https /healthz: {health[0]} {health[2][:60]}")
                if health[0] != 200:
                    problems.append(f"/healthz over TLS answered {health[0]}")
                try:
                    status, location, body = get(port, "/healthz", None)
                    print(f"plain http: {status} {location}")
                    # code-server answers plain HTTP on its TLS port with a redirect to HTTPS; the content itself must never be served
                    if not (status in (301, 302, 303, 307, 308) and location.startswith("https://")) or "lastHeartbeat" in body:
                        problems.append(f"plain HTTP was served ({status} {location!r})")
                except (OSError, http.client.HTTPException):
                    print("plain http: refused")
                try:
                    get(port, "/healthz", ssl.create_default_context())
                    problems.append("a client that does not trust the certificate was served")
                except ssl.SSLError:
                    print("untrusting client: refused")
                except OSError as error:
                    if "CERTIFICATE_VERIFY_FAILED" in str(error):
                        print("untrusting client: refused")
                    else:
                        problems.append(f"untrusting client: unexpected error {error}")
                status, location, _ = get(port, "/", trusted)
                print(f"https /: {status} {location}")
                if status not in (301, 302, 303, 307) or "login" not in location:
                    problems.append(f"/ without a login went to {status} {location!r}, not to the login page")
        finally:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
    for problem in problems:
        print(f"CODE_SERVER_TLS_PROBLEM {problem}")
    print("CODE_SERVER_TLS=PASS" if not problems else f"CODE_SERVER_TLS=FAIL {len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
