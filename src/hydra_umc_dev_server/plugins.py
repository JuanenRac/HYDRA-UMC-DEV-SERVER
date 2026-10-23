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
its own and the server hands it no credential. By default (`isolation="process"`)
every call runs in a separate Python process that is started in isolated mode, in an empty
temporary directory, with a scrubbed environment and limits on its CPU time and on the size
of the files it writes, and that is killed when the call overruns; the module is handed to
it as the bytes that were approved, so it sees nothing of the API process (its token, its
memory) and cannot import files next to it. A plugin therefore keeps no state from one call
to the next. With `isolation="thread"` it runs in the SAME process as the API, which makes it
trusted code: enable only what you have read. In both modes the module that runs is the
very bytes whose SHA-256 you approved (the digest covers the manifest and the module). A generator returns its
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
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import types
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
ISOLATIONS = ("process", "thread")
MAX_PARALLEL_RUNS = 4          # plugin calls that may run at the same time (process mode)
MAX_STUCK_THREADS = 8          # overrunning calls still alive in thread mode before new ones are refused
CHILD_CPU_SECONDS = 30         # limit on the CPU time of one isolated call
CHILD_MAX_FILE_BYTES = 10 * 1024 * 1024
_RESULT_MARK = "\x00HYDRA-PLUGIN-RESULT\x00"

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


def read_plugin_bytes(directory: Path, manifest: PluginManifest) -> tuple[bytes, bytes]:
    """The manifest file and the entry module, each read exactly once."""
    return (directory / MANIFEST_NAME).read_bytes(), (directory / manifest.entry).read_bytes()


def digest_of(manifest: PluginManifest, manifest_bytes: bytes, entry_bytes: bytes) -> str:
    """SHA-256 over the manifest file and the entry module, in that order."""
    digest = hashlib.sha256()
    for file_name, content in ((MANIFEST_NAME, manifest_bytes), (manifest.entry, entry_bytes)):
        digest.update(file_name.encode("utf-8") + b"\0")
        digest.update(content)
    return digest.hexdigest()


