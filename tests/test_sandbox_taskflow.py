# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_sandbox_taskflow.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The sandbox command lines, the argument allow-list, the staging of repo@revision,
the limit of concurrent tasks and the life of the workspace. Nothing here needs bubblewrap,
systemd or a network: the sandbox builders are pure and git works on a local repository."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from hydra_umc_dev_server.config import ConfigValidationError, TaskPolicy
from hydra_umc_dev_server.recipe import TaskRecipe, argument_problems
from hydra_umc_dev_server.runner import FIXED_PATH, OUTCOME_COMPLETED, OUTCOME_REJECTED, build_task_env, run_task
from hydra_umc_dev_server.sandbox import (
    SandboxSpec,
    SandboxUnavailableError,
    SandboxedLauncher,
    bubblewrap_argv,
    detect_sandbox,
    systemd_run_argv,
)
from hydra_umc_dev_server.taskflow import (
    ConcurrencyGate,
    StagingError,
    TooManyTasksError,
    fetch_ref,
    remove_workspace,
    should_remove,
    stage_repo,
)
from hydra_umc_dev_server.workspace import SystemWorkspaceFs, Workspace


def _policy(**extra):
    data = {"allow_deploy": False, "max_concurrent_tasks": 1, "allowed_commands": ["pytest", "build.sh", "python"]}
    data.update(extra)
    return TaskPolicy.from_dict(data)


class SandboxCommandLineTests(unittest.TestCase):
    ENV = {"PATH": "/usr/bin", "HOME": "/ws/t1"}

    def test_bubblewrap_has_no_home_no_network_an_empty_tmp_and_only_the_workspace_writable(self):
        argv = bubblewrap_argv(("pytest", "-q"), cwd="/ws/t1", env=self.ENV, spec=SandboxSpec(), exists=lambda p: p in ("/usr", "/bin"))
        text = " ".join(argv)
        self.assertEqual(argv[0], "bwrap")
        self.assertIn("--unshare-all", argv)
        self.assertNotIn("--share-net", argv)
        self.assertIn("--ro-bind /usr /usr", text)
        self.assertNotIn("/home", text.replace("/ws/t1", ""))
        self.assertIn("--tmpfs /tmp", text)
        self.assertIn("--bind /ws/t1 /ws/t1", text)
        self.assertIn("--clearenv", argv)
        self.assertIn("--setenv HOME /ws/t1", text)
        self.assertEqual(argv[-3:], ("--", "pytest", "-q")[-3:])
        self.assertEqual(argv[argv.index("--") + 1:], ("pytest", "-q"))

    def test_the_network_and_extra_read_only_paths_are_opened_only_when_the_policy_says_so(self):
        spec = SandboxSpec(network=True, read_only_paths=("/opt/toolchain",))
        argv = bubblewrap_argv(("pytest",), cwd="/ws/t1", env=self.ENV, spec=spec, exists=lambda p: p == "/etc/resolv.conf")
        self.assertIn("--share-net", argv)
        self.assertIn("/etc/resolv.conf", argv)
        self.assertIn("/opt/toolchain", argv)

    def test_systemd_run_protects_the_home_the_system_and_the_network(self):
        argv = systemd_run_argv(("pytest", "-q"), cwd="/ws/t1", env=self.ENV, spec=SandboxSpec(), is_root=False)
        text = " ".join(argv)
        self.assertIn("--user", argv)
        for expected in ("ProtectHome=yes", "ProtectSystem=strict", "PrivateTmp=yes", "PrivateNetwork=yes", "NoNewPrivileges=yes", "ReadWritePaths=/ws/t1"):
            self.assertIn(expected, text)
        self.assertEqual(argv[argv.index("--") + 1:], ("pytest", "-q"))
        as_root = systemd_run_argv(("pytest",), cwd="/ws/t1", env=self.ENV, spec=SandboxSpec(network=True), is_root=True)
        self.assertNotIn("--user", as_root)
        self.assertNotIn("PrivateNetwork=yes", " ".join(as_root))

    def test_detection_prefers_bubblewrap_then_systemd_and_a_named_missing_one_is_an_error(self):
        both = {"bwrap": "/usr/bin/bwrap", "systemd-run": "/usr/bin/systemd-run"}.get
        only_systemd = {"systemd-run": "/usr/bin/systemd-run"}.get
        self.assertEqual(detect_sandbox("auto", which=both, os_name="posix"), "bubblewrap")
        self.assertEqual(detect_sandbox("auto", which=only_systemd, os_name="posix"), "systemd-run")
        self.assertEqual(detect_sandbox("auto", which=lambda _n: None, os_name="posix"), "none")
        self.assertEqual(detect_sandbox("none", which=both, os_name="posix"), "none")
        with self.assertRaises(SandboxUnavailableError):
            detect_sandbox("bubblewrap", which=only_systemd, os_name="posix")
        with self.assertRaises(SandboxUnavailableError):
            detect_sandbox("bubblewrap", which=both, os_name="nt")
        with self.assertRaises(ConfigValidationError):
            detect_sandbox("docker", which=both, os_name="posix")

    def test_the_launcher_wraps_the_command_and_a_required_sandbox_refuses_a_bare_host(self):
        calls = []

        class Inner:
            def spawn(self, argv, *, cwd, env):
                calls.append((argv, cwd, env))
                return object()

        launcher = SandboxedLauncher(Inner(), SandboxSpec(), which={"bwrap": "/usr/bin/bwrap"}.get, os_name="posix")
        self.assertEqual(launcher.used, "bubblewrap")
        launcher.spawn(("pytest", "-q"), cwd="/ws/t1", env=self.ENV)
        self.assertEqual(calls[0][0][0], "bwrap")
        self.assertEqual(calls[0][0][-2:], ("pytest", "-q"))
        self.assertNotIn("HOME", calls[0][2])  # the wrapper itself gets no HOME; the task gets its own inside
        bare = SandboxedLauncher(Inner(), SandboxSpec(), which=lambda _n: None, os_name="posix")
        self.assertEqual(bare.used, "none")
        bare.spawn(("pytest",), cwd="/ws/t1", env=self.ENV)
        self.assertEqual(calls[-1][0], ("pytest",))
        with self.assertRaises(SandboxUnavailableError):
            SandboxedLauncher(Inner(), SandboxSpec(required=True), which=lambda _n: None, os_name="posix")


