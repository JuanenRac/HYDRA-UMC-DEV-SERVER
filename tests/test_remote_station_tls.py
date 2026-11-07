# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_remote_station_tls.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""TLS of the code-server station: off unless the profile names a certificate and a key, both or neither, and the unit carries exactly those two files."""
import unittest

from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.provision import _systemd_unit_text
from hydra_umc_dev_server.remote_station import RemoteAccess, RemoteStationProfile

BASE = {"kind": "code-server", "port": 8722, "bind_address": "127.0.0.1"}
CERT = "/etc/hydra-umc/tls/station.crt"
KEY = "/etc/hydra-umc/tls/station.key"


def profile(access: dict) -> RemoteStationProfile:
    return RemoteStationProfile.from_dict(
        {
            "identity": {"user": "hydra-dev-station", "home": "/srv/hydra-umc-dev/station", "workspace_subdir": "workspace"},
            "remote_access": access,
            "required_tools": [{"name": "git", "min_version": "2.40", "required": True}],
            "min_free_disk_gb": 10.0,
        }
    )


class TlsTests(unittest.TestCase):
    def test_without_files_nothing_changes_the_document_or_the_unit(self) -> None:
        access = RemoteAccess.from_dict(BASE)
        self.assertFalse(access.uses_tls())
        self.assertNotIn("tls_cert_file", access.to_dict())
        unit = _systemd_unit_text(profile(BASE))
        self.assertNotIn("--cert", unit)
        self.assertIn("--bind-addr 127.0.0.1:8722 --auth password --disable-telemetry\n", unit)

    def test_with_both_files_the_unit_carries_them_and_the_document_round_trips(self) -> None:
        data = {**BASE, "allow_public_bind": False, "tls_cert_file": CERT, "tls_key_file": KEY}
        access = RemoteAccess.from_dict(data)
        self.assertTrue(access.uses_tls())
        self.assertEqual(access.to_dict(), data)
        unit = _systemd_unit_text(profile(data))
        self.assertIn(f"--auth password --disable-telemetry --cert {CERT} --cert-key {KEY}\n", unit)
        self.assertEqual(unit.count("--cert "), 1)

    def test_one_file_without_the_other_is_refused(self) -> None:
        for lone in ({"tls_cert_file": CERT}, {"tls_key_file": KEY}):
            with self.assertRaisesRegex(ConfigValidationError, "go together"):
                RemoteAccess.from_dict({**BASE, **lone})

    def test_paths_that_are_not_plain_absolute_paths_are_refused(self) -> None:
        for bad in ("relative/station.crt", "/etc/tls/a b.crt", "/etc/tls/a;b.crt", "/etc/tls/$(id).crt", "/etc/tls/a\nb.crt", "/" + "a" * 250, "~/station.crt"):
            with self.assertRaisesRegex(ConfigValidationError, "absolute path of plain characters"):
                RemoteAccess.from_dict({**BASE, "tls_cert_file": bad, "tls_key_file": KEY})
        with self.assertRaisesRegex(ConfigValidationError, "must be a string"):
            RemoteAccess.from_dict({**BASE, "tls_cert_file": 5, "tls_key_file": KEY})

    def test_tls_files_are_for_code_server_only(self) -> None:
        with self.assertRaisesRegex(ConfigValidationError, "'code-server' kind only"):
            RemoteAccess.from_dict({"kind": "ssh-remote", "port": 22022, "bind_address": "127.0.0.1", "tls_cert_file": CERT, "tls_key_file": KEY})

    def test_empty_strings_mean_no_tls(self) -> None:
        access = RemoteAccess.from_dict({**BASE, "tls_cert_file": "", "tls_key_file": ""})
        self.assertFalse(access.uses_tls())


if __name__ == "__main__":
    unittest.main()