def plugin_digest(directory: Path, manifest: PluginManifest) -> str:
    """SHA-256 over the manifest file and the entry module, in that order."""
    manifest_bytes, entry_bytes = read_plugin_bytes(directory, manifest)
    return digest_of(manifest, manifest_bytes, entry_bytes)


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
    # the approved bytes of the module, kept so the module that runs is the one that was approved
    source: bytes = b""

    def clear(self) -> None:
        self.checks, self.reports, self.generators = {}, {}, {}
        self.source = b""

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
    def __init__(self, isolation: str | None = None) -> None:
        if isolation is None:
            isolation = os.environ.get("HYDRA_DEV_SERVER_PLUGIN_ISOLATION", "process").strip().lower() or "process"
        if isolation not in ISOLATIONS:
            raise PluginError(f"isolation must be one of {ISOLATIONS}")
        self.isolation = isolation
        self._records: dict[str, PluginRecord] = {}
        self._problems: list[dict] = []
        # the API serves requests in parallel threads: rescan, enable, disable and the
        # runs all touch the same records
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(MAX_PARALLEL_RUNS)
        self._stuck: list[threading.Thread] = []

    # -- discovery ---------------------------------------------------------
    def discover(self, root: Path) -> None:
        with self._lock:
            self._discover(root)

    def _discover(self, root: Path) -> None:
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
        with self._lock:
            return [self._records[name].describe() for name in sorted(self._records)]

    def _get(self, name: str) -> PluginRecord:
        record = self._records.get(name)
        if record is None:
            raise PluginError(f"no plugin named {name!r}")
        return record

    # -- lifecycle ---------------------------------------------------------
    def enable(self, name: str, expected_sha256: str) -> dict:
        with self._lock:
            return self._enable(name, expected_sha256)

    def _enable(self, name: str, expected_sha256: str) -> dict:
        record = self._get(name)
        if record.state == ENABLED:
            return record.describe()
        try:
            manifest_bytes, entry_bytes = read_plugin_bytes(record.directory, record.manifest)
        except OSError as exc:
            return self._fail(record, f"cannot read the plugin: {exc}")
        current = digest_of(record.manifest, manifest_bytes, entry_bytes)
        if not isinstance(expected_sha256, str) or expected_sha256.lower() != current:
            return self._fail(record, "the plugin does not match the SHA-256 that was approved")
        record.digest = current
        # from here on only the bytes that were just approved are used, never the file again
        try:
            registration = _Registration(record.manifest.provides)
            if self.isolation == "process":
                names = _register_in_child(entry_bytes, record.manifest)
                for kind, target in (("checks", registration.checks), ("reports", registration.reports), ("generators", registration.generators)):
                    for item in names.get(kind, []):
                        target[item] = _isolated_proxy(record, kind, item)
            else:
                module = types.ModuleType(f"hydra_umc_dev_server_plugin_{record.manifest.name.replace('-', '_')}")
                module.__file__ = str(record.directory / record.manifest.entry)
                exec(compile(entry_bytes, module.__file__, "exec"), module.__dict__)  # noqa: S102 - the approved bytes
                register = getattr(module, "register", None)
                if not callable(register):
                    raise PluginError("the entry module defines no register(registry)")
                register(registration)
        except Exception as exc:  # a plugin may raise anything; it must never take the server down
            return self._fail(record, f"register failed: {type(exc).__name__}: {exc}")
        record.checks = registration.checks
        record.reports = registration.reports
        record.generators = registration.generators
        record.source = entry_bytes
        record.state = ENABLED
        record.detail = ""
        return record.describe()

    def disable(self, name: str) -> dict:
        with self._lock:
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
        with self._lock:
            record = self._get(name)
            if record.state != ENABLED:
                raise PluginError(f"plugin {name!r} is {record.state}, not enabled")
            return record

    def _run(self, record: PluginRecord, kind: str, item: str, function: Callable, args: tuple, timeout: float, label: str, shape: Callable[[object], dict]) -> dict:
        if self.isolation == "process":
            if not self._slots.acquire(blocking=False):
                return {"status": "error", "error": f"{MAX_PARALLEL_RUNS} plugin calls are already running; try again in a moment"}
            try:
                return _run_isolated(record.source, record.manifest, kind, item, args, timeout, label, shape)
            finally:
                self._slots.release()
        with self._lock:
            self._stuck = [t for t in self._stuck if t.is_alive()]
            stuck = len(self._stuck)
        if stuck >= MAX_STUCK_THREADS:
            return {"status": "error", "error": f"{stuck} earlier plugin calls are still running after their timeout; no new call is started"}
        return _run_bounded(function, args, timeout, label, shape, on_overrun=self._remember_stuck)

    def _remember_stuck(self, worker: threading.Thread) -> None:
        with self._lock:
            self._stuck.append(worker)

    def run_check(self, name: str, check: str, timeout: float = CHECK_TIMEOUT_SECONDS) -> dict:
        record = self._enabled(name)
        function = record.checks.get(check)
        if function is None:
            raise PluginError(f"plugin {name!r} has no check {check!r}")
        return self._run(record, "checks", check, function, (), timeout, "check", _as_dict_result)

    def run_report(self, name: str, report: str, timeout: float = REPORT_TIMEOUT_SECONDS) -> dict:
        record = self._enabled(name)
        function = record.reports.get(report)
        if function is None:
            raise PluginError(f"plugin {name!r} has no report {report!r}")
        return self._run(record, "reports", report, function, (), timeout, "report", _as_dict_result)

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
        return self._run(record, "generators", generator, function, (json.loads(encoded),), timeout, "generator", _as_generated_file)


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


def _run_bounded(function: Callable, args: tuple, timeout: float, label: str, shape: Callable[[object], dict], on_overrun: Callable[[threading.Thread], None] | None = None) -> dict:
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
        if on_overrun is not None:
            on_overrun(worker)  # a thread cannot be cancelled: it is counted so that they cannot pile up
        return {"status": "error", "error": f"the {label} did not finish within {timeout:g} s"}
    if "error" in outcome:
        return {"status": "error", "error": outcome["error"]}
    return _shape_result(outcome.get("result"), label, shape)


def _shape_result(result: object, label: str, shape: Callable[[object], dict]) -> dict:
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


# ---------------------------------------------------------------------------
# Process isolation
# ---------------------------------------------------------------------------
# The program every isolated call runs: it receives the approved module as text on stdin,
# executes it in a fresh namespace, collects what register() adds and either reports the
# names (action "register") or runs one item (action "run"). The answer follows a marker no
# plugin is expected to print, so plugin output on stdout cannot be taken for the answer.
_CHILD_PROGRAM = r"""
import json, sys
MARK = __MARK__
request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (request["cpu"], request["cpu"]))
    resource.setrlimit(resource.RLIMIT_FSIZE, (request["fsize"], request["fsize"]))
except Exception:
    pass

class Registration:
    def __init__(self, provides):
        self._provides = provides
        self.checks, self.reports, self.generators = {}, {}, {}
    def _add(self, kind, target, name, function):
        if kind not in self._provides:
            raise ValueError("the manifest does not declare " + kind + " in provides")
        if not isinstance(name, str) or not name or not callable(function) or name in target:
            raise ValueError(kind[:-1] + " " + repr(name) + " is not valid or is registered twice")
        target[name] = function
    def add_check(self, name, function):
        self._add("checks", self.checks, name, function)
    def add_report(self, name, function):
        self._add("reports", self.reports, name, function)
    def add_generator(self, name, function):
        self._add("generators", self.generators, name, function)

def answer(payload):
    sys.stdout.write(MARK + json.dumps(payload))
    sys.stdout.flush()

try:
    namespace = {"__name__": "plugin_entry", "__file__": request["entry"]}
    exec(compile(request["source"], request["entry"], "exec"), namespace)
    register = namespace.get("register")
    if not callable(register):
        raise ValueError("the entry module defines no register(registry)")
    registration = Registration(tuple(request["provides"]))
    register(registration)
    if request["action"] == "register":
        answer({"names": {"checks": sorted(registration.checks), "reports": sorted(registration.reports), "generators": sorted(registration.generators)}})
    else:
        function = getattr(registration, request["kind"])[request["name"]]
        answer({"result": function(*request["args"])})
except BaseException as exc:
    answer({"error": type(exc).__name__ + ": " + str(exc)})
""".replace("__MARK__", repr(_RESULT_MARK))


