# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/provision.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
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
from .remote_station import RemoteIdentity, RemoteStationProfile

# code-server is the concrete "remote VS Code access" target DS02's own
# roadmap line names; ssh-remote reuses the host's existing sshd and needs
# no unit of its own.
_CODE_SERVER_EXEC = "/usr/bin/code-server"
# code-server is not in the Debian / Raspberry Pi OS repositories; its own installer is the supported way.
_CODE_SERVER_INSTALLER_URL = "https://code-server.dev/install.sh"
# Where code-server keeps its configuration and its data. They are under the home of the account, outside
# the workspace, so the unit has to be allowed to write there (ProtectSystem=strict makes the rest read-only).
_CODE_SERVER_CONFIG_DIR = ".config/code-server"
_CODE_SERVER_DATA_DIR = ".local/share/code-server"
# The file with HASHED_PASSWORD=..., written by the operator and never by the plan.
_CODE_SERVER_ENV_FILE = "code-server.env"


def _home_path(identity: RemoteIdentity, relative: str) -> str:
    base = identity.home.rstrip("/")
    return f"{base}/{relative}"


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
    config_dir = _home_path(identity, _CODE_SERVER_CONFIG_DIR)
    data_dir = _home_path(identity, _CODE_SERVER_DATA_DIR)
    env_file = _home_path(identity, _CODE_SERVER_ENV_FILE)
    # RestrictAddressFamilies keeps AF_NETLINK in the allow-list on
    # purpose: an editor server that ever enumerates interfaces needs it,
    # and a too-tight family list has caused a real crash-loop elsewhere
    # in this ecosystem - a real deploy still confirms with a live check,
    # not systemd-analyze verify alone.
    #
    # The home of the account is outside the workspace and ProtectSystem=strict makes it read-only, so
    # the two directories code-server writes to are listed in ReadWritePaths (the plan creates them), and
    # HOME and the XDG directories point at them. The password is a hash in an environment file that only the
    # account can read; the unit does not start without it (ConditionPathExists), so a station is never
    # reachable with the password code-server would generate for itself.
    return "\n".join(
        (
            "[Unit]",
            f"Description=HYDRA-UMC-DEV-SERVER remote station ({access.kind}) for {identity.user}",
            "After=network-online.target",
            "Wants=network-online.target",
            f"ConditionPathExists={env_file}",
            "",
            "[Service]",
            "Type=exec",
            f"User={identity.user}",
            f"WorkingDirectory={identity.workspace_path()}",
            f"Environment=HOME={identity.home}",
            f"Environment=XDG_CONFIG_HOME={identity.home.rstrip('/')}/.config",
            f"Environment=XDG_DATA_HOME={identity.home.rstrip('/')}/.local/share",
            f"EnvironmentFile={env_file}",
            f"ExecStart={_CODE_SERVER_EXEC} --bind-addr {access.bind_address}:{access.port} --auth password --disable-telemetry",
            "Restart=on-failure",
            "RestartSec=3",
            "NoNewPrivileges=yes",
            "ProtectSystem=strict",
            "ProtectHome=tmpfs",
            f"ReadWritePaths={identity.workspace_path()} {config_dir} {data_dir}",
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
    only ever handed back for a host that is actually ready. What the
    plan creates itself (the account, its workspace) is not a failure of
    the preflight: it is reported as "will create" and the plan makes it."""
    if preflight is not None and not preflight.ok:
        failed = ", ".join(check.name for check in preflight.failures())
        raise ConfigValidationError(
            f"refusing to build a provision plan over a failed preflight ({failed})"
        )

    identity = profile.identity
    access = profile.remote_access
    ssh = access.kind == "ssh-remote"
    # The account has a home but no "real" one: it is created empty (no skeleton files, no dotfiles, no
    # keys) and only the account can enter it, so there is nothing of a person in it for a task to read.
    # A code-server account has no login shell; an ssh-remote account needs one, because Remote-SSH logs in.
    steps: list[ProvisionStep] = [
        ProvisionStep(
            kind="create-system-user",
            description=(
                f"create dedicated system account {identity.user!r} with home {identity.home}, "
                + ("a login shell (Remote-SSH logs in)" if ssh else "no login shell")
                + " and no files copied into the home"
            ),
            command_preview=(
                "useradd", "--system", "--no-create-home",
                "--home-dir", identity.home,
                "--shell", "/bin/bash" if ssh else "/usr/sbin/nologin",
                identity.user,
            ),
        ),
        ProvisionStep(
            kind="create-home",
            description=f"create {identity.home} empty, owned by {identity.user} and closed to everybody else",
            command_preview=("install", "-d", "-o", identity.user, "-g", identity.user, "-m", "0700", identity.home),
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
        if tool.name == "code-server":
            steps.append(
                ProvisionStep(
                    kind="install-code-server",
                    description=(
                        f"code-server >= {tool.min_version} is not in the Debian / Raspberry Pi OS repositories: download its "
                        "official installer, read it, then run it (the plan does not pipe a download into a shell)"
                        + ("" if tool.required else " (optional)")
                    ),
                    command_preview=("curl", "-fsSL", "-o", "code-server-install.sh", _CODE_SERVER_INSTALLER_URL),
                )
            )
            continue
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
                kind="create-editor-state",
                description=(
                    f"create the directories code-server writes to ({_CODE_SERVER_CONFIG_DIR} and {_CODE_SERVER_DATA_DIR} "
                    f"under {identity.home}), owned by {identity.user}; the unit lists them as writable"
                ),
                command_preview=(
                    "install", "-d", "-o", identity.user, "-g", identity.user, "-m", "0700",
                    _home_path(identity, ".config"), _home_path(identity, ".local"), _home_path(identity, ".local/share"),
                    _home_path(identity, _CODE_SERVER_CONFIG_DIR), _home_path(identity, _CODE_SERVER_DATA_DIR),
                ),
            )
        )
        steps.append(
            ProvisionStep(
                kind="set-editor-password",
                description=(
                    f"the operator writes {_home_path(identity, _CODE_SERVER_ENV_FILE)} (mode 0600, owned by {identity.user}) with the line "
                    "HASHED_PASSWORD='<argon2 hash>' (an argon2 hash, as the code-server documentation describes); the plan "
                    "never makes a password, and the unit does not start until the file exists"
                ),
            )
        )
        steps.append(
            ProvisionStep(
                kind="write-systemd-unit",
                description=f"write /etc/systemd/system/{unit_name} (text below) and 'systemctl enable --now' it",
            )
        )
    else:  # ssh-remote
        steps.append(
            ProvisionStep(
                kind="prepare-ssh-access",
                description=(
                    f"create ~/.ssh of {identity.user} (mode 0700) for the operator to put the public key of the developer in "
                    "authorized_keys (mode 0600); the plan never installs a key"
                ),
                command_preview=("install", "-d", "-o", identity.user, "-g", identity.user, "-m", "0700", _home_path(identity, ".ssh")),
            )
        )
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
