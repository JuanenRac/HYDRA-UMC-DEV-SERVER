# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_taskflow_edges.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Staging a repository at a pinned revision, the concurrency gate and the end of a workspace: fakes for git and for process liveness,
plus one pass with a real git on a repository made in a temporary folder."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from hydra_umc_dev_server import taskflow as tf
from hydra_umc_dev_server.config import ConfigValidationError

SHA = "0123456789abcdef0123456789abcdef01234567"


class FakeGit:
    """Answers each git call from a script keyed by its second word and records every call."""

    def __init__(self, script=None, head=SHA):
        self.script = dict(script or {})
        self.head = head
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []

    def __call__(self, argv, *, cwd, env, timeout):
        self.calls.append(list(argv))
        self.envs.append(env)
        name = "checkout" if "checkout" in argv else argv[1]
        if name == "rev-parse":
            return self.script.get("rev-parse", (0, self.head + "\n"))
        return self.script.get(name, (0, ""))


def test_a_clean_staging_runs_the_four_steps_in_order_and_returns_the_commit(tmp_path: Path) -> None:
    git = FakeGit()
    assert tf.stage_repo(str(tmp_path), "https://example.org/r.git", SHA, run=git) == SHA
    assert [call[1] if call[1] != "-c" else call[3] for call in git.calls] == ["init", "fetch", "checkout", "rev-parse"]
    fetch = git.calls[1]
    assert fetch[-2:] == ["https://example.org/r.git", SHA]
    assert "--depth" in fetch and "--no-tags" in fetch and "--no-recurse-submodules" in fetch


def test_a_tag_is_fetched_as_a_tag_and_a_short_hash_is_accepted_when_it_matches(tmp_path: Path) -> None:
    git = FakeGit()
    assert tf.stage_repo(str(tmp_path), "src", "v1.2.3", run=git) == SHA
    assert git.calls[1][-1] == "refs/tags/v1.2.3"
    assert tf.fetch_ref("refs/heads/main") == "refs/heads/main"
    assert tf.fetch_ref("abcdef1") == "abcdef1"
    assert tf.fetch_ref("ABCDEF1234") == "ABCDEF1234"
    assert tf.fetch_ref("abcde") == "refs/tags/abcde"  # fewer than 7 hex characters is a tag name
    assert tf.stage_repo(str(tmp_path), "src", SHA[:7].upper(), run=FakeGit()) == SHA


@pytest.mark.parametrize("failing", ["init", "fetch", "checkout"])
def test_a_failing_step_stops_the_staging_and_keeps_the_tail_of_the_message(failing: str, tmp_path: Path) -> None:
    git = FakeGit({failing: (128, "x" * 1000 + "THE-REASON")})
    with pytest.raises(tf.StagingError, match=r"failed \(128\)") as raised:
        tf.stage_repo(str(tmp_path), "src", SHA, run=git)
    assert str(raised.value).endswith("THE-REASON")
    assert len(str(raised.value)) < 400
    assert not any("rev-parse" in call for call in git.calls)


@pytest.mark.parametrize("head", ["", "not a hash", "ABC", "0123", "g" * 40, SHA + "0" * 40])
def test_a_head_that_is_not_a_commit_is_refused(head: str, tmp_path: Path) -> None:
    with pytest.raises(tf.StagingError, match="did not report"):
        tf.stage_repo(str(tmp_path), "src", SHA, run=FakeGit(head=head))


def test_a_failing_rev_parse_and_a_commit_other_than_the_pinned_one_are_refused(tmp_path: Path) -> None:
    with pytest.raises(tf.StagingError, match="did not report"):
        tf.stage_repo(str(tmp_path), "src", SHA, run=FakeGit({"rev-parse": (1, SHA)}))
    other = "f" * 40
    with pytest.raises(tf.StagingError, match="not the pinned revision"):
        tf.stage_repo(str(tmp_path), "src", SHA, run=FakeGit(head=other))
    assert tf.stage_repo(str(tmp_path), "src", "v9", run=FakeGit(head=other)) == other  # a tag cannot be compared with a hash


def test_git_runs_with_a_scrubbed_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GITHUB_TOKEN", "ANTHROPIC_API_KEY", "SSH_AUTH_SOCK", "GIT_ASKPASS", "GIT_SSH_COMMAND", "MY_SECRET"):
        monkeypatch.setenv(name, "must-not-travel")
    env = tf.git_environment(str(tmp_path))
    assert not [value for value in env.values() if value == "must-not-travel"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_ALLOW_PROTOCOL"] == "file:https"
    assert env["HOME"] == str(tmp_path)


def test_git_that_is_missing_or_too_slow_is_a_staging_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def missing(*args, **kwargs):
        raise FileNotFoundError("git")

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)

    monkeypatch.setattr(tf.subprocess, "run", missing)
    with pytest.raises(tf.StagingError, match="not installed"):
        tf._system_git(["git", "init"], cwd=str(tmp_path), env={}, timeout=1)
    monkeypatch.setattr(tf.subprocess, "run", slow)
    with pytest.raises(tf.StagingError, match="longer than 1 seconds"):
        tf._system_git(["git", "fetch", "-q", "x"], cwd=str(tmp_path), env={}, timeout=1)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_real_git_stages_a_local_repository_at_its_pinned_commit(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=source, env=env, capture_output=True, text=True, check=True)
        return done.stdout.strip()

    git("init", "-q")
    (source / "a.txt").write_text("one", encoding="utf-8")
    git("add", "a.txt")
    git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "first")
    first = git("rev-parse", "HEAD")
    (source / "a.txt").write_text("two", encoding="utf-8")
    git("-c", "commit.gpgsign=false", "commit", "-q", "-am", "second")
    git("tag", "v0.0.1", first)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # The local clone source goes through the file protocol, which the scrubbed environment allows.
    commit = tf.stage_repo(str(workspace), source.as_posix(), first)
    assert commit == first
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "one"
    again = tmp_path / "ws2"
    again.mkdir()
    assert tf.stage_repo(str(again), source.as_posix(), "v0.0.1") == first
    missing = tmp_path / "ws3"
    missing.mkdir()
    with pytest.raises(tf.StagingError):
        tf.stage_repo(str(missing), source.as_posix(), "v404")


