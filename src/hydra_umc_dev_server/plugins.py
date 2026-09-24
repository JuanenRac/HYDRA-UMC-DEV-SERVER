# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/plugins.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Plugin lifecycle: discover, validate, enable, run, disable.

A plugin is a directory holding `plugin.json` and one Python module. It is
inert until an operator enables it, and enabling requires the operator to
name the SHA-256 of that plugin (its manifest and module together) - a
plugin whose files changed since they were reviewed is refused, not loaded.
A plugin only adds named *checks*: functions that return a JSON-serializable
dict. It gets no route, no credentials and no way to change what the server
allows.

States: `discovered` -> `enabled` (after a verified load) -> `disabled`;
`failed` when validation, the digest check or the plugin's own `register`
raised. A running check is bounded by a timeout, and one that raises or
overruns is reported as an error, never as a result.

`plugin.json`:
    {"name": "lint-report", "version": "0.1.0", "api_version": 1,
     "entry": "plugin.py"}

`entry` must be a plain file name inside the plugin directory, and its
module must define `register(registry)`, which calls
`registry.add_check("name", callable)` for each check it offers.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PLUGIN_API_VERSION = 1
MANIFEST_NAME = "plugin.json"
CHECK_TIMEOUT_SECONDS = 10.0

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ENTRY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*\.py$")

DISCOVERED = "discovered"
ENABLED = "enabled"
DISABLED = "disabled"
FAILED = "failed"


class PluginError(ValueError):
    """A plugin operation was refused; the message says why."""


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    api_version: int
    entry: str

    @classmethod
    def from_dict(cls, raw: object) -> "PluginManifest":
        if not isinstance(raw, dict):
            raise PluginError("plugin.json must be a JSON object")
        unknown = sorted(set(raw) - {"name", "version", "api_version", "entry"})
        if unknown:
            raise PluginError(f"plugin.json has unknown field(s) {unknown}")
        name, version, api_version, entry = (raw.get(k) for k in ("name", "version", "api_version", "entry"))
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise PluginError("name must be 1-40 characters: lowercase letters, digits and hyphens")
        if not isinstance(version, str) or not _VERSION_RE.match(version):
            raise PluginError("version must look like 1.2.3")
        if isinstance(api_version, bool) or api_version != PLUGIN_API_VERSION:
            raise PluginError(f"api_version must be {PLUGIN_API_VERSION}")
        if not isinstance(entry, str) or not _ENTRY_RE.match(entry):
            raise PluginError("entry must be a plain .py file name inside the plugin directory")
        return cls(name, version, api_version, entry)


def plugin_digest(directory: Path, manifest: PluginManifest) -> str:
    """SHA-256 over the manifest file and the entry module, in that order."""
    digest = hashlib.sha256()
    for file_name in (MANIFEST_NAME, manifest.entry):
        digest.update(file_name.encode("utf-8") + b"\0")
        digest.update((directory / file_name).read_bytes())
    return digest.hexdigest()


@dataclass
class PluginRecord:
    manifest: PluginManifest
    directory: Path
    digest: str
    state: str = DISCOVERED
    detail: str = ""
    checks: dict[str, Callable[[], dict]] = field(default_factory=dict)

    def describe(self) -> dict:
        return {
            "name": self.manifest.name,
            "version": self.manifest.version,
            "state": self.state,
            "detail": self.detail,
            "sha256": self.digest,
            "checks": sorted(self.checks),
        }


class _Registration:
    """What a plugin's register() receives: it can add checks and nothing else."""

    def __init__(self) -> None:
        self.checks: dict[str, Callable[[], dict]] = {}

    def add_check(self, name: str, function: Callable[[], dict]) -> None:
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise PluginError(f"check name {name!r} is not valid")
        if not callable(function):
            raise PluginError(f"check {name!r} is not callable")
        if name in self.checks:
            raise PluginError(f"check {name!r} is registered twice")
        self.checks[name] = function


