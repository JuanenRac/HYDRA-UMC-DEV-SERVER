# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/taskflow.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""What surrounds a task run: staging the repository at its pinned revision, limiting
how many tasks run at once, and the life of the workspace afterwards.

  * `stage_repo` puts `repo@revision` into the (empty) workspace with git, verifying that
    what was checked out really is the pinned commit. Git runs with a scrubbed
    environment, no prompts, no system or user configuration and only the file and https
    protocols, and it is injectable so the tests need no network.
  * `ConcurrencyGate` enforces `TaskPolicy.max_concurrent_tasks` across processes with one
    lock file per running task; a lock whose process is gone is taken over.
  * `apply_retention` removes the workspace according to `TaskPolicy.workspace_retention`,
    only ever a directory that is a real (non-link) child of the workspace base.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Protocol

from .config import ConfigValidationError

_HEX_REVISION = re.compile(r"^[0-9a-fA-F]{7,64}$")


class StagingError(ConfigValidationError):
    """The repository could not be put into the workspace at the pinned revision."""


class TooManyTasksError(ConfigValidationError):
    """`max_concurrent_tasks` tasks are already running."""


class GitRunner(Protocol):
    def __call__(self, argv: list[str], *, cwd: str, env: dict[str, str], timeout: int) -> tuple[int, str]: ...


def _system_git(argv: list[str], *, cwd: str, env: dict[str, str], timeout: int) -> tuple[int, str]:
    try:
        done = subprocess.run(  # noqa: S603 - fixed git subcommands, no shell
            argv, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except FileNotFoundError as exc:
        raise StagingError(f"git is not installed: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise StagingError(f"git took longer than {timeout} seconds: {' '.join(argv[:3])}") from exc
    return done.returncode, (done.stdout + done.stderr).strip()


def git_environment(workspace_root: str) -> dict[str, str]:
    """No credentials, no prompt, no configuration of the service user, only file and https."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": workspace_root,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ALLOW_PROTOCOL": "file:https",
        "LANG": "C",
    }
    for key in ("SYSTEMROOT", "TEMP", "TMP"):  # Windows needs these for git to start at all
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def fetch_ref(revision: str) -> str:
    """The ref to ask git for: a hash as it is, `vX.Y.Z` as the tag it names."""
    if revision.startswith("refs/") or _HEX_REVISION.match(revision):
        return revision
    return f"refs/tags/{revision}"


def stage_repo(
    workspace_root: str,
    source: str,
    revision: str,
    *,
    run: GitRunner = _system_git,
    timeout: int = 600,
) -> str:
    """Fetch `revision` of `source` into `workspace_root` and return the commit checked out.

    Raises `StagingError` when git fails or the checked-out commit is not the pinned one.
    """
    env = git_environment(workspace_root)
    steps = (
        ["git", "init", "-q"],
        ["git", "fetch", "-q", "--depth", "1", "--no-tags", "--no-recurse-submodules", source, fetch_ref(revision)],
        ["git", "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", "FETCH_HEAD"],
    )
    for argv in steps:
        code, output = run(argv, cwd=workspace_root, env=env, timeout=timeout)
        if code != 0:
            raise StagingError(f"{' '.join(argv[:2])} failed ({code}): {output[-300:]}")
    code, head = run(["git", "rev-parse", "HEAD"], cwd=workspace_root, env=env, timeout=timeout)
    commit = head.strip().lower()
    if code != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise StagingError("git did not report the checked-out commit")
    if _HEX_REVISION.match(revision) and not commit.startswith(revision.lower()):
        raise StagingError(f"the checked-out commit {commit[:12]} is not the pinned revision {revision}")
    return commit


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # type: ignore[attr-defined]  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ConcurrencyGate:
    """At most `limit` tasks at once under one workspace base, across processes."""

    def __init__(self, base: str, limit: int, *, alive: Callable[[int], bool] = _pid_alive) -> None:
        self._dir = Path(base) / ".running"
        self._limit = limit
        self._alive = alive

    def _live_locks(self) -> list[Path]:
        live: list[Path] = []
        if not self._dir.is_dir():
            return live
        for lock in self._dir.glob("*.lock"):
            try:
                pid = int(lock.read_text(encoding="ascii").strip() or "0")
            except (OSError, ValueError):
                pid = 0
            if self._alive(pid):
                live.append(lock)
            else:
                try:
                    lock.unlink()
                except OSError:
                    pass
        return live

    @contextmanager
    def hold(self, task_id: str) -> Iterator[None]:
        self._dir.mkdir(parents=True, exist_ok=True)
        if len(self._live_locks()) >= self._limit:
            raise TooManyTasksError(f"{self._limit} task(s) are already running (max_concurrent_tasks); try again when one finishes")
        lock = self._dir / f"{task_id}.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise TooManyTasksError(f"task {task_id!r} is already running") from exc
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(str(os.getpid()))
        try:
            yield
        finally:
            try:
                lock.unlink()
            except OSError:
                pass


def remove_workspace(base: str, task_id: str) -> bool:
    """Delete `<base>/<task_id>` when it is a real directory directly under `base` (never a link).
    Returns whether something was removed."""
    root = Path(base).resolve()
    target = root / task_id
    if target.is_symlink() or not target.is_dir() or target.resolve().parent != root:
        return False

    def _writable(function, path, _error):  # git leaves read-only object files behind on Windows
        os.chmod(path, 0o700)
        function(path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=_writable)
    else:
        shutil.rmtree(target, onerror=_writable)
    return True


def should_remove(retention: str, *, completed_ok: bool) -> bool:
    return retention == "delete" or (retention == "delete-on-success" and completed_ok)