class PolicyFieldsTests(unittest.TestCase):
    def test_defaults_are_the_conservative_ones_and_round_trip(self):
        policy = _policy()
        self.assertEqual((policy.sandbox, policy.sandbox_required, policy.sandbox_network), ("auto", False, False))
        self.assertEqual(policy.workspace_retention, "delete-on-success")
        self.assertEqual(TaskPolicy.from_dict(policy.to_dict()), policy)

    def test_invalid_values_are_reported_together(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            TaskPolicy.from_dict({
                "sandbox": "docker", "workspace_retention": "forever", "sandbox_read_only_paths": ["relative"],
                "allowed_arguments": {"pytest": "-q"}, "repo_sources": {"x": ""},
            })
        message = str(ctx.exception)
        for part in ("sandbox", "workspace_retention", "sandbox_read_only_paths", "allowed_arguments", "repo_sources"):
            self.assertIn(part, message)


class ArgumentAllowListTests(unittest.TestCase):
    def test_pytest_options_that_load_code_or_other_configuration_are_refused(self):
        policy = _policy()
        for args in (["-p", "evil"], ["-pevil"], ["-c", "x.ini"], ["-o", "addopts=x"], ["--rootdir=/"], ["--rootdir", "x"], ["--confcutdir=x"]):
            self.assertTrue(argument_problems(("pytest", *args), policy), args)
        self.assertEqual(argument_problems(("pytest", "-q", "-x", "tests/test_a.py", "-p", "no:cacheprovider"), policy), [])
        self.assertEqual(argument_problems(("pytest", "-pno:cacheprovider"), policy), [])

    def test_paths_outside_the_workspace_are_refused_in_plain_and_option_values(self):
        policy = _policy()
        for args in (["/etc/passwd"], ["../x"], ["a/../../x"], ["~/x"], ["--log-file=/tmp/x"], ["--out=../x"], ["C:/Users/x"], ["a\\..\\x"]):
            self.assertTrue(argument_problems(("pytest", *args), policy), args)
        self.assertEqual(argument_problems(("pytest", "tests", "--tb=short", "-k", "a and b"), policy), [])

    def test_shells_and_interpreters_cannot_be_given_inline_code(self):
        policy = _policy()
        self.assertTrue(argument_problems(("python", "-c", "print(1)"), policy))
        self.assertTrue(argument_problems(("bash", "-c", "id"), policy))
        self.assertEqual(argument_problems(("python", "check.py"), policy), [])

    def test_a_command_with_patterns_accepts_nothing_else(self):
        policy = _policy(allowed_arguments={"pytest": ["-q", "-x", "tests/*"]})
        self.assertEqual(argument_problems(("pytest", "-q", "tests/test_a.py"), policy), [])
        self.assertTrue(argument_problems(("pytest", "-v"), policy))
        self.assertTrue(argument_problems(("pytest", "src"), policy))
        self.assertEqual(argument_problems(("build.sh", "--anything"), policy), [])

    def test_the_recipe_is_rejected_by_validate_against_and_dot_slash_names_the_same_script(self):
        recipe = TaskRecipe.from_dict({"task_id": "t-1", "repo": "r", "revision": "1.0.0", "command": ["pytest", "-p", "evil"], "timeout_seconds": 5})
        with self.assertRaises(ConfigValidationError):
            recipe.validate_against(_policy())
        dotted = TaskRecipe.from_dict({"task_id": "t-2", "repo": "r", "revision": "1.0.0", "command": ["./build.sh"], "timeout_seconds": 5})
        dotted.validate_against(_policy())


class FixedPathAndScriptTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "the fixed PATH is for POSIX hosts")
    def test_the_task_path_is_fixed_whatever_the_service_inherited(self):
        env = build_task_env({"PATH": "/tmp/evil:relative:/usr/bin", "HOME": "/home/pi"})
        self.assertEqual(env["PATH"], FIXED_PATH)

    @unittest.skipUnless(os.name == "posix", "the workspace paths are POSIX paths")
    def test_a_script_of_the_repository_is_found_in_the_workspace_and_a_missing_dot_slash_one_is_rejected(self):
        launched = []

        class Handle:
            def poll(self):
                return 0

            def kill_tree(self):
                pass

            def stdout_tail(self):
                return ""

            def stderr_tail(self):
                return ""

        class Launcher:
            def spawn(self, argv, *, cwd, env):
                launched.append(argv)
                return Handle()

        with tempfile.TemporaryDirectory() as base:
            ws = _make_workspace(base, "task-1")
            Path(ws.root, "build.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            recipe = TaskRecipe.from_dict({"task_id": "task-1", "repo": "r", "revision": "1.0.0", "command": ["build.sh"], "timeout_seconds": 5})
            result = run_task(recipe, _policy(), ws, Launcher(), fs=SystemWorkspaceFs())
            self.assertEqual(result.outcome, OUTCOME_COMPLETED, result.rejection_reason)
            self.assertTrue(launched[0][0].endswith("build.sh") and os.path.isabs(launched[0][0]))
            missing = TaskRecipe.from_dict({"task_id": "task-1", "repo": "r", "revision": "1.0.0", "command": ["./build.sh"], "timeout_seconds": 5})
            Path(ws.root, "build.sh").unlink()
            rejected = run_task(missing, _policy(), ws, Launcher(), fs=SystemWorkspaceFs())
            self.assertEqual(rejected.outcome, OUTCOME_REJECTED)
            self.assertIn("does not exist", rejected.rejection_reason or "")


def _make_workspace(base, task_id):
    """allocate_workspace wants a POSIX base; the tests also run on Windows, so the directory is made directly."""
    root = Path(base, task_id)
    root.mkdir()
    return Workspace(task_id=task_id, root=str(root))


def _git(*args, cwd):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git is needed")
class StagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name, "src-repo")
        self.src.mkdir()
        _git("init", "-q", cwd=self.src)
        (self.src / "a.txt").write_text("one", encoding="utf-8")
        _git("add", "a.txt", cwd=self.src)
        _git("commit", "-q", "-m", "first", cwd=self.src)
        self.first = _git("rev-parse", "HEAD", cwd=self.src)
        _git("tag", "v1.0.0", cwd=self.src)
        (self.src / "a.txt").write_text("two", encoding="utf-8")
        _git("commit", "-q", "-am", "second", cwd=self.src)
        _git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=self.src)

    def _workspace(self, name="w"):
        path = Path(self.tmp.name, name)
        path.mkdir()
        return str(path)

    def test_a_tag_is_checked_out_and_the_commit_is_reported(self):
        ws = self._workspace()
        commit = stage_repo(ws, self.src.as_uri(), "v1.0.0")
        self.assertEqual(commit, self.first)
        self.assertEqual(Path(ws, "a.txt").read_text(encoding="utf-8"), "one")

    def test_a_commit_hash_is_checked_out_and_must_be_the_one_asked_for(self):
        ws = self._workspace()
        self.assertEqual(stage_repo(ws, self.src.as_uri(), self.first), self.first)
        wrong = self._workspace("w2")

        def lying(argv, *, cwd, env, timeout):
            if argv[:2] == ["git", "rev-parse"]:
                return 0, "f" * 40
            return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True).returncode, ""

        with self.assertRaises(StagingError):
            stage_repo(wrong, self.src.as_uri(), self.first, run=lying)

    def test_an_unknown_revision_or_source_is_a_staging_error(self):
        with self.assertRaises(StagingError):
            stage_repo(self._workspace(), self.src.as_uri(), "v9.9.9")
        with self.assertRaises(StagingError):
            stage_repo(self._workspace("w3"), Path(self.tmp.name, "nothing").as_uri(), "v1.0.0")

    def test_fetch_ref_names_tags_and_leaves_hashes(self):
        self.assertEqual(fetch_ref("v1.2.3"), "refs/tags/v1.2.3")
        self.assertEqual(fetch_ref("refs/tags/x"), "refs/tags/x")
        self.assertEqual(fetch_ref("abcdef1"), "abcdef1")


