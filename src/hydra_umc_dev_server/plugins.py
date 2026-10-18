# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/plugins.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Plugin lifecycle: discover, validate, enable, run, disable.

A plugin is a directory holding `plugin.json` and one Python module. It is
inert until an operator enables it, and enabling requires the operator to
name the SHA-256 of that plugin (its manifest and module together) - a
plugin whose files changed since they were reviewed is refused, not loaded.
A plugin offers named items of up to three kinds, declared in its manifest
with `provides`: *checks* (a function that inspects something and returns a
JSON dict), *reports* (a function that returns a JSON dict describing the
state of something, to be read) and *generators* (a function that takes a small
dict of parameters and returns one generated text file). It gets no route of
its own, and the server hands it no credential - but it runs in the SAME process
as the API, so a plugin is trusted code: enable only what you have read. The
SHA-256 you approve covers the manifest and the module. A generator returns its
text to the caller; the server never writes it to disk.

States: `discovered` -> `enabled` (after a verified load) -> `disabled`;
`failed` when validation, the digest check or the plugin's own `register`
raised. Enabling is all or nothing: if `register` raises, or tries to add a
kind the manifest does not declare, the plugin ends `failed` with nothing
registered. A running item is bounded by a timeout and by a size limit on what
it returns, and one that raises, overruns or returns the wrong shape is
reported as an error, never as a result; that never changes the plugin's state
or affects any other plugin.

`plugin.json`:
    {"name": "lint-report", "version": "0.1.0", "api_version": 1,
     "entry": "plugin.py", "provides": ["checks", "reports", "generators"]}

`provides` is optional and defaults to `["checks"]`, so a plugin written before
reports and generators existed keeps working unchanged. `entry` must be a plain
file name inside the plugin directory, and its module must define
`register(registry)`, which calls `registry.add_check("name", callable)`,
`registry.add_report("name", callable)` and `registry.add_generator("name",
callable)` for what it offers (only the kinds it declares).
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
REPORT_TIMEOUT_SECONDS = 10.0
GENERATOR_TIMEOUT_SECONDS = 10.0
MAX_RESULT_BYTES = 256 * 1024  # what a report may return, or a generator's text
MAX_PARAMS_BYTES = 4096        # what a generator may be handed
KINDS = ("checks", "reports", "generators")

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ENTRY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*\.py$")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")

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
    provides: tuple[str, ...] = ("checks",)

    @classmethod
    def from_dict(cls, raw: object) -> "PluginManifest":
        if not isinstance(raw, dict):
            raise PluginError("plugin.json must be a JSON object")
        unknown = sorted(set(raw) - {"name", "version", "api_version", "entry", "provides"})
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
        provides = raw.get("provides", ["checks"])
        if (
            not isinstance(provides, list) or not provides
            or not all(isinstance(kind, str) and kind in KINDS for kind in provides)
            or len(set(provides)) != len(provides)
        ):
            raise PluginError(f"provides must be a non-empty list of distinct values from {list(KINDS)}")
        return cls(name, version, api_version, entry, tuple(provides))


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
    reports: dict[str, Callable[[], dict]] = field(default_factory=dict)
    generators: dict[str, Callable[[dict], dict]] = field(default_factory=dict)

    def clear(self) -> None:
        self.checks, self.reports, self.generators = {}, {}, {}

    def describe(self) -> dict:
        return {
            "name": self.manifest.name,
            "version": self.manifest.version,
            "state": self.state,
            "detail": self.detail,
            "sha256": self.digest,
            "provides": list(self.manifest.provides),
            "checks": sorted(self.checks),
            "reports": sorted(self.reports),
            "generators": sorted(self.generators),
        }


