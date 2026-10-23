# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_provision.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The provisioning plan is a document, not an action - these tests
confirm it stays that way (argv captured as data, nothing executed) and
that it is refused over a host that is not ready."""
import unittest
from pathlib import Path

from hydra_umc_dev_server.config import ConfigValidationError, load_json_document
from hydra_umc_dev_server.preflight import PreflightCheck, PreflightReport, run_preflight
from hydra_umc_dev_server.provision import build_provision_plan
from hydra_umc_dev_server.remote_station import RemoteStationProfile

_EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "configs" / "remote-station.example.json"


def _profile(**overrides) -> RemoteStationProfile:
    document = {
        "identity": {"user": "hydra-dev-station", "home": "/srv/hydra-umc-dev/station", "workspace_subdir": "workspace"},
        "remote_access": {"kind": "code-server", "port": 8722, "bind_address": "127.0.0.1", "allow_public_bind": False},
        "required_tools": [
            {"name": "git", "min_version": "2.40", "required": True},
            {"name": "code-server", "min_version": "4.0", "required": False},
        ],
        "min_free_disk_gb": 10.0,
    }
    for key, value in overrides.items():
        document[key] = value
    return RemoteStationProfile.from_dict(document)


class FakeInspector:
    """A fully controllable `HostInspector`, mirroring the one in
    test_preflight - kept local so this module has no cross-test import."""

    def __init__(self):
        self.python = (3, 11, 4)
        self.free_gb = 50.0
        self.executables = {"git", "python3"}
        self.writable = True
        self.free_ports = {("127.0.0.1", 8722)}
        self.users = {"hydra-dev-station"}
        self.system_accounts = {"hydra-dev-station"}

    def python_version(self):
        return self.python

    def free_disk_gb(self, path):
        return self.free_gb

    def has_executable(self, name):
        return name in self.executables

    def path_is_writable(self, path):
        return self.writable

    def tcp_port_is_free(self, bind_address, port):
        return (bind_address, port) in self.free_ports

    def user_exists(self, name):
        return name in self.users

    def user_is_system_account(self, name):
        return name in self.system_accounts


class ProvisionPlanContentTests(unittest.TestCase):
    def setUp(self):
        self.profile = RemoteStationProfile.from_dict(load_json_document(_EXAMPLE_PATH))
        self.plan = build_provision_plan(self.profile)

    def test_the_plan_creates_the_user_before_the_workspace(self):
        kinds = [step.kind for step in self.plan.steps]
        self.assertLess(kinds.index("create-system-user"), kinds.index("create-workspace"))

    def test_the_user_step_carries_the_useradd_argv_as_data_not_a_call(self):
        step = next(s for s in self.plan.steps if s.kind == "create-system-user")
        self.assertEqual(step.command_preview[0], "useradd")
        self.assertIn("hydra-dev-station", step.command_preview)
        self.assertIn("--system", step.command_preview)

    def test_there_is_one_step_per_required_tool_entry_and_code_server_is_not_apt_installed(self):
        tool_steps = [s for s in self.plan.steps if s.kind in ("ensure-tool", "install-code-server")]
        self.assertEqual(len(tool_steps), len(self.profile.required_tools))
        for step in tool_steps:
            self.assertFalse(step.command_preview[:1] == ("apt-get",) and "code-server" in step.command_preview)
        installer = next(s for s in self.plan.steps if s.kind == "install-code-server")
        self.assertEqual(installer.command_preview[0], "curl")
        self.assertNotIn("sh", installer.command_preview)  # a download is never piped into a shell by the plan

    def test_the_account_is_created_with_a_home_that_holds_nothing_and_is_closed_to_others(self):
        user = next(s for s in self.plan.steps if s.kind == "create-system-user").command_preview
        self.assertIn("--no-create-home", user)
        self.assertNotIn("--create-home", user)
        self.assertEqual(user[user.index("--shell") + 1], "/usr/sbin/nologin")
        home = next(s for s in self.plan.steps if s.kind == "create-home").command_preview
        self.assertEqual(home[home.index("-m") + 1], "0700")
        self.assertEqual(home[-1], self.profile.identity.home)
        kinds = [s.kind for s in self.plan.steps]
        self.assertLess(kinds.index("create-system-user"), kinds.index("create-home"))
        self.assertLess(kinds.index("create-home"), kinds.index("create-workspace"))

    def test_the_unit_can_write_where_code_server_writes_and_never_starts_without_a_password(self):
        text = self.plan.systemd_unit_text
        home = self.profile.identity.home
        rw = next(l for l in text.splitlines() if l.startswith("ReadWritePaths="))
        for path in (self.profile.identity.workspace_path(), f"{home}/.config/code-server", f"{home}/.local/share/code-server"):
            self.assertIn(path, rw)
        self.assertIn(f"Environment=HOME={home}", text)
        self.assertIn(f"Environment=XDG_CONFIG_HOME={home}/.config", text)
        self.assertIn(f"EnvironmentFile={home}/code-server.env", text)
        self.assertIn(f"ConditionPathExists={home}/code-server.env", text)
        kinds = [s.kind for s in self.plan.steps]
        self.assertLess(kinds.index("create-editor-state"), kinds.index("write-systemd-unit"))
        self.assertIn("set-editor-password", kinds)
        state = next(s for s in self.plan.steps if s.kind == "create-editor-state").command_preview
        self.assertIn(f"{home}/.config/code-server", state)
        self.assertIn(f"{home}/.local/share/code-server", state)
        for step in self.plan.steps:
            self.assertNotIn("password", " ".join(step.command_preview).lower())  # no password is ever in an argv

    def test_the_code_server_plan_writes_a_systemd_unit_with_the_real_bind_and_identity(self):
        self.assertTrue(self.plan.systemd_unit_name.endswith(".service"))
        text = self.plan.systemd_unit_text
        self.assertIn("User=hydra-dev-station", text)
        self.assertIn("--bind-addr 127.0.0.1:8722", text)
        self.assertIn(self.profile.identity.workspace_path(), text)

    def test_the_unit_keeps_af_netlink_in_the_address_family_allowlist(self):
        # A too-tight RestrictAddressFamilies caused a real crash-loop
        # elsewhere in this ecosystem - the template must not repeat it.
        line = next(l for l in self.plan.systemd_unit_text.splitlines() if l.startswith("RestrictAddressFamilies="))
        self.assertIn("AF_NETLINK", line)

    def test_an_ssh_remote_plan_reuses_sshd_and_writes_no_unit(self):
        profile = _profile(
            remote_access={"kind": "ssh-remote", "port": 22022, "bind_address": "192.168.0.180", "allow_public_bind": False}
        )
        plan = build_provision_plan(profile)
        self.assertEqual(plan.systemd_unit_text, "")
        self.assertIn("reuse-sshd", [s.kind for s in plan.steps])

    def test_an_ssh_remote_account_gets_a_login_shell_and_a_closed_ssh_directory(self):
        profile = _profile(
            remote_access={"kind": "ssh-remote", "port": 22022, "bind_address": "192.168.0.180", "allow_public_bind": False}
        )
        plan = build_provision_plan(profile)
        user = next(s for s in plan.steps if s.kind == "create-system-user").command_preview
        self.assertEqual(user[user.index("--shell") + 1], "/bin/bash")
        ssh = next(s for s in plan.steps if s.kind == "prepare-ssh-access")
        self.assertEqual(ssh.command_preview[ssh.command_preview.index("-m") + 1], "0700")
        self.assertTrue(ssh.command_preview[-1].endswith("/.ssh"))
        self.assertNotIn("create-editor-state", [s.kind for s in plan.steps])

    def test_to_dict_is_json_shaped(self):
        payload = self.plan.to_dict()
        self.assertEqual(payload["identity_user"], "hydra-dev-station")
        self.assertIn("steps", payload)
        self.assertTrue(all({"kind", "description", "command_preview"} <= set(s) for s in payload["steps"]))


class ProvisionPlanPreflightGateTests(unittest.TestCase):
    def test_a_plan_built_over_a_passing_preflight_is_returned(self):
        report = run_preflight(_profile(), FakeInspector())
        self.assertTrue(report.ok)
        plan = build_provision_plan(_profile(), report)
        self.assertGreater(len(plan.steps), 0)

    def test_a_plan_for_a_host_without_the_account_is_built_and_says_what_it_creates(self):
        inspector = FakeInspector()
        inspector.users = set()
        report = run_preflight(_profile(), inspector)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual({c.name for c in report.to_create()}, {"identity-user", "workspace-writable"})
        plan = build_provision_plan(_profile(), report)
        self.assertIn("create-system-user", [s.kind for s in plan.steps])

    def test_a_plan_built_over_a_failed_preflight_is_refused_and_names_the_failure(self):
        inspector = FakeInspector()
        inspector.writable = False
        report = run_preflight(_profile(), inspector)
        self.assertFalse(report.ok)
        with self.assertRaises(ConfigValidationError) as ctx:
            build_provision_plan(_profile(), report)
        self.assertIn("workspace-writable", str(ctx.exception))

    def test_a_synthetic_failed_report_also_blocks_the_plan(self):
        report = PreflightReport(checks=(PreflightCheck(name="python-version", ok=False, detail="too old"),))
        with self.assertRaises(ConfigValidationError):
            build_provision_plan(_profile(), report)

    def test_no_preflight_argument_still_builds_a_plan(self):
        # Preflight is an optional gate here; DS04's real runner is where
        # it becomes mandatory before anything executes.
        plan = build_provision_plan(_profile())
        self.assertGreater(len(plan.steps), 0)


if __name__ == "__main__":
    unittest.main()