class ConcurrencyAndRetentionTests(unittest.TestCase):
    def test_the_limit_is_enforced_and_a_dead_lock_is_taken_over(self):
        with tempfile.TemporaryDirectory() as base:
            gate = ConcurrencyGate(base, 1)
            with gate.hold("a"):
                with self.assertRaises(TooManyTasksError):
                    with gate.hold("b"):
                        pass
            with gate.hold("b"):
                pass
            lock = Path(base, ".running", "ghost.lock")
            lock.write_text("999999", encoding="ascii")
            dead = ConcurrencyGate(base, 1, alive=lambda pid: pid == os.getpid())
            with dead.hold("c"):
                self.assertFalse(lock.exists())

    def test_two_gates_of_two_slots_allow_two_and_refuse_the_third(self):
        with tempfile.TemporaryDirectory() as base:
            gate = ConcurrencyGate(base, 2)
            with gate.hold("a"), gate.hold("b"):
                with self.assertRaises(TooManyTasksError):
                    with gate.hold("c"):
                        pass

    def test_retention_and_removal_stay_inside_the_base(self):
        self.assertTrue(should_remove("delete", completed_ok=False))
        self.assertTrue(should_remove("delete-on-success", completed_ok=True))
        self.assertFalse(should_remove("delete-on-success", completed_ok=False))
        self.assertFalse(should_remove("keep", completed_ok=True))
        with tempfile.TemporaryDirectory() as base:
            ws = _make_workspace(base, "task-9")
            Path(ws.root, "f.txt").write_text("x", encoding="utf-8")
            self.assertTrue(remove_workspace(base, "task-9"))
            self.assertFalse(Path(base, "task-9").exists())
            self.assertFalse(remove_workspace(base, "task-9"))
            self.assertFalse(remove_workspace(base, ".."))
            outside = Path(base, "outside")
            outside.mkdir()
            self.assertFalse(remove_workspace(str(outside), ".."))
            self.assertTrue(outside.exists())
            _make_workspace(base, "task-9")  # the same id can be used again once it was removed




