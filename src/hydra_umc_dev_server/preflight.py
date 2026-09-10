# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/preflight.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS02 preflight - reads a `RemoteStationProfile` and reports whether a
host is actually ready to become that station. It never changes the host:
no user is created, no package installed, no port opened. It only asks
questions and returns a structured, honest answer - the same "validates
and discovers, never runs anything" line DS01 already holds.

Every real host query goes through the injectable `HostInspector`
protocol, so a test drives the whole thing with a fake and nothing
touches a real machine - the same "nothing talks to a real host in a
test" convention `config.py` already states for DS01. `SystemHostInspector`
is the one place real `sys`/`shutil`/`socket`/`pwd` calls live, imported
lazily so a non-POSIX box can still import this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .config import ConfigValidationError
from .remote_station import RemoteStationProfile

_MIN_PYTHON = (3, 11, 0)


@runtime_checkable
class HostInspector(Protocol):
    """The read-only seam between preflight logic and a real host. Every
    method answers a question; none of them changes anything."""

    def python_version(self) -> tuple[int, int, int]: ...

    def free_disk_gb(self, path: str) -> float | None:
        """Free space on the filesystem holding `path`, or None if `path`
        does not exist (a real, reportable "the workspace parent is
        missing", not a crash)."""

    def has_executable(self, name: str) -> bool: ...

    def path_is_writable(self, path: str) -> bool: ...

    def tcp_port_is_free(self, bind_address: str, port: int) -> bool: ...

    def user_exists(self, name: str) -> bool: ...

    def user_is_system_account(self, name: str) -> bool:
        """True only for a real dedicated service account - not a normal
        login user, and never uid 0."""


@dataclass(frozen=True)
class PreflightCheck:
    """One named yes/no question and the real reason for the answer."""

    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def failures(self) -> tuple[PreflightCheck, ...]:
        return tuple(check for check in self.checks if not check.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
            "failures": [check.name for check in self.failures()],
        }


def run_preflight(
    profile: RemoteStationProfile,
    inspector: HostInspector,
    *,
    min_python: tuple[int, int, int] = _MIN_PYTHON,
) -> PreflightReport:
    """Pure: turns a profile + a host inspector into a report. Does not
    touch a real host itself - all host contact is the inspector's, and a
    test passes a fake one."""
    checks: list[PreflightCheck] = []

    actual_python = inspector.python_version()
    checks.append(
        PreflightCheck(
            name="python-version",
            ok=actual_python >= min_python,
            detail=(
                f"found {'.'.join(map(str, actual_python))}, "
                f"need >= {'.'.join(map(str, min_python))}"
            ),
        )
    )

    workspace = profile.identity.workspace_path()
    free_gb = inspector.free_disk_gb(workspace)
    if free_gb is None:
        checks.append(
            PreflightCheck(
                name="free-disk",
                ok=False,
                detail=f"cannot measure free space: {workspace} has no existing parent",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                name="free-disk",
                ok=free_gb >= profile.min_free_disk_gb,
                detail=f"{free_gb:.1f} GiB free at {workspace}, need >= {profile.min_free_disk_gb:.1f}",
            )
        )

    checks.append(
        PreflightCheck(
            name="workspace-writable",
            ok=inspector.path_is_writable(workspace),
            detail=f"{workspace} must be writable by {profile.identity.user}",
        )
    )

    for tool in profile.required_tools:
        present = inspector.has_executable(tool.name)
        checks.append(
            PreflightCheck(
                name=f"tool:{tool.name}",
                # An optional tool that is simply absent is not a failure.
                ok=present or not tool.required,
                detail=(
                    f"{tool.name} {'found' if present else 'not found'} on PATH"
                    + ("" if tool.required else " (optional)")
                ),
            )
        )

    access = profile.remote_access
    checks.append(
        PreflightCheck(
            name="remote-port-free",
            ok=inspector.tcp_port_is_free(access.bind_address, access.port),
            detail=f"{access.bind_address}:{access.port} must be free for the {access.kind} endpoint",
        )
    )

    checks.append(
        PreflightCheck(
            name="bind-address-is-private",
            ok=access.is_loopback_or_private() or access.allow_public_bind,
            detail=(
                f"{access.bind_address} is "
                + ("loopback/private" if access.is_loopback_or_private() else "routable")
                + ("; allowed by allow_public_bind" if access.allow_public_bind and not access.is_loopback_or_private() else "")
            ),
        )
    )

    user = profile.identity.user
    exists = inspector.user_exists(user)
    if not exists:
        checks.append(
            PreflightCheck(
                name="identity-user",
                ok=False,
                detail=f"system account {user!r} does not exist yet (DS02 provisioning would create it)",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                name="identity-user",
                ok=inspector.user_is_system_account(user),
                detail=(
                    f"{user!r} exists and is a dedicated system account"
                    if inspector.user_is_system_account(user)
                    else f"{user!r} exists but is a normal login user / uid 0 - refuse to run the station as it"
                ),
            )
        )

    return PreflightReport(checks=tuple(checks))


class SystemHostInspector:
    """The real `HostInspector`. The only object in DS02 that actually
    calls out to the host it runs on - and still only to read."""

    def python_version(self) -> tuple[int, int, int]:
        import sys

        return (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)

    def free_disk_gb(self, path: str) -> float | None:
        import os
        import shutil

        probe = path
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                return None
            probe = parent
        if not probe:
            return None
        usage = shutil.disk_usage(probe)
        return usage.free / (1024**3)

    def has_executable(self, name: str) -> bool:
        import shutil

        return shutil.which(name) is not None

    def path_is_writable(self, path: str) -> bool:
        import os

        probe = path
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                return False
            probe = parent
        return bool(probe) and os.access(probe, os.W_OK)

    def tcp_port_is_free(self, bind_address: str, port: int) -> bool:
        import socket

        family = socket.AF_INET6 if ":" in bind_address else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((bind_address, port))
            except OSError:
                return False
        return True

    def _passwd_entry(self, name: str) -> object | None:
        try:
            import pwd
        except ImportError:
            raise ConfigValidationError(
                "identity-user checks need a POSIX host - preflight for a remote station is a Linux concept"
            )
        try:
            return pwd.getpwnam(name)
        except KeyError:
            return None

    def user_exists(self, name: str) -> bool:
        return self._passwd_entry(name) is not None

    def user_is_system_account(self, name: str) -> bool:
        entry = self._passwd_entry(name)
        if entry is None:
            return False
        uid = getattr(entry, "pw_uid", None)
        shell = str(getattr(entry, "pw_shell", ""))
        if uid == 0:
            return False
        # Debian/RPi-OS convention: system accounts live below 1000, and a
        # real service account has a nologin/false shell.
        return isinstance(uid, int) and uid < 1000 and (
            shell.endswith("nologin") or shell.endswith("false")
        )