def _child_environment(scratch: str) -> dict[str, str]:
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": scratch, "TMPDIR": scratch, "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8"}
    if os.name == "nt":  # the interpreter needs these to start at all
        for key in ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR"):
            if key in os.environ:
                env[key] = os.environ[key]
        env["TEMP"] = env["TMP"] = scratch
        env["PATH"] = os.environ.get("PATH", "")
    return env


def _kill_group(proc: "subprocess.Popen[bytes]") -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _call_child(entry_bytes: bytes, manifest: PluginManifest, action: str, kind: str, item: str, args: tuple, timeout: float) -> dict:
    """One isolated call; returns the decoded answer, or {"error": ...} (a timeout starts with "timeout")."""
    try:
        request = json.dumps({
            "source": entry_bytes.decode("utf-8"), "entry": manifest.entry, "provides": list(manifest.provides), "action": action,
            "kind": kind, "name": item, "args": list(args), "cpu": CHILD_CPU_SECONDS, "fsize": CHILD_MAX_FILE_BYTES,
        }).encode("utf-8")
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        return {"error": f"the module cannot be handed to the isolated process: {exc}"}
    with tempfile.TemporaryDirectory(prefix="hydra-plugin-") as scratch:
        kwargs: dict = {"start_new_session": True} if os.name == "posix" else {}
        try:
            proc = subprocess.Popen(  # noqa: S603 - the interpreter running this server, a fixed program
                [sys.executable, "-I", "-c", _CHILD_PROGRAM],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=scratch, env=_child_environment(scratch), **kwargs,
            )
        except OSError as exc:
            return {"error": f"the isolated process could not be started: {exc}"}
        try:
            out, _ = proc.communicate(request, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            proc.communicate()
            return {"error": f"timeout: it did not finish within {timeout:g} s"}
        finally:
            _kill_group(proc)  # a plugin may leave a background process behind
    text = out[: MAX_RESULT_BYTES * 2 + 4096].decode("utf-8", errors="replace")
    _, marker, payload = text.rpartition(_RESULT_MARK)
    if not marker:
        return {"error": f"the isolated process ended without an answer (exit code {proc.returncode})"}
    try:
        decoded = json.loads(payload)
    except ValueError:
        return {"error": "the isolated process answered something that is not JSON"}
    return decoded if isinstance(decoded, dict) else {"error": "the isolated process answered the wrong shape"}


def _register_in_child(entry_bytes: bytes, manifest: PluginManifest) -> dict:
    answer = _call_child(entry_bytes, manifest, "register", "", "", (), CHECK_TIMEOUT_SECONDS)
    if "error" in answer:
        raise PluginError(str(answer["error"]))
    names = answer.get("names")
    if not isinstance(names, dict):
        raise PluginError("the isolated process did not report what the plugin registers")
    for kind, items in names.items():
        if kind not in KINDS or not isinstance(items, list) or not all(isinstance(i, str) and _NAME_RE.match(i) for i in items):
            raise PluginError("the plugin registers a name that is not valid")
    return names


def _isolated_proxy(record: PluginRecord, kind: str, item: str) -> Callable:
    """Stands for an item that lives in the isolated process; the registry runs it through _run_isolated."""
    def proxy(*_args: object, **_kwargs: object) -> dict:  # pragma: no cover
        raise PluginError("an isolated item is run through the registry")
    proxy.__name__ = f"{record.manifest.name}.{kind}.{item}"
    return proxy


def _run_isolated(entry_bytes: bytes, manifest: PluginManifest, kind: str, item: str, args: tuple, timeout: float, label: str, shape: Callable[[object], dict]) -> dict:
    answer = _call_child(entry_bytes, manifest, "run", kind, item, args, timeout)
    if "error" in answer:
        message = str(answer["error"])
        if message.startswith("timeout"):
            return {"status": "error", "error": f"the {label} did not finish within {timeout:g} s"}
        return {"status": "error", "error": message}
    return _shape_result(answer.get("result"), label, shape)
