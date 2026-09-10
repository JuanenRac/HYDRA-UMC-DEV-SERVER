# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/provision.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS02 dry-run provisioning plan - what a real installer *would* do to
turn a fresh host into the `RemoteStationProfile`'s remote station,
rendered as an inspectable object and never executed here.

`build_provision_plan()` returns a `ProvisionPlan`: an ordered list of
`ProvisionStep`s (each carrying the exact argv that would run, as data)
plus the full systemd unit text that would be written. Nothing in this
module shells out, writes a file, or contacts a host - DS04's real runner
is where execution lives, behind its own policy gate. A plan is refused
outright when it is built over a failed preflight, so "the host isn't
ready" can never be one step of a plan that then half-runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import ConfigValidationError
from .preflight import PreflightReport
from .remote_station import RemoteStationProfile

# code-server is the concrete "remote VS Code access" target DS02's own
# roadmap line names; ssh-remote reuses the host's existing sshd and needs
# no unit of its own.
_CODE_SERVER_EXEC = "/usr/bin/code-server"


@dataclass(frozen=True)
class ProvisionStep:
    kind: str
    description: str
    # The argv a real installer would run for this step - captured as data
    # so a human can read the whole plan before anything happens. Empty for
    # a step that only writes a file (see `ProvisionPlan.systemd_unit_text`).
    command_preview: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "description": self.description,
            "command_preview": list(self.command_preview),
        }


@dataclass(frozen=True)
class ProvisionPlan:
    profile: RemoteStationProfile
    steps: tuple[ProvisionStep, ...]
    systemd_unit_name: str
    systemd_unit_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_user": self.profile.identity.user,
            "remote_access": self.profile.remote_access.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "systemd_unit_name": self.systemd_unit_name,
            "systemd_unit_text": self.systemd_unit_text,
        }


def _systemd_unit_text(profile: RemoteStationProfile) -> str:
    identity = profile.identity
    access = profile.remote_access
    # RestrictAddressFamilies keeps AF_NETLINK in the allow-list on
    # purpose: an editor server that ever enumerates interfaces needs it,
    # and a too-tight family list has caused a real crash-loop elsewhere
    # in this ecosystem - a real deploy still confirms with a live check,
    # not systemd-analyze verify alone.
    return "\n".join(
        (
            "[Unit]",
            f"Description=HYDRA-UMC-DEV-SERVER remote station ({access.kind}) for {identity.user}",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Service]",
            "Type=exec",
            f"User={identity.user}",
            f"WorkingDirectory={identity.workspace_path()}",
            f"ExecStart={_CODE_SERVER_EXEC} --bind-addr {access.bind_address}:{access.port} --auth password",
            "Restart=on-failure",
            "RestartSec=3",
            "NoNewPrivileges=yes",
            "ProtectSystem=strict",
            "ProtectHome=tmpfs",
            f"ReadWritePaths={identity.workspace_path()}",
            "PrivateTmp=yes",
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        )
    )


def build_provision_plan(
    profile: RemoteStationProfile,
    preflight: PreflightReport | None = None,
) -> ProvisionPlan:
    """Build the dry-run plan. If `preflight` is given and it failed,
    raise `ConfigValidationError` rather than return a plan - a plan is
    only ever handed back for a host that is actually ready."""
    if preflight is not None and not preflight.ok:
        failed = ", ".join(check.name for check in preflight.failures())
        raise ConfigValidationError(
            f"refusing to build a provision plan over a failed preflight ({failed})"
        )

    identity = profile.identity
    access = profile.remote_access
    steps: list[ProvisionStep] = [
        ProvisionStep(
            kind="create-system-user",
            description=f"create dedicated system account {identity.user!r} with home {identity.home}",
            command_preview=(
                "useradd", "--system", "--create-home",
                "--home-dir", identity.home,
                "--shell", "/usr/sbin/nologin",
                identity.user,
            ),
        ),
        ProvisionStep(
            kind="create-workspace",
            description=f"create {identity.workspace_path()} owned by {identity.user}",
            command_preview=(
                "install", "-d", "-o", identity.user, "-g", identity.user,
                "-m", "0750", identity.workspace_path(),
            ),
        ),
    ]

    for tool in profile.required_tools:
        steps.append(
            ProvisionStep(
                kind="ensure-tool",
                description=(
                    f"ensure {tool.name} >= {tool.min_version} is installed"
                    + ("" if tool.required else " (optional)")
                ),
                command_preview=("apt-get", "install", "--yes", tool.name),
            )
        )

    unit_name = f"hydra-umc-dev-station-{identity.user}.service"
    if access.kind == "code-server":
        steps.append(
            ProvisionStep(
                kind="write-systemd-unit",
                description=f"write /etc/systemd/system/{unit_name} (text below) and 'systemctl enable --now' it",
            )
        )
    else:  # ssh-remote
        steps.append(
            ProvisionStep(
                kind="reuse-sshd",
                description=(
                    f"no new service: VS Code Remote-SSH connects over the host's existing sshd as {identity.user}; "
                    f"confirm sshd listens on {access.bind_address} and {identity.user} may log in"
                ),
                command_preview=("sshd", "-T"),
            )
        )

    return ProvisionPlan(
        profile=profile,
        steps=tuple(steps),
        systemd_unit_name=unit_name,
        systemd_unit_text=_systemd_unit_text(profile) if access.kind == "code-server" else "",
    )
