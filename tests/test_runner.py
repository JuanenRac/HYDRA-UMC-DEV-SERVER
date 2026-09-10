# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_runner.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS04 runner. The control tests use a fake launcher and a fake clock -
nothing is spawned, and the gating (allow-listed command, no path escape,
scrubbed env, process-group kill on cancel/timeout) is proven in
isolation. One guarded test uses the real launcher to confirm a real
child-of-a-child is actually gone after a cancel."""
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from hydra_umc_dev_server.config import TaskPolicy
from hydra_umc_dev_server.recipe import TaskRecipe
from hydra_umc_dev_server.runner import (
    OUTCOME_CANCELLED,
    OUTCOME_COMPLETED,
    OUTCOME_REJECTED,
    OUTCOME_TIMED_OUT,
    CancelToken,
    ProcessLauncher,
    SubprocessLauncher,
    build_task_env,
    run_task,
)
from hydra_umc_dev_server.workspace import Workspace


def _policy(allowed=("pytest", "build.sh")):
    return TaskPolicy.from_dict(
        {"allow_deploy": False, "max_concurrent_tasks": 1, "allowed_commands": list(allowed)}
    )


def _recipe(**overrides) -> TaskRecipe:
    data = {
        "task_id": "run-0001",
        "repo": "HYDRA-UMC-DEV-SERVER",
        "revision": "0.0.4",
        "command": ["pytest", "-q"],
        "timeout_seconds": 10,
        "input_paths": [],
    }
    data.update(overrides)
    return TaskRecipe.from_dict(data)


_WS = Workspace(task_id="run-0001", root="/srv/dev/workspaces/run-0001")


class FakeHandle:
    def __init__(self, *, finish_code=0, finish_after_polls=1):
        self._code = finish_code
        self._left = finish_after_polls
        self.killed = False

    def poll(self):
        if self.killed:
            return -9
        if self._left <= 0:
            return self._code
        self._left -= 1
        return None

    def kill_tree(self):
        self.killed = True

    def stdout_tail(self):
        return "fake-stdout"

    def stderr_tail(self):
        return ""


class FakeLauncher:
    def __init__(self, handle=None):
        self.handle = handle or FakeHandle()
        self.calls: list[dict] = []

    def spawn(self, argv, *, cwd, env):
        self.calls.append({"argv": tuple(argv), "cwd": cwd, "env": dict(env)})
        return self.handle


class FakeClock:
    """monotonic() jumps by `step` every sleep() - deterministic timeouts."""

    def __init__(self, step=1.0):
        self.now = 0.0
        self.step = step

    def monotonic(self):
        return self.now

    def sleep(self, _seconds):
        self.now += self.step


class BuildTaskEnvTests(unittest.TestCase):
    def test_only_the_safe_allowlist_survives_every_secret_shaped_name_is_dropped(self):
        source = {
            "PATH": "/usr/bin", "HOME": "/home/pi", "LANG": "C.UTF-8",
            "GITHUB_TOKEN": "ghp_x", "AWS_SECRET_ACCESS_KEY": "y",
            "ANTHROPIC_API_KEY": "sk-ant-z", "DB_PASSWORD": "p", "SSH_AUTH_SOCK": "/tmp/s",
        }
        env = build_task_env(source)
        self.assertEqual(set(env), {"PATH", "HOME", "LANG"})
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertFalse(any(k.endswith(("_TOKEN", "_KEY", "_SECRET", "_PASSWORD")) for k in env))


class RunnerGatingTests(unittest.TestCase):
    def test_a_command_not_in_the_policy_is_rejected_and_nothing_is_spawned(self):
        launcher = FakeLauncher()
        result = run_task(_recipe(command=["curl", "http://evil"]), _policy(["pytest"]), _WS, launcher, clock=FakeClock())
        self.assertEqual(result.outcome, OUTCOME_REJECTED)
        self.assertIn("allowed_commands", result.rejection_reason or "")
        self.assertEqual(launcher.calls, [])

    def test_a_recipe_input_path_that_escapes_the_workspace_is_rejected_and_nothing_is_spawned(self):
        launcher = FakeLauncher()
        result = run_task(_recipe(input_paths=["../../.ssh/id_ed25519"]), _policy(), _WS, launcher, clock=FakeClock())
        self.assertEqual(result.outcome, OUTCOME_REJECTED)
        self.assertEqual(launcher.calls, [])

    def test_the_child_is_spawned_in_the_workspace_with_a_scrubbed_env(self):
        launcher = FakeLauncher()
        run_task(_recipe(), _policy(), _WS, launcher, clock=FakeClock())
        call = launcher.calls[0]
        self.assertEqual(call["cwd"], _WS.root)
        self.assertFalse(any("TOKEN" in k or "SECRET" in k or "KEY" in k for k in call["env"]))


class RunnerLifecycleTests(unittest.TestCase):
    def test_a_command_that_finishes_zero_is_completed(self):
        launcher = FakeLauncher(FakeHandle(finish_code=0, finish_after_polls=2))
        result = run_task(_recipe(), _policy(), _WS, launcher, clock=FakeClock())
        self.assertEqual(result.outcome, OUTCOME_COMPLETED)
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(result.killed_process_group)

    def test_a_command_that_never_finishes_times_out_and_the_group_is_killed(self):
        handle = FakeHandle(finish_after_polls=10_000)
        result = run_task(_recipe(timeout_seconds=3), _policy(), _WS, FakeLauncher(handle), clock=FakeClock(step=1.0))
        self.assertEqual(result.outcome, OUTCOME_TIMED_OUT)
        self.assertTrue(result.killed_process_group)
        self.assertTrue(handle.killed)

    def test_a_cancel_token_stops_the_run_and_kills_the_group(self):
        handle = FakeHandle(finish_after_polls=10_000)
        token = CancelToken()
        token.cancel()
        result = run_task(_recipe(timeout_seconds=999), _policy(), _WS, FakeLauncher(handle), cancel_token=token, clock=FakeClock())
        self.assertEqual(result.outcome, OUTCOME_CANCELLED)
        self.assertTrue(result.killed_process_group)
        self.assertTrue(handle.killed)

    def test_to_dict_is_json_shaped(self):
        result = run_task(_recipe(), _policy(), _WS, FakeLauncher(), clock=FakeClock())
        payload = result.to_dict()
        self.assertEqual(payload["task_id"], "run-0001")
        self.assertIn("outcome", payload)
        self.assertIn("killed_process_group", payload)

    def test_the_fake_launcher_satisfies_the_protocol(self):
        self.assertIsInstance(FakeLauncher(), ProcessLauncher)


def _pid_alive(pid: int) -> bool:
    if os.name == "posix":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
        capture_output=True, text=True, check=False,
    ).stdout
    return str(pid) in out


class RealChildOfAChildIsReapedTests(unittest.TestCase):
    """The real evidence for DS04's 'cancelación limpia hijos': spawn a
    real process that itself spawns a real grandchild, cancel, and confirm
    BOTH are gone."""

    def test_cancelling_a_run_kills_the_whole_real_process_tree(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(task_id="real-tree", root=str(Path(tmp)))
            script = (
                "import subprocess, sys, os, time\n"
                "c = subprocess.Popen([sys.executable, '-c',"
                " \"import os,time; open('grandchild.pid','w').write(str(os.getpid())); time.sleep(120)\"])\n"
                "open('child.pid','w').write(str(os.getpid()))\n"
                "time.sleep(120)\n"
            )
            recipe = TaskRecipe.from_dict({
                "task_id": "real-tree", "repo": "x", "revision": "0.0.4",
                "command": [sys.executable, "-c", script], "timeout_seconds": 120, "input_paths": [],
            })
            policy = _policy([sys.executable])
            token = CancelToken()
            threading.Timer(2.0, token.cancel).start()

            result = run_task(recipe, policy, ws, SubprocessLauncher(), cancel_token=token, poll_interval=0.1)

            self.assertEqual(result.outcome, OUTCOME_CANCELLED)
            self.assertTrue(result.killed_process_group)

            child_pid = int((Path(tmp) / "child.pid").read_text())
            grandchild_pid = int((Path(tmp) / "grandchild.pid").read_text())
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and (_pid_alive(child_pid) or _pid_alive(grandchild_pid)):
                time.sleep(0.2)
            self.assertFalse(_pid_alive(child_pid), "the child process survived the cancel")
            self.assertFalse(_pid_alive(grandchild_pid), "the grandchild process survived the cancel")


if __name__ == "__main__":
    unittest.main()