class PluginRegistry:
    def __init__(self) -> None:
        self._records: dict[str, PluginRecord] = {}
        self._problems: list[dict] = []

    # -- discovery ---------------------------------------------------------
    def discover(self, root: Path) -> None:
        """Read every immediate subdirectory of `root` that holds a plugin.json.

        Nothing is imported. A directory with a broken plugin is reported in
        `problems` and does not stop the others.
        """
        self._problems = []
        found: dict[str, PluginRecord] = {}
        if not root.is_dir():
            self._records = {}
            return
        for directory in sorted(p for p in root.iterdir() if p.is_dir()):
            manifest_path = directory / MANIFEST_NAME
            if not manifest_path.is_file():
                continue
            try:
                manifest = PluginManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
                if not (directory / manifest.entry).is_file():
                    raise PluginError(f"entry {manifest.entry!r} is missing")
                if manifest.name in found:
                    raise PluginError(f"name {manifest.name!r} is already used by another directory")
                record = PluginRecord(manifest, directory, plugin_digest(directory, manifest))
            except (PluginError, OSError, ValueError) as exc:
                self._problems.append({"directory": directory.name, "reason": str(exc)})
                continue
            previous = self._records.get(manifest.name)
            if previous is not None and previous.digest == record.digest:
                record = previous  # unchanged on disk: keep its state
            found[manifest.name] = record
        self._records = found

    @property
    def problems(self) -> list[dict]:
        return list(self._problems)

    def list(self) -> list[dict]:
        return [self._records[name].describe() for name in sorted(self._records)]

    def _get(self, name: str) -> PluginRecord:
        record = self._records.get(name)
        if record is None:
            raise PluginError(f"no plugin named {name!r}")
        return record

    # -- lifecycle ---------------------------------------------------------
    def enable(self, name: str, expected_sha256: str) -> dict:
        record = self._get(name)
        if record.state == ENABLED:
            return record.describe()
        try:
            current = plugin_digest(record.directory, record.manifest)
        except OSError as exc:
            return self._fail(record, f"cannot read the plugin: {exc}")
        if not isinstance(expected_sha256, str) or expected_sha256.lower() != current:
            return self._fail(record, "the plugin does not match the SHA-256 that was approved")
        record.digest = current
        registration = _Registration()
        try:
            spec = importlib.util.spec_from_file_location(
                f"hydra_umc_dev_server_plugin_{record.manifest.name.replace('-', '_')}",
                record.directory / record.manifest.entry,
            )
            if spec is None or spec.loader is None:
                raise PluginError("the entry module cannot be loaded")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if not callable(register):
                raise PluginError("the entry module defines no register(registry)")
            register(registration)
        except Exception as exc:  # a plugin may raise anything; it must never take the server down
            return self._fail(record, f"register failed: {type(exc).__name__}: {exc}")
        record.checks = registration.checks
        record.state = ENABLED
        record.detail = ""
        return record.describe()

    def disable(self, name: str) -> dict:
        record = self._get(name)
        record.checks = {}
        record.state = DISABLED
        record.detail = ""
        return record.describe()

    def _fail(self, record: PluginRecord, detail: str) -> dict:
        record.checks = {}
        record.state = FAILED
        record.detail = detail
        return record.describe()

    # -- running -----------------------------------------------------------
    def run_check(self, name: str, check: str, timeout: float = CHECK_TIMEOUT_SECONDS) -> dict:
        record = self._get(name)
        if record.state != ENABLED:
            raise PluginError(f"plugin {name!r} is {record.state}, not enabled")
        function = record.checks.get(check)
        if function is None:
            raise PluginError(f"plugin {name!r} has no check {check!r}")
        outcome: dict = {}

        def target() -> None:
            try:
                outcome["result"] = function()
            except Exception as exc:
                outcome["error"] = f"{type(exc).__name__}: {exc}"

        worker = threading.Thread(target=target, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            return {"status": "error", "error": f"the check did not finish within {timeout:g} s"}
        if "error" in outcome:
            return {"status": "error", "error": outcome["error"]}
        result = outcome.get("result")
        try:
            json.dumps(result)
        except (TypeError, ValueError):
            return {"status": "error", "error": "the check returned something that is not JSON"}
        if not isinstance(result, dict):
            return {"status": "error", "error": "the check must return a dict"}
        return {"status": "ok", "result": result}