class SandboxLimitsTests(unittest.TestCase):
    ENV = {"PATH": "/usr/bin", "HOME": "/ws/t1"}

    def test_systemd_run_carries_the_cgroup_limits_of_the_policy_and_only_those(self):
        spec = SandboxSpec(memory_max="2G", cpu_quota="200%", tasks_max=256)
        text = " ".join(systemd_run_argv(("pytest",), cwd="/ws/t1", env=self.ENV, spec=spec, is_root=True))
        for expected in ("MemoryMax=2G", "MemorySwapMax=0", "CPUQuota=200%", "TasksMax=256"):
            self.assertIn(expected, text)
        plain = " ".join(systemd_run_argv(("pytest",), cwd="/ws/t1", env=self.ENV, spec=SandboxSpec(), is_root=True))
        for absent in ("MemoryMax", "CPUQuota", "TasksMax"):
            self.assertNotIn(absent, plain)

    def test_bubblewrap_has_no_cgroup_so_the_limits_do_not_appear_in_its_command_line(self):
        spec = SandboxSpec(memory_max="2G", cpu_quota="200%", tasks_max=256)
        text = " ".join(bubblewrap_argv(("pytest",), cwd="/ws/t1", env=self.ENV, spec=spec, exists=lambda p: False))
        self.assertNotIn("MemoryMax", text)

    def test_the_policy_validates_the_limits(self):
        policy = TaskPolicy.from_dict({"allow_deploy": False, "max_concurrent_tasks": 1, "allowed_commands": ["pytest"],
                                       "sandbox_memory_max": "512M", "sandbox_cpu_quota": "150%", "sandbox_tasks_max": 100})
        self.assertEqual((policy.sandbox_memory_max, policy.sandbox_cpu_quota, policy.sandbox_tasks_max), ("512M", "150%", 100))
        self.assertEqual(TaskPolicy.from_dict(policy.to_dict()), policy)
        for bad in ({"sandbox_memory_max": "lots"}, {"sandbox_memory_max": "0"}, {"sandbox_memory_max": 5},
                    {"sandbox_cpu_quota": "2"}, {"sandbox_cpu_quota": "0%"}, {"sandbox_tasks_max": 0},
                    {"sandbox_tasks_max": True}, {"sandbox_tasks_max": "9"}):
            with self.subTest(bad=bad):
                with self.assertRaises(ConfigValidationError):
                    TaskPolicy.from_dict({"allow_deploy": False, "max_concurrent_tasks": 1, "allowed_commands": ["pytest"], **bad})
        self.assertIsNone(_policy().sandbox_memory_max)


if __name__ == "__main__":
    unittest.main()
