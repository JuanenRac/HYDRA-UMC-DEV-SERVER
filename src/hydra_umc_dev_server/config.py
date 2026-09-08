# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/config.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_deploy": self.allow_deploy,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "allowed_commands": list(self.allowed_commands),
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
        if errors:
            raise ConfigValidationError("; ".join(errors))
        return TaskPolicy(
            allow_deploy=allow_deploy,
            max_concurrent_tasks=max_concurrent_tasks,
            allowed_commands=tuple(allowed_commands_raw),
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
