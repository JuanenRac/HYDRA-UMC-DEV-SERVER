# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_remote_station.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import unittest
from pathlib import Path

from hydra_umc_dev_server.config import ConfigValidationError, load_json_document
from hydra_umc_dev_server.remote_station import (
    RemoteAccess,
    RemoteIdentity,
    RemoteStationProfile,
)

_EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "configs" / "remote-station.example.json"


def _valid_document() -> dict:
    return {
        "identity": {"user": "hydra-dev-station", "home": "/srv/hydra-umc-dev/station", "workspace_subdir": "workspace"},
        "remote_access": {"kind": "code-server", "port": 8722, "bind_address": "127.0.0.1", "allow_public_bind": False},
        "required_tools": [{"name": "git", "min_version": "2.40", "required": True}],
        "min_free_disk_gb": 10.0,
    }


class RemoteIdentityTests(unittest.TestCase):
    def test_a_valid_identity_round_trips(self):
        data = {"user": "hydra-dev-station", "home": "/srv/x/station", "workspace_subdir": "workspace"}
        self.assertEqual(RemoteIdentity.from_dict(data).to_dict(), data)

    def test_the_workspace_path_is_home_joined_with_the_subdir(self):
        identity = RemoteIdentity.from_dict({"user": "u", "home": "/srv/x", "workspace_subdir": "work"})
        self.assertEqual(identity.workspace_path(), "/srv/x/work")

    def test_root_is_refused_as_the_station_identity(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            RemoteIdentity.from_dict({"user": "root", "home": "/root"})
        self.assertIn("dedicated system account", str(ctx.exception))

    def test_the_cm5_login_user_is_refused_as_the_station_identity(self):
        with self.assertRaises(ConfigValidationError):
            RemoteIdentity.from_dict({"user": "hydra-umc", "home": "/home/hydra-umc"})

    def test_a_relative_home_is_rejected(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            RemoteIdentity.from_dict({"user": "u", "home": "srv/x"})
        self.assertIn("absolute path", str(ctx.exception))

    def test_a_workspace_subdir_escaping_with_dotdot_is_rejected(self):
        with self.assertRaises(ConfigValidationError):
            RemoteIdentity.from_dict({"user": "u", "home": "/srv/x", "workspace_subdir": "../../etc"})

    def test_an_absolute_workspace_subdir_is_rejected(self):
        with self.assertRaises(ConfigValidationError):
            RemoteIdentity.from_dict({"user": "u", "home": "/srv/x", "workspace_subdir": "/etc"})


class RemoteAccessTests(unittest.TestCase):
    def test_a_valid_loopback_access_round_trips(self):
        data = {"kind": "code-server", "port": 8722, "bind_address": "127.0.0.1", "allow_public_bind": False}
        self.assertEqual(RemoteAccess.from_dict(data).to_dict(), data)

    def test_a_private_rfc1918_bind_address_is_accepted(self):
        access = RemoteAccess.from_dict({"kind": "ssh-remote", "port": 22022, "bind_address": "192.168.0.180"})
        self.assertTrue(access.is_loopback_or_private())

    def test_a_public_bind_address_is_refused_without_the_explicit_opt_in(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            RemoteAccess.from_dict({"kind": "code-server", "port": 8722, "bind_address": "8.8.8.8"})
        self.assertIn("allow_public_bind", str(ctx.exception))

    def test_a_public_bind_address_is_allowed_only_with_the_literal_true(self):
        access = RemoteAccess.from_dict(
            {"kind": "code-server", "port": 8722, "bind_address": "8.8.8.8", "allow_public_bind": True}
        )
        self.assertFalse(access.is_loopback_or_private())
        self.assertTrue(access.allow_public_bind)

    def test_a_non_boolean_allow_public_bind_never_grants_it(self):
        with self.assertRaises(ConfigValidationError):
            RemoteAccess.from_dict(
                {"kind": "code-server", "port": 8722, "bind_address": "8.8.8.8", "allow_public_bind": "true"}
            )

    def test_an_invalid_ip_is_rejected(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            RemoteAccess.from_dict({"kind": "code-server", "port": 8722, "bind_address": "not-an-ip"})
        self.assertIn("valid IP address", str(ctx.exception))

    def test_a_privileged_port_is_rejected(self):
        with self.assertRaises(ConfigValidationError):
            RemoteAccess.from_dict({"kind": "code-server", "port": 80, "bind_address": "127.0.0.1"})

    def test_a_boolean_is_not_accepted_as_a_port(self):
        with self.assertRaises(ConfigValidationError):
            RemoteAccess.from_dict({"kind": "code-server", "port": True, "bind_address": "127.0.0.1"})

    def test_an_unknown_kind_is_rejected(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            RemoteAccess.from_dict({"kind": "vnc", "port": 8722, "bind_address": "127.0.0.1"})
        self.assertIn("kind", str(ctx.exception))


class RemoteStationProfileTests(unittest.TestCase):
    def test_a_valid_document_round_trips(self):
        data = _valid_document()
        self.assertEqual(RemoteStationProfile.from_dict(data).to_dict(), data)

    def test_required_tools_must_be_a_non_empty_list(self):
        data = _valid_document()
        data["required_tools"] = []
        with self.assertRaises(ConfigValidationError) as ctx:
            RemoteStationProfile.from_dict(data)
        self.assertIn("required_tools", str(ctx.exception))

    def test_a_broken_tool_entry_is_reported_with_its_index(self):
        data = _valid_document()
        data["required_tools"] = [
            {"name": "git", "min_version": "2.40", "required": True},
            {"name": "", "min_version": "3.11", "required": True},
        ]
        with self.assertRaises(ConfigValidationError) as ctx:
            RemoteStationProfile.from_dict(data)
        self.assertIn("required_tools[1]", str(ctx.exception))

    def test_a_negative_min_free_disk_is_rejected(self):
        data = _valid_document()
        data["min_free_disk_gb"] = -5
        with self.assertRaises(ConfigValidationError):
            RemoteStationProfile.from_dict(data)

    def test_min_free_disk_defaults_to_ten_when_absent(self):
        data = _valid_document()
        del data["min_free_disk_gb"]
        self.assertEqual(RemoteStationProfile.from_dict(data).min_free_disk_gb, 10.0)

    def test_errors_from_several_sections_accumulate_into_one_message(self):
        data = {
            "identity": {"user": "root", "home": "relative/path"},
            "remote_access": {"kind": "vnc", "port": 80, "bind_address": "8.8.8.8"},
            "required_tools": [],
        }
        with self.assertRaises(ConfigValidationError) as ctx:
            RemoteStationProfile.from_dict(data)
        message = str(ctx.exception)
        self.assertIn("identity:", message)
        self.assertIn("remote_access:", message)
        self.assertIn("required_tools", message)

    def test_the_real_shipped_example_config_is_valid(self):
        data = load_json_document(_EXAMPLE_PATH)
        profile = RemoteStationProfile.from_dict(data)
        self.assertFalse(profile.remote_access.allow_public_bind, "the shipped example must bind privately")
        self.assertTrue(profile.remote_access.is_loopback_or_private())


if __name__ == "__main__":
    unittest.main()
