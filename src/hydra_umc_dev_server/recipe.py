# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/recipe.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS04, part 2 - a task recipe pinned to a revision, with an allowed
command.

Two more of DS04's acceptance invariants live here:

  * a command that is not in the task policy's own `allowed_commands` is
    refused - `TaskRecipe.validate_against(policy)` checks `command[0]`
    against `TaskPolicy.allowed_commands` (DS01's schema) and refuses
    anything else, so "run whatever" is never a recipe.
  * a recipe path that would escape the workspace is refused - every
    entry in `input_paths` is resolved through the `Workspace` (a `..`,
    an absolute path, or later a symlink target outside the workspace all
    raise `WorkspaceEscapeError`), so a recipe cannot name
    `../../.ssh/id_ed25519` as one of "its" files.

Same DS01 shape: a frozen dataclass, `from_dict()` accumulating every
error into one `ConfigValidationError`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .config import ConfigValidationError, TaskPolicy, _require_positive_int, _require_str
from .workspace import Workspace, _require_safe_id

# A recipe cannot ask for an unbounded run - DS05 refines leases/limits,
# but even at DS04 a timeout must be real and sane.
_MAX_TIMEOUT_SECONDS = 60 * 60  # one hour
_REVISION = re.compile(r"^[0-9a-fA-F]{7,64}$|^v?\d+\.\d+\.\d+$|^refs/tags/[\w./-]+$")


@dataclass(frozen=True)
class TaskRecipe:
    """One unit of bounded work: which repo, pinned to which revision,
    which allowed command, how long it may run, and which files inside
    the workspace it declares it needs."""

    task_id: str
    repo: str
    revision: str
    command: tuple[str, ...]
    timeout_seconds: int
    input_paths: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "repo": self.repo,
            "revision": self.revision,
            "command": list(self.command),
            "timeout_seconds": self.timeout_seconds,
            "input_paths": list(self.input_paths),
        }

    @staticmethod
    def from_dict(data: object) -> "TaskRecipe":
        if not isinstance(data, dict):
            raise ConfigValidationError("task recipe must be a JSON object")
        errors: list[str] = []

        task_id_raw = _require_str(data, "task_id", errors)
        task_id = ""
        if task_id_raw:
            try:
                task_id = _require_safe_id(task_id_raw)
            except ConfigValidationError as exc:
                errors.append(str(exc))

        repo = _require_str(data, "repo", errors)
        revision = _require_str(data, "revision", errors)
        if revision and not _REVISION.match(revision):
            errors.append(
                f"'revision' {revision!r} must be a commit hash, a vX.Y.Z tag, or refs/tags/... "
                "- a bare branch name is not a pinned revision"
            )

        command_raw = data.get("command")
        command: tuple[str, ...] = ()
        if not isinstance(command_raw, list) or not command_raw or not all(isinstance(c, str) and c for c in command_raw):
            errors.append("'command' must be a non-empty list of non-empty strings (argv)")
        else:
            command = tuple(command_raw)

        timeout_seconds = _require_positive_int(data, "timeout_seconds", errors, default=300)
        if timeout_seconds > _MAX_TIMEOUT_SECONDS:
            errors.append(f"'timeout_seconds' {timeout_seconds} exceeds the maximum {_MAX_TIMEOUT_SECONDS}")

        input_paths_raw = data.get("input_paths", [])
        input_paths: tuple[str, ...] = ()
        if not isinstance(input_paths_raw, list) or not all(isinstance(p, str) and p for p in input_paths_raw):
            errors.append("'input_paths' must be a list of non-empty strings")
        else:
            input_paths = tuple(input_paths_raw)

        if errors:
            raise ConfigValidationError("; ".join(errors))
        return TaskRecipe(
            task_id=task_id,
            repo=repo,
            revision=revision,
            command=command,
            timeout_seconds=timeout_seconds,
            input_paths=input_paths,
        )

    def validate_against(self, policy: TaskPolicy) -> None:
        """Raise `ConfigValidationError` unless this recipe's command is
        explicitly allowed by `policy`. Deploy stays forbidden the DS01
        way: `allow_deploy` is not consulted here because a deploy command
        is simply never in `allowed_commands`."""
        if not policy.allowed_commands:
            raise ConfigValidationError(
                "the task policy allows no commands at all - no recipe can run under it"
            )
        if self.command and self.command[0] not in policy.allowed_commands:
            raise ConfigValidationError(
                f"command {self.command[0]!r} is not in the policy's allowed_commands "
                f"{tuple(policy.allowed_commands)!r}"
            )

    def resolved_input_paths(self, workspace: Workspace) -> tuple[str, ...]:
        """Every declared input path, resolved inside `workspace`. Raises
        `WorkspaceEscapeError` (a `ConfigValidationError` subclass) for any
        path that climbs out - a recipe cannot name a file outside its own
        workspace."""
        resolved: list[str] = []
        for relpath in self.input_paths:
            resolved.append(workspace.resolve(relpath))
        return tuple(resolved)
