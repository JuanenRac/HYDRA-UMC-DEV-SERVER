# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/config.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Real, tested configuration schema for DS01 (contracts, limits and a
verifiable skeleton). Three declarative documents, each independently
loadable/validatable, matching this delivery's own acceptance criterion:
both valid and invalid configuration are tested, and no task has
deployment permission by default.

Nothing in this module talks to a real host, workspace or task - that is
DS02/DS04/DS05, later deliveries. This is the contract those deliveries
will build on, not a preview of their behavior.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigValidationError(ValueError):
    """Raised for a real, specific reason a configuration document is
    invalid - never a bare `ValueError`, so a caller (and a future
    workspace/task runner) can report exactly which field failed and why,
    not just that something did."""


def _require_str(data: dict[str, Any], field_name: str, errors: list[str]) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value:
        errors.append(f"{field_name!r} must be a non-empty string")
        return ""
    return value


def _require_bool(data: dict[str, Any], field_name: str, errors: list[str], *, default: bool) -> bool:
    if field_name not in data:
        return default
    value = data[field_name]
    if not isinstance(value, bool):
        errors.append(f"{field_name!r} must be a real boolean (true/false), not {value!r}")
        return default
    return value


def _require_positive_int(data: dict[str, Any], field_name: str, errors: list[str], *, default: int) -> int:
    if field_name not in data:
        return default
    value = data[field_name]
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        errors.append(f"{field_name!r} must be a positive integer, not {value!r}")
        return default
    return value


@dataclass(frozen=True)
class HostProfile:
    """Who this host is and where it keeps state - real fields from this
    project's own disk layout and migration concept (see
    docs/ARCHITECTURE.md), not yet consumed by any runner (that is
    DS02)."""
    hostname: str
    arch: str
    storage_root: str
    created_from: str

    _VALID_CREATED_FROM = ("fresh-image", "migrated-from-pc")

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "arch": self.arch,
            "storage_root": self.storage_root,
            "created_from": self.created_from,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "HostProfile":
        if not isinstance(data, dict):
            raise ConfigValidationError("host profile must be a JSON object")
        errors: list[str] = []
        hostname = _require_str(data, "hostname", errors)
        arch = _require_str(data, "arch", errors)
        storage_root = _require_str(data, "storage_root", errors)
        created_from = _require_str(data, "created_from", errors)
        if storage_root and not storage_root.startswith("/"):
            errors.append(f"'storage_root' must be an absolute path, got {storage_root!r}")
        if created_from and created_from not in HostProfile._VALID_CREATED_FROM:
            errors.append(f"'created_from' must be one of {HostProfile._VALID_CREATED_FROM}, not {created_from!r}")
        if errors:
            raise ConfigValidationError("; ".join(errors))
        return HostProfile(hostname=hostname, arch=arch, storage_root=storage_root, created_from=created_from)


@dataclass(frozen=True)
class ToolchainPolicy:
    """Which language toolchains this host is expected to have available -
    real fields from 13.7 ("Herramientas y perfiles de compilacion"), a
    declared expectation to check against later (DS04), not yet enforced
    by anything in this delivery."""
    name: str
    min_version: str
    required: bool

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "min_version": self.min_version, "required": self.required}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ToolchainPolicy":
        if not isinstance(data, dict):
            raise ConfigValidationError("toolchain entry must be a JSON object")
        errors: list[str] = []
        name = _require_str(data, "name", errors)
        min_version = _require_str(data, "min_version", errors)
        required = _require_bool(data, "required", errors, default=True)
        if errors:
            raise ConfigValidationError("; ".join(errors))
        return ToolchainPolicy(name=name, min_version=min_version, required=required)


