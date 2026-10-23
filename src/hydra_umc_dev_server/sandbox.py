# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/sandbox.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Operating-system isolation of the task runner.

The scrubbed environment keeps secrets out of the *environment* of a task, but a
child that runs as the service user can still read that user's files (ssh keys, git
credentials, the token file of the API). This module wraps the command in a real
sandbox when the host has one:

  * `bubblewrap` (`bwrap`): a private mount namespace in which the system is
    read-only, the home of the service user does not exist, `/tmp` is empty, the
    only writable place is the workspace of the task, and (unless the policy opens
    it) there is no network.
  * `systemd-run`: a transient unit with `ProtectHome`, `ProtectSystem=strict`,
    `PrivateTmp`, `PrivateNetwork`, `NoNewPrivileges` and only the workspace
    writable. It needs a systemd that lets the service user start units.

The builders are pure functions that return the wrapped argv, so the exact command
line is tested without either program being installed. What they cannot prove is that
the kernel of a given host enforces them: `detect_sandbox` only says which program
was found, and the result of a run says which one was used.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import ConfigValidationError

SANDBOX_MODES = ("auto", "bubblewrap", "systemd-run", "none")

# The system directories a build or a test run needs to read. Only those that exist
# on the host are bound.
_SYSTEM_RO_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/opt")
_SYSTEM_RO_FILES = ("/etc/alternatives", "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/ssl", "/etc/ca-certificates")
_NETWORK_RO_FILES = ("/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf")


class SandboxUnavailableError(ConfigValidationError):
    """The policy asks for a sandbox (or requires one) and the host has none."""


@dataclass(frozen=True)
class SandboxSpec:
    mode: str = "auto"
    network: bool = False
    read_only_paths: tuple[str, ...] = field(default_factory=tuple)
    required: bool = False


def detect_sandbox(
    mode: str,
    *,
    which: Callable[[str], str | None] = shutil.which,
    os_name: str | None = None,
) -> str:
    """The sandbox that will be used: `bubblewrap`, `systemd-run` or `none`.

    `auto` takes bubblewrap, then systemd-run, then none. A named sandbox that is not
    installed raises: asking for isolation and silently running without it would be the
    worse outcome.
    """
    if mode not in SANDBOX_MODES:
        raise ConfigValidationError(f"sandbox must be one of {SANDBOX_MODES}, not {mode!r}")
    name = os.name if os_name is None else os_name
    if mode == "none":
        return "none"
    if name != "posix":
        if mode == "auto":
            return "none"
        raise SandboxUnavailableError(f"the sandbox {mode!r} needs a Linux host")
    if mode in ("auto", "bubblewrap") and which("bwrap"):
        return "bubblewrap"
    if mode in ("auto", "systemd-run") and which("systemd-run"):
        return "systemd-run"
    if mode == "auto":
        return "none"
    raise SandboxUnavailableError(f"the sandbox {mode!r} was asked for but its program is not installed")


def bubblewrap_argv(
    argv: tuple[str, ...],
    *,
    cwd: str,
    env: dict[str, str],
    spec: SandboxSpec,
    exists: Callable[[str], bool] = os.path.exists,
) -> tuple[str, ...]:
    """`bwrap` command line: the system read-only, the home absent, an empty /tmp, the
    workspace the only writable place, no network unless the policy opens it."""
    out: list[str] = ["bwrap", "--die-with-parent", "--new-session", "--unshare-all"]
    if spec.network:
        out.append("--share-net")
    for path in _SYSTEM_RO_DIRS + _SYSTEM_RO_FILES + (_NETWORK_RO_FILES if spec.network else ()):
        if exists(path):
            out += ["--ro-bind", path, path]
    for path in spec.read_only_paths:
        out += ["--ro-bind", path, path]
    out += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    out += ["--bind", cwd, cwd, "--chdir", cwd, "--clearenv"]
    for key in sorted(env):
        out += ["--setenv", key, env[key]]
    out.append("--")
    return tuple(out) + tuple(argv)


def systemd_run_argv(
    argv: tuple[str, ...],
    *,
    cwd: str,
    env: dict[str, str],
    spec: SandboxSpec,
    is_root: bool | None = None,
) -> tuple[str, ...]:
    """`systemd-run` command line for a transient unit with the same promises."""
    root = (os.geteuid() == 0) if is_root is None and hasattr(os, "geteuid") else bool(is_root)
    out: list[str] = ["systemd-run"]
    if not root:
        out.append("--user")
    out += ["--pipe", "--wait", "--collect", "--quiet", f"--working-directory={cwd}"]
    props = [
        "ProtectHome=yes", "ProtectSystem=strict", "PrivateTmp=yes", "PrivateDevices=yes",
        "NoNewPrivileges=yes", "ProtectKernelTunables=yes", "ProtectControlGroups=yes",
        f"ReadWritePaths={cwd}",
    ]
    if spec.read_only_paths:
        props.append("ReadOnlyPaths=" + " ".join(spec.read_only_paths))
    if not spec.network:
        props.append("PrivateNetwork=yes")
    for prop in props:
        out += ["-p", prop]
    for key in sorted(env):
        out.append(f"--setenv={key}={env[key]}")
    out.append("--")
    return tuple(out) + tuple(argv)


class SandboxedLauncher:
    """A `ProcessLauncher` that wraps every command in the sandbox found on the host.

    `used` says which one was applied (`bubblewrap`, `systemd-run` or `none`); with
    `spec.required` a host without any sandbox refuses to start the command.
    """

    def __init__(
        self, inner: Any, spec: SandboxSpec, *, which: Callable[[str], str | None] = shutil.which, os_name: str | None = None,
    ) -> None:
        self._inner = inner
        self._spec = spec
        self.used = detect_sandbox(spec.mode, which=which, os_name=os_name)
        if spec.required and self.used == "none":
            raise SandboxUnavailableError(
                "the task policy requires a sandbox and this host has neither bubblewrap nor systemd-run"
            )

    def spawn(self, argv: tuple[str, ...], *, cwd: str, env: dict[str, str]) -> Any:
        if self.used == "bubblewrap":
            wrapped = bubblewrap_argv(argv, cwd=cwd, env=env, spec=self._spec)
        elif self.used == "systemd-run":
            wrapped = systemd_run_argv(argv, cwd=cwd, env=env, spec=self._spec)
        else:
            return self._inner.spawn(argv, cwd=cwd, env=env)
        # the wrapper itself needs a PATH to be found; the task gets its own through --setenv
        return self._inner.spawn(wrapped, cwd=cwd, env={"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")})
