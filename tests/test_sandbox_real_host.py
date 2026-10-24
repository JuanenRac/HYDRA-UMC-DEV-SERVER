# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_sandbox_real_host.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The sandbox against a real kernel: the command lines of sandbox.py are only strings until a host runs them.

These tests run the real `SandboxedLauncher` with `systemd-run` or `bubblewrap` and look at what the task could and could not do
(read the home of the service user, write outside its workspace, use the network, use more memory than its limit). They need a Linux
host whose systemd lets the user start units (as root, or with a user instance); anywhere else every test is skipped, and the pure tests
of test_sandbox_taskflow.py still cover the command lines. A skipped run proves nothing about the sandbox: the line printed by the
skip says why.

The workspace is created under /var/tmp, where `PrivateTmp` would hide it from the unit if the sandbox did not bind it in: these tests
are the ones that found that out (status 226 on a real systemd) and keep it fixed.
"""
import os
import shutil
import sys
import tempfile
import time
import unittest

from hydra_umc_dev_server.runner import SubprocessLauncher
from hydra_umc_dev_server.sandbox import SandboxSpec, SandboxedLauncher, detect_sandbox


def _usable(mode: str) -> str | None:
    """None when the sandbox `mode` works on this host, else the reason it does not."""
    if os.name != "posix" or not sys.platform.startswith("linux"):
        return "not a Linux host"
    try:
        used = detect_sandbox(mode)
    except Exception as error:  # noqa: BLE001 - any reason is a reason to skip
        return str(error)
    if used != mode:
        return f"{mode} is not installed"
    workspace = tempfile.mkdtemp(dir="/var/tmp")
    try:
        launcher = SandboxedLauncher(SubprocessLauncher(), SandboxSpec(mode=mode))
        handle = launcher.spawn(("/bin/true",), cwd=workspace, env={"PATH": "/usr/bin:/bin"})
        deadline = time.monotonic() + 20
        while handle.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        code = handle.poll()
        return None if code == 0 else f"the probe run exited with {code}: {handle.stderr_tail().strip()[:200]}"
    except Exception as error:  # noqa: BLE001
        return str(error)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _run(mode: str, script: str, workspace: str, spec: SandboxSpec, timeout: float = 60.0) -> tuple[int | None, str, str]:
    launcher = SandboxedLauncher(SubprocessLauncher(), spec)
    assert launcher.used == mode
    handle = launcher.spawn(("/bin/sh", "-c", script), cwd=workspace, env={"PATH": "/usr/bin:/bin"})
    deadline = time.monotonic() + timeout
    while handle.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if handle.poll() is None:
        handle.kill_tree()
    return handle.poll(), handle.stdout_tail(), handle.stderr_tail()


class _RealHostMixin:
    mode = ""
    reason: str | None = None

    def setUp(self) -> None:
        if self.reason:
            self.skipTest(f"{self.mode}: {self.reason}")
        self.workspace = tempfile.mkdtemp(dir="/var/tmp")
        self.addCleanup(shutil.rmtree, self.workspace, True)
        self.home_marker = os.path.join(os.path.expanduser("~"), ".hydra-sandbox-probe")
        with open(self.home_marker, "w", encoding="utf-8") as handle:
            handle.write("secret")
        self.addCleanup(lambda: os.path.exists(self.home_marker) and os.remove(self.home_marker))

    def spec(self, **extra) -> SandboxSpec:
        return SandboxSpec(mode=self.mode, **extra)

    def test_the_task_writes_in_its_workspace_and_nowhere_else(self):
        outside = os.path.join(os.path.expanduser("~"), "written-by-the-task")
        self.addCleanup(lambda: os.path.exists(outside) and os.remove(outside))
        code, out, err = _run(
            self.mode,
            f"echo inside > {self.workspace}/out.txt; echo in=$?; (echo no > {outside}) 2>/dev/null; echo outside=$?",
            self.workspace,
            self.spec(),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("in=0", out)
        self.assertNotIn("outside=0", out)
        self.assertFalse(os.path.exists(outside))
        with open(os.path.join(self.workspace, "out.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), "inside")

    def test_the_task_cannot_read_the_home_of_the_service_user(self):
        code, out, _err = _run(self.mode, f"cat {self.home_marker} 2>/dev/null; echo read=$?", self.workspace, self.spec())
        self.assertNotIn("secret", out)
        self.assertNotIn("read=0", out)

    def test_the_task_has_no_network_unless_the_policy_opens_it(self):
        script = "cat /proc/net/dev | tail -n +3 | cut -d: -f1 | tr -d ' ' | grep -v '^lo$' | wc -l"
        code, out, err = _run(self.mode, script, self.workspace, self.spec(network=False))
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "0", "no interface besides loopback inside the sandbox")


class SystemdRunRealHostTests(_RealHostMixin, unittest.TestCase):
    mode = "systemd-run"
    reason = _usable("systemd-run")

    def test_the_memory_limit_of_the_policy_is_enforced_by_the_kernel(self):
        script = 'python3 -c "x = bytearray(300 * 1024 * 1024); print(len(x))"; echo survived=$?'
        code, out, _err = _run(self.mode, script, self.workspace, self.spec(memory_max="64M"))
        self.assertNotIn("survived=0", out, "a task that takes five times its memory limit must not finish")
        self.assertNotEqual(code, 0)

    def test_a_task_inside_the_memory_limit_still_runs(self):
        script = 'python3 -c "x = bytearray(8 * 1024 * 1024); print(len(x))"'
        code, out, err = _run(self.mode, script, self.workspace, self.spec(memory_max="256M"))
        self.assertEqual(code, 0, err)
        self.assertIn(str(8 * 1024 * 1024), out)

    def test_the_task_limit_stops_a_fork_bomb_from_growing(self):
        script = "i=0; while [ $i -lt 60 ]; do sleep 5 & i=$((i+1)); done; echo started=$(jobs -p | wc -l)"
        code, out, _err = _run(self.mode, script, self.workspace, self.spec(tasks_max=10), timeout=30)
        started = [line for line in out.splitlines() if line.startswith("started=")]
        if started:
            self.assertLess(int(started[0].split("=")[1]), 60, "TasksMax must have refused some of the forks")


class SystemdRunWorkspaceTests(unittest.TestCase):
    reason = _usable("systemd-run")

    def setUp(self) -> None:
        if self.reason:
            self.skipTest(f"systemd-run: {self.reason}")

    def test_a_workspace_under_tmp_is_bound_into_the_unit(self):
        for base in ("/tmp", "/var/tmp"):
            workspace = tempfile.mkdtemp(dir=base)
            self.addCleanup(shutil.rmtree, workspace, True)
            code, out, err = _run("systemd-run", f"echo here > {workspace}/f; cat {workspace}/f", workspace, SandboxSpec(mode="systemd-run"))
            self.assertEqual(code, 0, f"{base}: {err}")
            self.assertEqual(out.strip(), "here")

    def test_a_workspace_the_unit_cannot_reach_is_refused_before_it_runs(self):
        from hydra_umc_dev_server.sandbox import SandboxUnavailableError

        launcher = SandboxedLauncher(SubprocessLauncher(), SandboxSpec(mode="systemd-run"))
        for hidden in ("/home/service/ws", "/root/ws", "/run/user/1000/ws"):
            with self.assertRaises(SandboxUnavailableError):
                launcher.spawn(("/bin/true",), cwd=hidden, env={"PATH": "/usr/bin:/bin"})


class BubblewrapRealHostTests(_RealHostMixin, unittest.TestCase):
    mode = "bubblewrap"
    reason = _usable("bubblewrap")

    def test_the_task_sees_an_empty_tmp(self):
        marker = tempfile.NamedTemporaryFile(dir="/tmp", delete=False)
        marker.close()
        self.addCleanup(os.remove, marker.name)
        code, out, err = _run(self.mode, f"ls {marker.name} 2>/dev/null; echo ls=$?", self.workspace, self.spec())
        self.assertEqual(code, 0, err)
        self.assertNotIn("ls=0", out)


if __name__ == "__main__":
    unittest.main()