@dataclass(frozen=True)
class TaskPolicy:
    """The hard boundary DS01's own acceptance criterion names explicitly:
    "ninguna tarea tiene permiso de despliegue por defecto". allow_deploy
    defaults to False and only from_dict()'ing a document that sets it to
    the literal boolean `true` can ever produce a policy with it enabled -
    a missing, misspelled or non-boolean field never silently grants it.
    """
    allow_deploy: bool
    max_concurrent_tasks: int
    allowed_commands: tuple[str, ...] = field(default_factory=tuple)
    # Per command, the arguments (after the command itself) it may be given, as
    # fnmatch patterns. A command with an entry here accepts nothing else; a command
    # without one is only held to the baseline rules of `recipe.argument_problems`.
    allowed_arguments: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Operating-system isolation of the runner (see sandbox.py): "auto" uses
    # bubblewrap or systemd-run when the host has one, "none" turns it off.
    sandbox: str = "auto"
    # When true, a host without any sandbox refuses to run a task at all.
    sandbox_required: bool = False
    # The sandbox has no network unless this is true.
    sandbox_network: bool = False
    # Directories outside the system ones that the task may read (a toolchain, a venv).
    sandbox_read_only_paths: tuple[str, ...] = field(default_factory=tuple)
    # Resource limits of the task's cgroup, applied by the systemd-run sandbox (bubblewrap has no cgroup, so with it
    # they are not enforced and the result says which sandbox ran): "2G" of memory, "200%" of CPU (two cores),
    # at most 512 tasks (processes and threads). None leaves that limit to the host.
    sandbox_memory_max: str | None = None
    sandbox_cpu_quota: str | None = None
    sandbox_tasks_max: int | None = None
    # What happens to the workspace after the run: "keep" always keeps it,
    # "delete-on-success" removes it after a completed run with exit code 0,
    # "delete" removes it after every run.
    workspace_retention: str = "delete-on-success"
    # Where each repository name of a recipe is fetched from (a URL or a local path).
    # A repository without an entry is not staged (the workspace stays empty).
    repo_sources: dict[str, str] = field(default_factory=dict)

    _SANDBOX_MODES = ("auto", "bubblewrap", "systemd-run", "none")
    _RETENTIONS = ("keep", "delete-on-success", "delete")

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_deploy": self.allow_deploy,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "allowed_commands": list(self.allowed_commands),
            "allowed_arguments": {k: list(v) for k, v in self.allowed_arguments.items()},
            "sandbox": self.sandbox,
            "sandbox_required": self.sandbox_required,
            "sandbox_network": self.sandbox_network,
            "sandbox_read_only_paths": list(self.sandbox_read_only_paths),
            "sandbox_memory_max": self.sandbox_memory_max,
            "sandbox_cpu_quota": self.sandbox_cpu_quota,
            "sandbox_tasks_max": self.sandbox_tasks_max,
            "workspace_retention": self.workspace_retention,
            "repo_sources": dict(self.repo_sources),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TaskPolicy":
        if not isinstance(data, dict):
            raise ConfigValidationError("task policy must be a JSON object")
        errors: list[str] = []
        allow_deploy = _require_bool(data, "allow_deploy", errors, default=False)
        max_concurrent_tasks = _require_positive_int(data, "max_concurrent_tasks", errors, default=1)
        allowed_commands_raw = data.get("allowed_commands", [])
        if not isinstance(allowed_commands_raw, list) or not all(isinstance(c, str) and c for c in allowed_commands_raw):
            errors.append("'allowed_commands' must be a list of non-empty strings")
            allowed_commands_raw = []
        arguments_raw = data.get("allowed_arguments", {})
        arguments: dict[str, tuple[str, ...]] = {}
        if not isinstance(arguments_raw, dict):
            errors.append("'allowed_arguments' must be an object of command -> list of patterns")
        else:
            for command, patterns in arguments_raw.items():
                if not isinstance(patterns, list) or not all(isinstance(p, str) and p for p in patterns):
                    errors.append(f"'allowed_arguments'[{command!r}] must be a list of non-empty strings")
                else:
                    arguments[command] = tuple(patterns)
        sandbox = data.get("sandbox", "auto")
        if sandbox not in TaskPolicy._SANDBOX_MODES:
            errors.append(f"'sandbox' must be one of {TaskPolicy._SANDBOX_MODES}, not {sandbox!r}")
            sandbox = "auto"
        sandbox_required = _require_bool(data, "sandbox_required", errors, default=False)
        sandbox_network = _require_bool(data, "sandbox_network", errors, default=False)
        ro_raw = data.get("sandbox_read_only_paths", [])
        ro_paths: tuple[str, ...] = ()
        if not isinstance(ro_raw, list) or not all(isinstance(p, str) and p.startswith("/") for p in ro_raw):
            errors.append("'sandbox_read_only_paths' must be a list of absolute paths")
        else:
            ro_paths = tuple(ro_raw)
        memory_max = data.get("sandbox_memory_max")
        if memory_max is not None and not (isinstance(memory_max, str) and re.fullmatch(r"[1-9][0-9]*[KMGT]?", memory_max)):
            errors.append("'sandbox_memory_max' must look like '512M' or '2G' (a number and an optional K, M, G or T)")
            memory_max = None
        cpu_quota = data.get("sandbox_cpu_quota")
        if cpu_quota is not None and not (isinstance(cpu_quota, str) and re.fullmatch(r"[1-9][0-9]{0,4}%", cpu_quota)):
            errors.append("'sandbox_cpu_quota' must look like '200%' (100% is one core)")
            cpu_quota = None
        tasks_max = data.get("sandbox_tasks_max")
        if tasks_max is not None and (isinstance(tasks_max, bool) or not isinstance(tasks_max, int) or tasks_max < 1):
            errors.append("'sandbox_tasks_max' must be a positive integer")
            tasks_max = None
        retention = data.get("workspace_retention", "delete-on-success")
        if retention not in TaskPolicy._RETENTIONS:
            errors.append(f"'workspace_retention' must be one of {TaskPolicy._RETENTIONS}, not {retention!r}")
            retention = "delete-on-success"
        sources_raw = data.get("repo_sources", {})
        sources: dict[str, str] = {}
        if not isinstance(sources_raw, dict) or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in sources_raw.items()):
            errors.append("'repo_sources' must be an object of repository name -> URL or path")
        else:
            sources = dict(sources_raw)
        if errors:
            raise ConfigValidationError("; ".join(errors))
        return TaskPolicy(
            allow_deploy=allow_deploy,
            max_concurrent_tasks=max_concurrent_tasks,
            allowed_commands=tuple(allowed_commands_raw),
            allowed_arguments=arguments,
            sandbox=sandbox,
            sandbox_required=sandbox_required,
            sandbox_network=sandbox_network,
            sandbox_read_only_paths=ro_paths,
            sandbox_memory_max=memory_max,
            sandbox_cpu_quota=cpu_quota,
            sandbox_tasks_max=tasks_max,
            workspace_retention=retention,
            repo_sources=sources,
        )


def load_json_document(path: Path) -> dict[str, Any]:
    """Reads and parses one JSON document, raising ConfigValidationError
    (never a bare json.JSONDecodeError/OSError) for a real, specific
    reason - the same "no bare exception reaches the CLI" convention this
    ecosystem's other config loaders already use."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigValidationError(f"could not read {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigValidationError(f"{path} must contain a JSON object, not a {type(data).__name__}")
    return data