class _Registration:
    """What a plugin's register() receives: it can add the kinds its manifest
    declares and nothing else."""

    def __init__(self, provides: tuple[str, ...] = ("checks",)) -> None:
        self._provides = provides
        self.checks: dict[str, Callable[[], dict]] = {}
        self.reports: dict[str, Callable[[], dict]] = {}
        self.generators: dict[str, Callable[[dict], dict]] = {}

    def _add(self, kind: str, target: dict, name: str, function: object) -> None:
        if kind not in self._provides:
            raise PluginError(f"the manifest does not declare {kind!r} in provides")
        label = kind[:-1]
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise PluginError(f"{label} name {name!r} is not valid")
        if not callable(function):
            raise PluginError(f"{label} {name!r} is not callable")
        if name in target:
            raise PluginError(f"{label} {name!r} is registered twice")
        target[name] = function

    def add_check(self, name: str, function: Callable[[], dict]) -> None:
        self._add("checks", self.checks, name, function)

    def add_report(self, name: str, function: Callable[[], dict]) -> None:
        self._add("reports", self.reports, name, function)

    def add_generator(self, name: str, function: Callable[[dict], dict]) -> None:
        self._add("generators", self.generators, name, function)


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
        registration = _Registration(record.manifest.provides)
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
        record.reports = registration.reports
        record.generators = registration.generators
        record.state = ENABLED
        record.detail = ""
        return record.describe()

    def disable(self, name: str) -> dict:
        record = self._get(name)
        record.clear()
        record.state = DISABLED
        record.detail = ""
        return record.describe()

    def _fail(self, record: PluginRecord, detail: str) -> dict:
        record.clear()
        record.state = FAILED
        record.detail = detail
        return record.describe()

    # -- running -----------------------------------------------------------
    def _enabled(self, name: str) -> PluginRecord:
        record = self._get(name)
        if record.state != ENABLED:
            raise PluginError(f"plugin {name!r} is {record.state}, not enabled")
        return record

    def run_check(self, name: str, check: str, timeout: float = CHECK_TIMEOUT_SECONDS) -> dict:
        record = self._enabled(name)
        function = record.checks.get(check)
        if function is None:
            raise PluginError(f"plugin {name!r} has no check {check!r}")
        return _run_bounded(function, (), timeout, "check", _as_dict_result)

    def run_report(self, name: str, report: str, timeout: float = REPORT_TIMEOUT_SECONDS) -> dict:
        record = self._enabled(name)
        function = record.reports.get(report)
        if function is None:
            raise PluginError(f"plugin {name!r} has no report {report!r}")
        return _run_bounded(function, (), timeout, "report", _as_dict_result)

    def run_generator(
        self, name: str, generator: str, params: dict | None = None, timeout: float = GENERATOR_TIMEOUT_SECONDS
    ) -> dict:
        record = self._enabled(name)
        function = record.generators.get(generator)
        if function is None:
            raise PluginError(f"plugin {name!r} has no generator {generator!r}")
        params = {} if params is None else params
        if not isinstance(params, dict):
            raise PluginError("the generator parameters must be a JSON object")
        try:
            encoded = json.dumps(params)
        except (TypeError, ValueError) as exc:
            raise PluginError("the generator parameters are not JSON") from exc
        if len(encoded.encode("utf-8")) > MAX_PARAMS_BYTES:
            raise PluginError(f"the generator parameters may be at most {MAX_PARAMS_BYTES} bytes")
        # the plugin gets its own copy, so it cannot alter what the caller holds
        return _run_bounded(function, (json.loads(encoded),), timeout, "generator", _as_generated_file)


def _as_dict_result(result: object) -> dict:
    if not isinstance(result, dict):
        return {"status": "error", "error": "it must return a dict"}
    return {"status": "ok", "result": result}


def _as_generated_file(result: object) -> dict:
    """A generator returns {"filename": ..., "content": "text"}; nothing else."""
    if not isinstance(result, dict) or set(result) != {"filename", "content"}:
        return {"status": "error", "error": 'it must return {"filename": ..., "content": ...}'}
    filename, content = result["filename"], result["content"]
    if not isinstance(filename, str) or not _FILENAME_RE.match(filename) or ".." in filename:
        return {"status": "error", "error": "filename must be a plain file name (letters, digits, . _ -)"}
    if not isinstance(content, str):
        return {"status": "error", "error": "content must be text"}
    return {"status": "ok", "result": {"filename": filename, "content": content}}


def _run_bounded(function: Callable, args: tuple, timeout: float, label: str, shape: Callable[[object], dict]) -> dict:
    """Run one plugin function in a worker thread with a timeout, then check
    what it returned: JSON, the right shape, and no larger than MAX_RESULT_BYTES.
    Whatever goes wrong is an error entry; nothing propagates."""
    outcome: dict = {}

    def target() -> None:
        try:
            outcome["result"] = function(*args)
        except BaseException as exc:  # noqa: BLE001 - a plugin may raise anything, including SystemExit
            outcome["error"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return {"status": "error", "error": f"the {label} did not finish within {timeout:g} s"}
    if "error" in outcome:
        return {"status": "error", "error": outcome["error"]}
    result = outcome.get("result")
    try:
        encoded = json.dumps(result)
    except (TypeError, ValueError):
        return {"status": "error", "error": f"the {label} returned something that is not JSON"}
    if len(encoded.encode("utf-8")) > MAX_RESULT_BYTES:
        return {"status": "error", "error": f"the {label} returned more than {MAX_RESULT_BYTES} bytes"}
    shaped = shape(result)
    if shaped["status"] == "error":
        shaped["error"] = f"the {label}: {shaped['error']}"
    return shaped