def test_the_gate_lets_in_up_to_its_limit_and_frees_the_place_when_the_task_ends(tmp_path: Path) -> None:
    gate = tf.ConcurrencyGate(str(tmp_path), 2, alive=lambda pid: True)
    with gate.hold("t1"):
        with gate.hold("t2"):
            with pytest.raises(tf.TooManyTasksError, match="2 task"):
                with gate.hold("t3"):
                    pytest.fail("a third task must not run")
        assert len(list((tmp_path / ".running").glob("*.lock"))) == 1
    assert list((tmp_path / ".running").glob("*.lock")) == []
    with gate.hold("t3"):
        pass


def test_the_same_task_cannot_run_twice_and_a_failure_still_frees_the_lock(tmp_path: Path) -> None:
    gate = tf.ConcurrencyGate(str(tmp_path), 5, alive=lambda pid: True)
    with gate.hold("t1"):
        with pytest.raises(tf.TooManyTasksError, match="already running"):
            with gate.hold("t1"):
                pytest.fail("must not run")
    with pytest.raises(RuntimeError):
        with gate.hold("t1"):
            raise RuntimeError("the task blew up")
    assert list((tmp_path / ".running").glob("*.lock")) == []


def test_a_lock_of_a_dead_process_or_with_junk_is_taken_over(tmp_path: Path) -> None:
    running = tmp_path / ".running"
    running.mkdir()
    (running / "dead.lock").write_text("111", encoding="ascii")
    (running / "junk.lock").write_text("not a pid", encoding="ascii")
    (running / "empty.lock").write_text("", encoding="ascii")
    (running / "alive.lock").write_text("222", encoding="ascii")
    gate = tf.ConcurrencyGate(str(tmp_path), 2, alive=lambda pid: pid == 222)
    with gate.hold("new"):
        assert sorted(p.name for p in running.glob("*.lock")) == ["alive.lock", "new.lock"]
    assert [p.name for p in running.glob("*.lock")] == ["alive.lock"]


def test_the_lock_holds_the_pid_of_this_process_and_this_process_is_alive(tmp_path: Path) -> None:
    gate = tf.ConcurrencyGate(str(tmp_path), 1)
    with gate.hold("t1"):
        assert (tmp_path / ".running" / "t1.lock").read_text(encoding="ascii") == str(os.getpid())
        with pytest.raises(tf.TooManyTasksError):
            with gate.hold("t2"):
                pytest.fail("the real liveness check must see this process")
    assert tf._pid_alive(os.getpid()) is True
    assert tf._pid_alive(0) is False
    assert tf._pid_alive(-5) is False


def test_both_errors_are_configuration_errors() -> None:
    assert issubclass(tf.StagingError, ConfigValidationError)
    assert issubclass(tf.TooManyTasksError, ConfigValidationError)


def test_a_workspace_is_removed_only_when_it_is_a_real_directory_directly_under_the_base(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    (base / "t1").mkdir()
    (base / "t1" / "sub").mkdir()
    (base / "t1" / "sub" / "f.txt").write_text("x", encoding="utf-8")
    readonly = base / "t1" / "ro.txt"
    readonly.write_text("x", encoding="utf-8")
    readonly.chmod(0o400)
    assert tf.remove_workspace(str(base), "t1") is True
    assert not (base / "t1").exists()
    assert tf.remove_workspace(str(base), "t1") is False  # already gone
    (base / "afile").write_text("x", encoding="utf-8")
    assert tf.remove_workspace(str(base), "afile") is False  # a file is not a workspace
    assert (base / "afile").exists()


def test_a_path_that_climbs_out_or_goes_down_is_never_removed(tmp_path: Path) -> None:
    base = tmp_path / "base"
    (base / "t1" / "deep").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    assert tf.remove_workspace(str(base), "../outside") is False
    assert tf.remove_workspace(str(base), "t1/deep") is False
    assert tf.remove_workspace(str(base), "") is False
    assert outside.exists() and (base / "t1" / "deep").exists()


def test_a_link_to_a_directory_is_never_followed(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep", encoding="utf-8")
    try:
        (base / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make symbolic links")
    assert tf.remove_workspace(str(base), "link") is False
    assert (outside / "precious.txt").read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    ("retention", "ok", "removed"),
    [("delete", True, True), ("delete", False, True), ("delete-on-success", True, True), ("delete-on-success", False, False),
     ("keep", True, False), ("keep", False, False), ("", True, False), ("DELETE", True, False)],
)
def test_the_retention_policy_decides_what_is_removed(retention: str, ok: bool, removed: bool) -> None:
    assert tf.should_remove(retention, completed_ok=ok) is removed
