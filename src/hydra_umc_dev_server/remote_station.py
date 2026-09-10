# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/remote_station.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS02 - the reproducible-remote-station profile: who the remote coding
identity is, how remote editing reaches it, and which tools that identity
must have.

Like the DS01 documents in `config.py`, this is a declarative,
independently loadable/validatable document - nothing here provisions a
host, installs a package or opens a port. That is what DS02's preflight
(`preflight.py`) reads it to *check*, and what a later, real installer
would read it to *do*. Its whole job is to make "a remote station" a
thing you can diff, review and reproduce byte-for-byte, not a hand-run
sequence of commands.

Two safety-relevant rules are enforced at load time, by test, not just by
documentation:

  * the remote-editing endpoint binds a loopback or RFC 1918 private
    address by default; a routable/public bind address is refused unless
    the document sets the literal boolean `allow_public_bind: true` - the
    same "a missing/misspelled field never silently grants it" shape
    `config.py`'s `TaskPolicy.allow_deploy` already uses.
  * the identity is a real dedicated system account (a name, a home under
    an absolute path), never `root` and never a login user's own name.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any

from .config import ConfigValidationError, ToolchainPolicy, _require_bool, _require_str

_VALID_REMOTE_ACCESS_KINDS = ("code-server", "ssh-remote")
# A remote-editing service on a dev host has no business on a well-known
# service port - require the unprivileged range so a preflight port check
# is meaningful and a typo can't collide with sshd/http/etc.
_MIN_REMOTE_PORT = 1024
_MAX_REMOTE_PORT = 65535


def _require_positive_number(data: dict[str, Any], field_name: str, errors: list[str], *, default: float) -> float:
    if field_name not in data:
        return default
    value = data[field_name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        errors.append(f"{field_name!r} must be a positive number, not {value!r}")
        return default
    return float(value)


@dataclass(frozen=True)
class RemoteIdentity:
    """The dedicated, non-login system account remote coding work runs as."""

    user: str
    home: str
    workspace_subdir: str = "workspace"

    _FORBIDDEN_USERS = ("root", "admin", "hydra-umc")  # the last is the CM5 login user

    def workspace_path(self) -> str:
        base = self.home if self.home.endswith("/") else self.home + "/"
        return base + self.workspace_subdir

    def to_dict(self) -> dict[str, Any]:
        return {"user": self.user, "home": self.home, "workspace_subdir": self.workspace_subdir}

    @staticmethod
    def from_dict(data: object) -> "RemoteIdentity":
        if not isinstance(data, dict):
            raise ConfigValidationError("remote identity must be a JSON object")
        errors: list[str] = []
        user = _require_str(data, "user", errors)
        home = _require_str(data, "home", errors)
        workspace_subdir = data.get("workspace_subdir", "workspace")
        if not isinstance(workspace_subdir, str) or not workspace_subdir or workspace_subdir.startswith("/") or ".." in workspace_subdir:
            errors.append("'workspace_subdir' must be a non-empty relative path with no '..' segments")
            workspace_subdir = "workspace"
        if user and user in RemoteIdentity._FORBIDDEN_USERS:
            errors.append(f"'user' must be a dedicated system account, not {user!r}")
        if home and not home.startswith("/"):
            errors.append(f"'home' must be an absolute path, got {home!r}")
        if errors:
            raise ConfigValidationError("; ".join(errors))
        return RemoteIdentity(user=user, home=home, workspace_subdir=workspace_subdir)


@dataclass(frozen=True)
class RemoteAccess:
    """How a developer's editor reaches this station."""

    kind: str
    port: int
    bind_address: str
    allow_public_bind: bool = False

    def is_loopback_or_private(self) -> bool:
        try:
            addr = ipaddress.ip_address(self.bind_address)
        except ValueError:
            return False
        return addr.is_loopback or addr.is_private

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "port": self.port,
            "bind_address": self.bind_address,
            "allow_public_bind": self.allow_public_bind,
        }

    @staticmethod
    def from_dict(data: object) -> "RemoteAccess":
        if not isinstance(data, dict):
            raise ConfigValidationError("remote access must be a JSON object")
        errors: list[str] = []
        kind = _require_str(data, "kind", errors)
        bind_address = _require_str(data, "bind_address", errors)
        allow_public_bind = _require_bool(data, "allow_public_bind", errors, default=False)

        port = data.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not (_MIN_REMOTE_PORT <= port <= _MAX_REMOTE_PORT):
            errors.append(f"'port' must be an integer in [{_MIN_REMOTE_PORT}, {_MAX_REMOTE_PORT}], not {port!r}")
            port = _MIN_REMOTE_PORT

        if kind and kind not in _VALID_REMOTE_ACCESS_KINDS:
            errors.append(f"'kind' must be one of {_VALID_REMOTE_ACCESS_KINDS}, not {kind!r}")

        if bind_address:
            try:
                addr = ipaddress.ip_address(bind_address)
                if not (addr.is_loopback or addr.is_private) and not allow_public_bind:
                    errors.append(
                        f"'bind_address' {bind_address!r} is routable/public - refusing without "
                        "'allow_public_bind': true (a remote-editing endpoint on a dev host defaults to loopback/private)"
                    )
            except ValueError:
                errors.append(f"'bind_address' must be a valid IP address, got {bind_address!r}")

        if errors:
            raise ConfigValidationError("; ".join(errors))
        return RemoteAccess(kind=kind, port=port, bind_address=bind_address, allow_public_bind=allow_public_bind)


@dataclass(frozen=True)
class RemoteStationProfile:
    """The whole DS02 station document: an identity, a remote-access
    endpoint, the toolchains that identity must have, and a real
    minimum-free-disk floor a preflight check enforces."""

    identity: RemoteIdentity
    remote_access: RemoteAccess
    required_tools: tuple[ToolchainPolicy, ...]
    min_free_disk_gb: float = 10.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "remote_access": self.remote_access.to_dict(),
            "required_tools": [t.to_dict() for t in self.required_tools],
            "min_free_disk_gb": self.min_free_disk_gb,
        }

    @staticmethod
    def from_dict(data: object) -> "RemoteStationProfile":
        if not isinstance(data, dict):
            raise ConfigValidationError("remote station profile must be a JSON object")
        errors: list[str] = []

        identity: RemoteIdentity | None = None
        try:
            identity = RemoteIdentity.from_dict(data.get("identity"))
        except ConfigValidationError as exc:
            errors.append(f"identity: {exc}")

        remote_access: RemoteAccess | None = None
        try:
            remote_access = RemoteAccess.from_dict(data.get("remote_access"))
        except ConfigValidationError as exc:
            errors.append(f"remote_access: {exc}")

        tools_raw = data.get("required_tools", [])
        required_tools: list[ToolchainPolicy] = []
        if not isinstance(tools_raw, list) or not tools_raw:
            errors.append("'required_tools' must be a non-empty list of toolchain entries")
        else:
            for index, entry in enumerate(tools_raw):
                try:
                    required_tools.append(ToolchainPolicy.from_dict(entry))
                except ConfigValidationError as exc:
                    errors.append(f"required_tools[{index}]: {exc}")

        min_free_disk_gb = _require_positive_number(data, "min_free_disk_gb", errors, default=10.0)

        if errors:
            raise ConfigValidationError("; ".join(errors))
        assert identity is not None and remote_access is not None  # errors would have been raised
        return RemoteStationProfile(
            identity=identity,
            remote_access=remote_access,
            required_tools=tuple(required_tools),
            min_free_disk_gb=min_free_disk_gb,
        )
