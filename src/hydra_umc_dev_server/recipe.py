# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/recipe.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
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

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any

from .config import ConfigValidationError, TaskPolicy, _require_positive_int, _require_str
from .workspace import Workspace, _require_safe_id

# A recipe cannot ask for an unbounded run - DS05 refines leases/limits,
# but even at DS04 a timeout must be real and sane.
_MAX_TIMEOUT_SECONDS = 60 * 60  # one hour
_REVISION = re.compile(r"^[0-9a-fA-F]{7,64}$|^v?\d+\.\d+\.\d+$|^refs/tags/[\w./-]+$")


def command_key(command0: str) -> str:
    """`./build.sh` and `build.sh` name the same allowed script."""
    return command0[2:] if command0.startswith("./") else command0


# Options that make a well-known tool load code or read configuration from a place the
# recipe never declared (pytest runs `conftest.py` and any plugin it is told to load).
# For `-p` only the harmless form `-p no:<plugin>` is accepted.
_DENIED_OPTIONS: dict[str, tuple[str, ...]] = {
    "pytest": ("-p", "-c", "-o", "--rootdir", "--confcutdir", "--basetemp", "--override-ini", "--import-mode", "--pyargs", "--config-file", "--cache-clear-dir"),
    "python": ("-c", "-i", "--command"),
    "python3": ("-c", "-i", "--command"),
    "sh": ("-c",),
    "bash": ("-c", "--rcfile", "--init-file"),
    "node": ("-e", "--eval", "-p", "--print", "-r", "--require", "--import"),
    "perl": ("-e", "-E"),
    "ruby": ("-e",),
    "env": ("-S", "-C"),
}


def _is_path_escape(value: str) -> bool:
    if value.startswith(("/", "~", "\\")) or (len(value) > 2 and value[1] == ":" and value[2] in "\\/"):
        return True
    return ".." in re.split(r"[\\/]", value)


def argument_problems(command: tuple[str, ...], policy: TaskPolicy) -> list[str]:
    """Why the arguments of `command` (everything after the command itself) are not allowed.

    Always: no NUL, no absolute or home path, no `..` (also in the value of `--option=value`),
    and none of the options that load code of the tool (`_DENIED_OPTIONS`). When the policy
    lists patterns for the command in `allowed_arguments`, every argument must match one."""
    problems: list[str] = []
    if not command:
        return problems
    key = command_key(command[0])
    args = command[1:]
    denied = _DENIED_OPTIONS.get(key.rsplit("/", 1)[-1], ())
    patterns = policy.allowed_arguments.get(key) or policy.allowed_arguments.get(command[0])
    for index, arg in enumerate(args):
        if "\x00" in arg:
            problems.append(f"argument {index + 1} holds a NUL byte")
            continue
        head, _, value = arg.partition("=") if arg.startswith("-") else (arg, "", "")
        listed = patterns is not None and any(fnmatch.fnmatchcase(arg, pattern) for pattern in patterns)
        if arg.startswith("-") and not listed:  # an option the policy names itself is the operator's decision
            for option in denied:
                if arg == option or arg.startswith(option + "=") or (not option.startswith("--") and len(option) == 2 and arg.startswith(option) and len(arg) > 2 and not arg.startswith("--")):
                    if option == "-p" and (arg == "-p" and index + 1 < len(args) and args[index + 1].startswith("no:") or arg.startswith("-pno:")):
                        break
                    problems.append(f"the option {head!r} is not allowed for {key!r} (it loads code or configuration the recipe did not declare)")
                    break
        for candidate in ((value,) if value else ()) + (() if arg.startswith("-") else (arg,)):
            if _is_path_escape(candidate):
                problems.append(f"argument {index + 1} {arg!r} points outside the workspace (absolute, home or '..' path)")
                break
        if patterns is not None and not any(fnmatch.fnmatchcase(arg, pattern) for pattern in patterns):
            problems.append(f"argument {index + 1} {arg!r} is not in the policy's allowed_arguments for {key!r}")
    return problems


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
        if self.command and command_key(self.command[0]) not in {command_key(c) for c in policy.allowed_commands}:
            raise ConfigValidationError(
                f"command {self.command[0]!r} is not in the policy's allowed_commands "
                f"{tuple(policy.allowed_commands)!r}"
            )
        problems = argument_problems(self.command, policy)
        if problems:
            raise ConfigValidationError("; ".join(problems))

    def resolved_input_paths(self, workspace: Workspace, fs: Any = None) -> tuple[str, ...]:
        """Every declared input path, resolved inside `workspace`. Raises
        `WorkspaceEscapeError` (a `ConfigValidationError` subclass) for any
        path that climbs out - a recipe cannot name a file outside its own
        workspace. With `fs` (a `WorkspaceFs`) the path is also resolved the way
        the operating system would open it, so a symbolic link that points out of
        the workspace is refused too."""
        resolved: list[str] = []
        for relpath in self.input_paths:
            resolved.append(workspace.resolve_with(relpath, fs) if fs is not None else workspace.resolve(relpath))
        return tuple(resolved)
