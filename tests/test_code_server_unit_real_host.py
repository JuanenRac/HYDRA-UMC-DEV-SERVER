# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_code_server_unit_real_host.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The unit of the code-server station against a real systemd.

The text of the unit is built by `provision._systemd_unit_text`; these tests give it to a real systemd:

  * `systemd-analyze verify` accepts it (every directive is known, the sections are well formed);
  * with the stand-in below as `ExecStart` (code-server itself is not installed on a test host), a unit started as root with the
    account of the station does not start without the password file, starts with it, can write in the two directories code-server
    writes to, reads the password hash from the environment file, and cannot write anywhere else in the home.

Only the program is replaced; every other line of the unit is the one the plan writes. What this does NOT prove is that the real
code-server runs under these restrictions (that needs the program, a station and a browser). The tests are skipped, saying why, on
a host that is not Linux with systemd as its init, or when the tests do not run as root.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from hydra_umc_dev_server.provision import _systemd_unit_text
from hydra_umc_dev_server.remote_station import RemoteStationProfile

_STAND_IN = (
    "/bin/sh -c 'echo ran > \"$XDG_CONFIG_HOME/code-server/ran\"; env > \"$XDG_CONFIG_HOME/code-server/env\"; "
    "(echo x > \"$HOME/stray\") 2>/dev/null; echo $? > \"$XDG_DATA_HOME/code-server/stray_status\"; sleep 30'"
)


def _skip_reason(need_root: bool) -> str | None:
    if not sys.platform.startswith("linux"):
        return "not a Linux host"
    if not shutil.which("systemctl") or not shutil.which("systemd-analyze"):
        return "systemd is not installed"
    try:
        with open("/proc/1/comm", encoding="utf-8") as handle:
            if handle.read().strip() != "systemd":
                return "systemd is not the init of this host"
    except OSError:
        return "cannot read /proc/1/comm"
    if need_root and (not hasattr(os, "geteuid") or os.geteuid() != 0):
        return "the unit is started as root and the tests are not"
    if need_root:
        probe = subprocess.run(["systemctl", "is-system-running"], capture_output=True, text=True, timeout=20)
        if probe.stdout.strip() in ("", "offline"):
            return "the system manager of systemd is not running"
    return None


def _profile(home: str) -> RemoteStationProfile:
    return RemoteStationProfile.from_dict(
        {
            "identity": {"user": "nobody", "home": home, "workspace_subdir": "workspace"},
            "remote_access": {"kind": "code-server", "port": 8722, "bind_address": "127.0.0.1", "allow_public_bind": False},
            "required_tools": [{"name": "git", "min_version": "2.40", "required": True}],
            "min_free_disk_gb": 1.0,
        }
    )


def _with_stand_in(text: str) -> str:
    return "\n".join(f"ExecStart={_STAND_IN}" if line.startswith("ExecStart=") else line for line in text.splitlines()) + "\n"


class UnitVerifyTests(unittest.TestCase):
    reason = _skip_reason(need_root=False)

    def setUp(self) -> None:
        if self.reason:
            self.skipTest(self.reason)

    def test_systemd_analyze_accepts_the_unit_of_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp) / "hydra-umc-dev-station-test.service"
            unit.write_text(_with_stand_in(_systemd_unit_text(_profile("/srv/hydra-umc-dev/station"))), encoding="utf-8")
            result = subprocess.run(["systemd-analyze", "verify", str(unit)], capture_output=True, text=True, timeout=60)
            # what a wrong unit looks like to systemd: a directive or section it does not know, or a value it cannot parse. The
            # account, the password file and the install target belong to the host, not to the text of the unit.
            problems = [
                line for line in (result.stdout + result.stderr).splitlines()
                if re.search(r"unknown (key|section|lvalue)|failed to parse|invalid|bad unit|assignment outside of section", line, re.I)
            ]
            self.assertEqual(problems, [], result.stderr)


class UnitRunsTests(unittest.TestCase):
    reason = _skip_reason(need_root=True)

    def setUp(self) -> None:
        if self.reason:
            self.skipTest(self.reason)
        self.home = tempfile.mkdtemp(dir="/var/lib", prefix="hydra-station-test-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.name = f"hydra-umc-station-test-{uuid.uuid4().hex[:8]}.service"
        self.unit_path = Path("/run/systemd/system") / self.name
        self.addCleanup(self._cleanup_unit)
        profile = _profile(self.home)
        for path in (self.home, f"{self.home}/workspace", f"{self.home}/.config", f"{self.home}/.local", f"{self.home}/.local/share",
                     f"{self.home}/.config/code-server", f"{self.home}/.local/share/code-server"):
            os.makedirs(path, exist_ok=True)
            shutil.chown(path, "nobody")
        os.chmod(self.home, 0o700)
        self.unit_path.write_text(_with_stand_in(_systemd_unit_text(profile)), encoding="utf-8")
        subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=60)

    def _cleanup_unit(self) -> None:
        subprocess.run(["systemctl", "stop", self.name], capture_output=True, timeout=60)
        if self.unit_path.exists():
            self.unit_path.unlink()
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=60)

    def _state(self) -> str:
        return subprocess.run(["systemctl", "is-active", self.name], capture_output=True, text=True, timeout=30).stdout.strip()

    def _wait_for(self, path: str, seconds: float = 15.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if os.path.exists(path) and os.path.getsize(path) >= 0 and os.path.exists(f"{self.home}/.local/share/code-server/stray_status"):
                return True
            time.sleep(0.2)
        return False

    def test_it_does_not_start_without_the_password_file_and_then_it_does(self):
        subprocess.run(["systemctl", "start", self.name], capture_output=True, timeout=60)
        self.assertNotEqual(self._state(), "active", "no password file, no station")
        self.assertFalse(os.path.exists(f"{self.home}/.config/code-server/ran"))

        env_file = Path(self.home) / "code-server.env"
        env_file.write_text("HASHED_PASSWORD='$argon2i$test'\n", encoding="utf-8")
        shutil.chown(env_file, "nobody")
        os.chmod(env_file, 0o600)
        started = subprocess.run(["systemctl", "start", self.name], capture_output=True, text=True, timeout=60)
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertTrue(self._wait_for(f"{self.home}/.config/code-server/ran"), "the stand-in never wrote in its config directory")
        self.assertEqual(self._state(), "active")

        self.assertIn("HASHED_PASSWORD=$argon2i$test", Path(f"{self.home}/.config/code-server/env").read_text(encoding="utf-8").splitlines())
        self.assertEqual(Path(f"{self.home}/.local/share/code-server/stray_status").read_text(encoding="utf-8").strip() != "0", True,
                         "the unit must not let the station write in the rest of its home")
        self.assertFalse(os.path.exists(f"{self.home}/stray"))


if __name__ == "__main__":
    unittest.main()
