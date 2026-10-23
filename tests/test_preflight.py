# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_preflight.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Every test here drives preflight through a fake inspector - nothing
touches a real host, the same rule config.py states for DS01."""
import unittest

from hydra_umc_dev_server.preflight import HostInspector, PreflightReport, run_preflight
from hydra_umc_dev_server.remote_station import RemoteStationProfile


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
    """A fully controllable `HostInspector` - each answer is a plain field
    a test sets to whatever scenario it needs."""

    def __init__(self):
        self.python = (3, 11, 4)
        self.free_gb: float | None = 50.0
        self.executables = {"git", "python3"}
        self.writable = True
        self.free_ports = {("127.0.0.1", 8722)}
        self.users = {"hydra-dev-station"}
        self.system_accounts = {"hydra-dev-station"}

    def python_version(self):
        return self.python

    def free_disk_gb(self, path: str):
        return self.free_gb

    def has_executable(self, name: str) -> bool:
        return name in self.executables

    def path_is_writable(self, path: str) -> bool:
        return self.writable

    def tcp_port_is_free(self, bind_address: str, port: int) -> bool:
        return (bind_address, port) in self.free_ports

    def user_exists(self, name: str) -> bool:
        return name in self.users

    def user_is_system_account(self, name: str) -> bool:
        return name in self.system_accounts


class PreflightHappyPathTests(unittest.TestCase):
    def test_the_fake_inspector_default_scenario_passes_every_check(self):
        report = run_preflight(_profile(), FakeInspector())
        self.assertIsInstance(report, PreflightReport)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.failures(), ())

    def test_it_satisfies_the_hostinspector_protocol(self):
        self.assertIsInstance(FakeInspector(), HostInspector)


class PreflightFailureTests(unittest.TestCase):
    def test_an_old_python_fails_the_version_check_only(self):
        inspector = FakeInspector()
        inspector.python = (3, 9, 18)
        report = run_preflight(_profile(), inspector)
        self.assertFalse(report.ok)
        self.assertEqual([c.name for c in report.failures()], ["python-version"])

    def test_too_little_free_disk_fails_the_disk_check(self):
        inspector = FakeInspector()
        inspector.free_gb = 2.0
        report = run_preflight(_profile(), inspector)
        self.assertIn("free-disk", [c.name for c in report.failures()])

    def test_a_missing_workspace_parent_is_a_real_reported_reason_not_a_crash(self):
        inspector = FakeInspector()
        inspector.free_gb = None
        report = run_preflight(_profile(), inspector)
        disk = next(c for c in report.checks if c.name == "free-disk")
        self.assertFalse(disk.ok)
        self.assertIn("no existing parent", disk.detail)

    def test_a_non_writable_workspace_fails(self):
        inspector = FakeInspector()
        inspector.writable = False
        report = run_preflight(_profile(), inspector)
        self.assertIn("workspace-writable", [c.name for c in report.failures()])

    def test_a_missing_required_tool_fails_but_a_missing_optional_tool_does_not(self):
        inspector = FakeInspector()
        inspector.executables = {"python3"}  # git (required) gone, code-server (optional) also gone
        report = run_preflight(_profile(), inspector)
        failed = [c.name for c in report.failures()]
        self.assertIn("tool:git", failed)
        self.assertNotIn("tool:code-server", failed)

    def test_a_busy_remote_port_fails(self):
        inspector = FakeInspector()
        inspector.free_ports = set()
        report = run_preflight(_profile(), inspector)
        self.assertIn("remote-port-free", [c.name for c in report.failures()])

    def test_a_missing_identity_user_does_not_block_the_plan_that_creates_it(self):
        inspector = FakeInspector()
        inspector.users = set()
        inspector.writable = False  # nothing can be writable by an account that is not there yet
        report = run_preflight(_profile(), inspector)
        identity = next(c for c in report.checks if c.name == "identity-user")
        workspace = next(c for c in report.checks if c.name == "workspace-writable")
        self.assertTrue(identity.ok and identity.will_create)
        self.assertIn("does not exist yet", identity.detail)
        self.assertTrue(workspace.ok and workspace.will_create)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.to_dict()["will_create"], ["workspace-writable", "identity-user"])

    def test_an_existing_account_is_asked_whether_it_can_write_not_the_user_running_the_check(self):
        inspector = FakeInspector()
        inspector.writable = True  # the current user could write...
        asked = []

        def writable_by(path, name):
            asked.append((path, name))
            return False  # ...but the account of the station cannot

        inspector.path_is_writable_by = writable_by
        report = run_preflight(_profile(), inspector)
        self.assertIn("workspace-writable", [c.name for c in report.failures()])
        self.assertEqual(asked, [("/srv/hydra-umc-dev/station/workspace", "hydra-dev-station")])

    def test_an_identity_user_that_is_a_normal_login_user_is_refused(self):
        inspector = FakeInspector()
        inspector.system_accounts = set()  # exists, but not a system account
        report = run_preflight(_profile(), inspector)
        identity = next(c for c in report.checks if c.name == "identity-user")
        self.assertFalse(identity.ok)

    def test_a_public_bind_with_the_opt_in_passes_the_privacy_check(self):
        profile = _profile(
            remote_access={"kind": "code-server", "port": 8722, "bind_address": "8.8.8.8", "allow_public_bind": True}
        )
        inspector = FakeInspector()
        inspector.free_ports = {("8.8.8.8", 8722)}
        report = run_preflight(profile, inspector)
        privacy = next(c for c in report.checks if c.name == "bind-address-is-private")
        self.assertTrue(privacy.ok)
        self.assertIn("allowed by allow_public_bind", privacy.detail)


class _SshInspector(FakeInspector):
    def __init__(self):
        super().__init__()
        self.uid, self.shell, self.keys = 998, "/bin/bash", True

    def user_uid(self, name):
        return self.uid

    def user_shell(self, name):
        return self.shell

    def user_has_authorized_keys(self, name):
        return self.keys


def _ssh_profile():
    return _profile(remote_access={"kind": "ssh-remote", "port": 22022, "bind_address": "127.0.0.1", "allow_public_bind": False})


class PreflightSshRemoteTests(unittest.TestCase):
    """Remote-SSH logs in, so the account needs a real shell and an authorized_keys file, not nologin."""

    def identity(self, inspector):
        inspector.free_ports = {("127.0.0.1", 22022)}
        return next(c for c in run_preflight(_ssh_profile(), inspector).checks if c.name == "identity-user")

    def test_an_account_with_a_shell_and_keys_passes(self):
        check = self.identity(_SshInspector())
        self.assertTrue(check.ok, check.detail)

    def test_a_nologin_account_is_refused_for_ssh_remote_but_passes_for_code_server(self):
        inspector = _SshInspector()
        inspector.shell = "/usr/sbin/nologin"
        check = self.identity(inspector)
        self.assertFalse(check.ok)
        self.assertIn("cannot log in", check.detail)
        self.assertTrue(next(c for c in run_preflight(_profile(), FakeInspector()).checks if c.name == "identity-user").ok)

    def test_an_account_without_authorized_keys_is_refused(self):
        inspector = _SshInspector()
        inspector.keys = False
        check = self.identity(inspector)
        self.assertFalse(check.ok)
        self.assertIn("authorized_keys", check.detail)

    def test_root_and_a_normal_login_user_are_still_refused(self):
        for uid in (0, 1000):
            inspector = _SshInspector()
            inspector.uid = uid
            with self.subTest(uid=uid):
                self.assertFalse(self.identity(inspector).ok)

    def test_an_inspector_that_cannot_tell_the_shell_fails_closed(self):
        self.assertFalse(self.identity(FakeInspector()).ok)

    def test_a_missing_account_is_created_by_the_plan(self):
        inspector = _SshInspector()
        inspector.users = set()
        check = self.identity(inspector)
        self.assertTrue(check.ok and check.will_create)


class PreflightReportShapeTests(unittest.TestCase):
    def test_to_dict_exposes_ok_checks_and_failure_names(self):
        inspector = FakeInspector()
        inspector.writable = False
        payload = run_preflight(_profile(), inspector).to_dict()
        self.assertEqual(payload["ok"], False)
        self.assertIn("workspace-writable", payload["failures"])
        self.assertTrue(all({"name", "ok", "detail"} <= set(c) for c in payload["checks"]))


if __name__ == "__main__":
    unittest.main()
