# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/runner.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS04, part 3 - the bounded runner.

This is the first delivery that actually executes something. It stays
tightly gated:

  * the recipe's command must be in the policy's `allowed_commands`
    (`recipe.validate_against`) and every declared input path must stay
    inside the workspace, or the run is `rejected` before anything spawns.
  * the child gets a SCRUBBED environment - only a fixed safe allow-list
    (`PATH`, `HOME`, `LANG`, `TZ`), never an inherited `*_TOKEN` /
    `*_KEY` / `*_SECRET` / `ANTHROPIC_*` / `GITHUB_*` / `SSH_*`. That is
    DS04's "acceso a secretos se rechaza": the runner never hands a task
    a credential it happened to have.
  * on timeout or cancel the WHOLE process group is killed, not just the
    direct child - DS04's "cancelación limpia hijos".

All of that is driven through the injectable `ProcessLauncher` seam, so
the control tests use a fake and prove the gating without spawning
anything; one guarded test uses the real `SubprocessLauncher` to prove a
real child-of-a-child is actually gone after a cancel.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .config import ConfigValidationError, TaskPolicy
from .recipe import TaskRecipe
from .workspace import Workspace

# The ONLY variables a task's environment is allowed to inherit. Anything
# else - and every secret-shaped name in particular - is simply absent.
# The Windows extras are non-secret OS basics the interpreter itself needs
# to start at all; the real target of this runner is a Linux dev host.
_SAFE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TZ")
_SAFE_ENV_KEYS_WINDOWS = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
    "TEMP", "TMP", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
)
_TAIL_BYTES = 8 * 1024

OUTCOME_COMPLETED = "completed"
OUTCOME_TIMED_OUT = "timed-out"
OUTCOME_CANCELLED = "cancelled"
OUTCOME_REJECTED = "rejected"


def build_task_env(source_env: dict[str, str] | None = None) -> dict[str, str]:
    """A task's whole environment: the safe allow-list only, nothing
    inherited beyond it."""
    import os

    src = os.environ if source_env is None else source_env
    return {key: src[key] for key in _SAFE_ENV_KEYS if key in src and src[key]}


class CancelToken:
    """A one-shot cancel flag the runner polls between waits."""

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


@runtime_checkable
class ProcessHandle(Protocol):
    def poll(self) -> int | None:
        """Exit code if the process has finished, else None. Non-blocking."""

    def kill_tree(self) -> None:
        """Terminate this process AND every descendant (the process
        group / job), then reap."""

    def stdout_tail(self) -> str: ...

    def stderr_tail(self) -> str: ...


@runtime_checkable
class ProcessLauncher(Protocol):
    def spawn(self, argv: tuple[str, ...], *, cwd: str, env: dict[str, str]) -> ProcessHandle: ...


@dataclass(frozen=True)
class RunResult:
    task_id: str
    outcome: str
    exit_code: int | None
    duration_seconds: float
    stdout_tail: str = ""
    stderr_tail: str = ""
    rejection_reason: str | None = None
    killed_process_group: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "outcome": self.outcome,
            "exit_code": self.exit_code,
            "duration_seconds": round(self.duration_seconds, 3),
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "rejection_reason": self.rejection_reason,
            "killed_process_group": self.killed_process_group,
        }


def run_task(
    recipe: TaskRecipe,
    policy: TaskPolicy,
    workspace: Workspace,
    launcher: ProcessLauncher,
    *,
    cancel_token: CancelToken | None = None,
    poll_interval: float = 0.05,
    clock: Any = time,
) -> RunResult:
    """Execute `recipe` inside `workspace`, bounded by `recipe.timeout_seconds`
    and `cancel_token`. Returns a `RunResult`; raises nothing for a normal
    rejection or a non-zero exit."""
    try:
        recipe.validate_against(policy)
        resolved = recipe.resolved_input_paths(workspace)  # raises WorkspaceEscapeError on escape
    except ConfigValidationError as exc:
        return RunResult(
            task_id=recipe.task_id,
            outcome=OUTCOME_REJECTED,
            exit_code=None,
            duration_seconds=0.0,
            rejection_reason=str(exc),
        )
    del resolved  # DS04 only proves they resolve; DS05's runner stages them

    env = build_task_env()
    started = clock.monotonic()
    handle = launcher.spawn(tuple(recipe.command), cwd=workspace.root, env=env)

    outcome = OUTCOME_COMPLETED
    exit_code: int | None = None
    killed = False
    while True:
        exit_code = handle.poll()
        if exit_code is not None:
            break
        elapsed = clock.monotonic() - started
        if cancel_token is not None and cancel_token.cancelled:
            handle.kill_tree()
            outcome, killed = OUTCOME_CANCELLED, True
            break
        if elapsed >= recipe.timeout_seconds:
            handle.kill_tree()
            outcome, killed = OUTCOME_TIMED_OUT, True
            break
        clock.sleep(poll_interval)

    return RunResult(
        task_id=recipe.task_id,
        outcome=outcome,
        exit_code=exit_code,
        duration_seconds=clock.monotonic() - started,
        stdout_tail=handle.stdout_tail(),
        stderr_tail=handle.stderr_tail(),
        killed_process_group=killed,
    )


# ---------------------------------------------------------------------------
# The one real launcher
# ---------------------------------------------------------------------------
class _SubprocessHandle:
    def __init__(self, proc: Any) -> None:
        self._proc = proc
        self._out = ""
        self._err = ""
        self._reaped = False

    def poll(self) -> int | None:
        code = self._proc.poll()
        if code is not None and not self._reaped:
            self._drain()
        return code

    def _drain(self) -> None:
        try:
            out, err = self._proc.communicate(timeout=5)
        except Exception:  # noqa: BLE001 - best-effort tail capture only
            out, err = "", ""
        self._out = (out or "")[-_TAIL_BYTES:]
        self._err = (err or "")[-_TAIL_BYTES:]
        self._reaped = True

    def kill_tree(self) -> None:
        import os
        import signal
        import subprocess as sp

        pid = self._proc.pid
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                self._wait_briefly()
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        else:  # Windows: taskkill reaps the whole tree
            sp.run(
                ("taskkill", "/F", "/T", "/PID", str(pid)),
                stdout=sp.DEVNULL, stderr=sp.DEVNULL, check=False,
            )
        if not self._reaped:
            self._drain()

    def _wait_briefly(self) -> None:
        for _ in range(20):
            if self._proc.poll() is not None:
                return
            time.sleep(0.05)

    def stdout_tail(self) -> str:
        return self._out

    def stderr_tail(self) -> str:
        return self._err


class SubprocessLauncher:
    """Real `ProcessLauncher`. Spawns the child as its own process-group
    leader (POSIX `start_new_session`, Windows `CREATE_NEW_PROCESS_GROUP`)
    so `kill_tree()` can take down every descendant, not just the child."""

    def spawn(self, argv: tuple[str, ...], *, cwd: str, env: dict[str, str]) -> ProcessHandle:
        import subprocess as sp

        kwargs: dict[str, Any] = {}
        if hasattr(sp, "CREATE_NEW_PROCESS_GROUP"):  # Windows
            kwargs["creationflags"] = sp.CREATE_NEW_PROCESS_GROUP
        else:  # POSIX
            kwargs["start_new_session"] = True
        proc = sp.Popen(  # noqa: S603 - argv is an allow-listed command from a validated recipe
            list(argv),
            cwd=cwd,
            env=env,
            stdout=sp.PIPE,
            stderr=sp.PIPE,
            text=True,
            **kwargs,
        )
        return _SubprocessHandle(proc)
