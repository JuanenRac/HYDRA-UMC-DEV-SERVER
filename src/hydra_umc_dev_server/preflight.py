# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/preflight.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
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
    # True for a check that does not hold yet because the plan itself creates it (the
    # dedicated account, its workspace): it does not block the plan, and it is not hidden.
    will_create: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail, "will_create": self.will_create}


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def failures(self) -> tuple[PreflightCheck, ...]:
        return tuple(check for check in self.checks if not check.ok)

    def to_create(self) -> tuple[PreflightCheck, ...]:
        return tuple(check for check in self.checks if check.will_create)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
            "failures": [check.name for check in self.failures()],
            "will_create": [check.name for check in self.to_create()],
        }


def _identity_check(profile: RemoteStationProfile, inspector: HostInspector, exists: bool) -> PreflightCheck:
    """The account the station runs as. A missing account is not a failure (the plan creates it);
    an existing one must be a dedicated account. What "dedicated" means depends on how the editor
    gets in: a service account with no login shell for `code-server`, an account that can log in
    (a real shell and an authorized_keys file) for `ssh-remote`, because Remote-SSH has to log in."""
    user = profile.identity.user
    ssh = profile.remote_access.kind == "ssh-remote"
    if not exists:
        return PreflightCheck(
            name="identity-user",
            ok=True,
            will_create=True,
            detail=f"system account {user!r} does not exist yet; the plan creates it",
        )
    if not ssh:
        dedicated = inspector.user_is_system_account(user)
        return PreflightCheck(
            name="identity-user",
            ok=dedicated,
            detail=(
                f"{user!r} exists and is a dedicated system account"
                if dedicated
                else f"{user!r} exists but is a normal login user / uid 0 - refuse to run the station as it"
            ),
        )
    uid_of = getattr(inspector, "user_uid", None)
    shell_of = getattr(inspector, "user_shell", None)
    keys_of = getattr(inspector, "user_has_authorized_keys", None)
    if not (callable(uid_of) and callable(shell_of) and callable(keys_of)):
        return PreflightCheck(
            name="identity-user", ok=False,
            detail="this host inspector cannot tell the shell and the authorized keys of the account, which ssh-remote needs",
        )
    uid, shell = uid_of(user), str(shell_of(user) or "")
    problems: list[str] = []
    if uid in (None, 0):
        problems.append("it is uid 0 or has no uid")
    elif uid >= 1000:
        problems.append("it is a normal login user, not a dedicated account (uid >= 1000)")
    if not shell or shell.endswith(("nologin", "false")):
        problems.append(f"its shell {shell or 'none'!r} cannot log in, and Remote-SSH has to log in")
    if not keys_of(user):
        problems.append("it has no authorized_keys file, so nobody can log in as it")
    return PreflightCheck(
        name="identity-user",
        ok=not problems,
        detail=(
            f"{user!r} exists, is a dedicated account with a login shell and an authorized_keys file"
            if not problems
            else f"{user!r} exists but " + "; ".join(problems)
        ),
    )


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

    user = profile.identity.user
    user_exists = inspector.user_exists(user)
    if not user_exists:
        # nothing can be writable by an account that does not exist yet; the plan creates both
        checks.append(
            PreflightCheck(
                name="workspace-writable",
                ok=True,
                will_create=True,
                detail=f"{workspace} is not there yet; the plan creates it, owned by {user}",
            )
        )
    else:
        writable_by = getattr(inspector, "path_is_writable_by", None)
        writable = writable_by(workspace, user) if callable(writable_by) else inspector.path_is_writable(workspace)
        checks.append(
            PreflightCheck(
                name="workspace-writable",
                ok=bool(writable),
                detail=f"{workspace} must be writable by {user}",
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

    checks.append(_identity_check(profile, inspector, user_exists))

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
            ) from None
        try:
            return pwd.getpwnam(name)
        except KeyError:
            return None

    def user_exists(self, name: str) -> bool:
        return self._passwd_entry(name) is not None

    def user_uid(self, name: str) -> int | None:
        entry = self._passwd_entry(name)
        uid = getattr(entry, "pw_uid", None)
        return uid if isinstance(uid, int) else None

    def user_shell(self, name: str) -> str | None:
        entry = self._passwd_entry(name)
        return (str(getattr(entry, "pw_shell", "")) or None) if entry is not None else None

    def user_has_authorized_keys(self, name: str) -> bool:
        import os

        entry = self._passwd_entry(name)
        home = str(getattr(entry, "pw_dir", "")) if entry is not None else ""
        return bool(home) and os.path.isfile(os.path.join(home, ".ssh", "authorized_keys"))

    def path_is_writable_by(self, path: str, name: str) -> bool:
        """Whether the account `name` (not the user running this check) can write to `path`, or
        to the nearest existing parent when `path` is not there yet. Reads owner, group and mode."""
        import os
        import stat

        entry = self._passwd_entry(name)
        if entry is None:
            return False
        uid = getattr(entry, "pw_uid", -1)
        probe = path
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                return False
            probe = parent
        info = os.stat(probe)
        if uid == 0:
            return True
        if info.st_uid == uid:
            return bool(info.st_mode & stat.S_IWUSR)
        groups = {getattr(entry, "pw_gid", -1)}
        try:
            import grp

            groups |= {g.gr_gid for g in grp.getgrall() if name in g.gr_mem}
        except ImportError:
            pass
        if info.st_gid in groups:
            return bool(info.st_mode & stat.S_IWGRP)
        return bool(info.st_mode & stat.S_IWOTH)

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
