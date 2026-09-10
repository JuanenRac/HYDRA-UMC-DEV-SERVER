# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_provision.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
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

    def test_there_is_one_ensure_tool_step_per_required_tool_entry(self):
        tool_steps = [s for s in self.plan.steps if s.kind == "ensure-tool"]
        self.assertEqual(len(tool_steps), len(self.profile.required_tools))

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
